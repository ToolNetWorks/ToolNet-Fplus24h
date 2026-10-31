"""Facebook Publishing Worker lifecycle.

The Worker claims a PublishingJob, validates Account/Proxy/Group eligibility,
stages media, launches a browser, and interacts with the Facebook UI via
Playwright to publish anonymously.

In DRY_RUN mode, the Worker validates everything but never clicks Post.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from modules.facebook_publishing.models import (
    WorkerConfig, WorkerPublishJob, WorkerRunningOp, WorkerResultState,
)
from modules.facebook_publishing.services.config import WorkerSettings, load_settings
from modules.facebook_publishing.services.account_binding import (
    resolve_account_bundle, acquire_running_op, release_running_op,
    heartbeat_running_op, AccountProxyBindingError,
)
from modules.facebook_publishing.services.eligibility import (
    check_group_eligibility, GroupEligibilityResult,
)
from modules.facebook_publishing.services.media_stager import (
    MediaStager, MediaStagingError,
)
from modules.facebook_publishing.services.browser_manager import (
    BrowserManager, BrowserManagerError,
)
from modules.facebook_publishing.services.composer import (
    AnonymousComposer, AnonymousComposerError,
)
from modules.facebook_publishing.services.verification import (
    PublishingVerification, VerificationResult,
)
from modules.facebook_publishing.services.reconciliation import (
    reconcile_job_states, safe_transition_to_uncertain,
)
from modules.facebook_publishing.services.audit_log import AuditLogger
from modules.publishing.services.job_engine import (
    claim_due_job, prepare_job_media, begin_dispatch,
    confirm_published, flag_uncertain, fail_before_dispatch,
    JobEngineError, JobConflict,
)
from modules.publishing.services.media_selection import allocation_payload

logger = logging.getLogger(__name__)


class WorkerError(Exception):
    pass


class WorkerNotEnabledError(WorkerError):
    pass


class WorkerConcurrencyError(WorkerError):
    pass


@dataclass
class WorkerSession:
    """Ephemeral holder for a single Worker publishing session."""
    worker_id: str
    publish_job: WorkerPublishJob
    bundle: Optional[object] = None
    context: Optional[object] = None
    page: Optional[object] = None
    staged_images: Optional[list] = None
    image_ids: Optional[list] = None
    browser_manager: Optional[object] = None


def _validate_pipeline_enabled(pipeline_id, settings: WorkerSettings):
    """The Worker must be explicitly enabled before it can publish.

    Checks both the DB WorkerConfig and the env-level settings.
    """
    config = WorkerConfig.objects.filter(pipeline_id=pipeline_id).first()
    if config is None:
        if not settings.enabled:
            raise WorkerNotEnabledError(
                'No WorkerConfig for Pipeline and FACEBOOK_PUBLISHING_ENABLED=false. '
                'Worker is not enabled.'
            )
        # No DB config but env says enabled — still proceed but warn
        logger.warning(
            'No WorkerConfig found for Pipeline %s; using env settings only.',
            pipeline_id,
        )
        return config

    if not config.enabled:
        raise WorkerNotEnabledError(
            'WorkerConfig.enabled=false for this Pipeline. '
            'Set it to true to enable.'
        )
    return config


def _can_publish(settings: WorkerSettings, config: Optional[WorkerConfig]) -> bool:
    """Check whether real publishing is allowed RIGHT NOW.

    Both env-level and DB-level must agree.
    """
    env_enabled = settings.enabled
    env_dry_run = settings.dry_run
    db_enabled = config.enabled if config else False
    db_dry_run = config.dry_run if config else True

    # Publishing is only allowed when both agree it is enabled AND not dry_run
    if not env_enabled or not db_enabled:
        return False
    if env_dry_run or db_dry_run:
        return False
    return True


def _create_publish_job_record(*, pipeline_id, job, worker_id, settings,
                               account, group, proxy):
    """Create the WorkerPublishJob record, initialized to QUEUED."""
    worker_job = WorkerPublishJob.objects.create(
        job=job,
        pipeline_id=pipeline_id,
        account=account,
        group=group,
        proxy=proxy or account.assigned_proxy,
        worker_id=worker_id,
        state=WorkerResultState.QUEUED,
        attempt_number=job.attempt_count,
        dry_run=settings.dry_run,
    )
    return worker_job


def claim_job(*, pipeline_id, worker_id, lease_seconds=600):
    """Claim a due PublishingJob via the Job Engine.

    Returns the claim snapshot and WorkerPublishJob record, or None if no job.
    """
    settings = load_settings(pipeline_id)
    config = _validate_pipeline_enabled(pipeline_id, settings)

    if settings.dry_run:
        logger.info('Worker is in DRY_RUN mode for Pipeline %s.', pipeline_id)

    claim = claim_due_job(
        pipeline_id=pipeline_id, worker_id=worker_id,
    )
    if claim is None:
        return None

    job_snapshot = claim['job']
    from modules.publishing.models import PublishingJob
    job = PublishingJob.objects.select_related(
        'facebook_account', 'facebook_account__assigned_proxy__auth_secret',
        'facebook_account__cookie_secret',
        'facebook_group',
    ).get(pk=job_snapshot['id'], pipeline_id=pipeline_id)

    # Resolve the proxy for the account only if using PROXY mode
    proxy = None
    if settings.use_proxy:
        proxy = getattr(job.facebook_account, 'assigned_proxy', None)
        if proxy is None:
            from modules.proxies.models import ProxyEndpoint
            proxy = ProxyEndpoint.objects.select_related('auth_secret').filter(
                account_id=job.facebook_account_id, pipeline_id=pipeline_id,
            ).first()

    worker_job = _create_publish_job_record(
        pipeline_id=pipeline_id, job=job, worker_id=worker_id,
        settings=settings, account=job.facebook_account,
        group=job.facebook_group, proxy=proxy,
    )

    audit = AuditLogger(worker_id=worker_id, job_id=str(job.pk))
    audit.log_event('job_claimed', job_id=job_snapshot['id'])

    return {
        'job': job_snapshot,
        'claim_token': claim['claim_token'],
        'worker_job': worker_job,
        'settings': settings,
        'config': config,
        'audit': audit,
        'job_obj': job,
    }


def prepare_session(claim_result, settings: WorkerSettings):
    """Step 1: Validate Account/Proxy/Group and acquire concurrency lock.

    Returns a WorkerSession with the resolved AccountBundle.
    Updates WorkerPublishJob state: QUEUED -> PREPARING -> READY.
    """
    job = claim_result['job_obj']
    worker_job = claim_result['worker_job']
    audit = claim_result['audit']
    pipeline_id = job.pipeline_id

    worker_job.state = WorkerResultState.PREPARING
    worker_job.save(update_fields=['state'])
    audit.log_transition(
        from_state=WorkerResultState.QUEUED,
        to_state=WorkerResultState.PREPARING,
    )

    # Step 1a: Validate Account/Proxy binding (only if using PROXY mode)
    bundle = None
    if settings.use_proxy:
        try:
            bundle = resolve_account_bundle(
                pipeline_id=pipeline_id,
                account_id=job.facebook_account_id,
                group_id=job.facebook_group_id,
                worker_id=claim_result['audit']._worker_id,
                settings=settings,
            )
        except AccountProxyBindingError as exc:
            audit.log_error('ACCOUNT_PROXY_BINDING_FAILED', str(exc))
            worker_job.state = WorkerResultState.FAILED
            worker_job.error_code = 'ACCOUNT_PROXY_BINDING_FAILED'
            worker_job.error_detail = str(exc)[:2000]
            worker_job.save(update_fields=['state', 'error_code', 'error_detail'])
            raise WorkerError(f'Account/Proxy validation failed: {exc}') from exc
    else:
        # DIRECT mode: create a minimal bundle without proxy validation
        from modules.facebook_accounts.models import FacebookAccount
        from modules.facebook_groups.models import FacebookGroup
        from modules.publishing.scheduler_models import AccountGroupEligibility
        from django.utils import timezone
        from modules.facebook_publishing.services.account_binding import AccountBundle, _count_encrypted_cookies

        account = FacebookAccount.objects.select_related('cookie_secret').filter(
            pk=job.facebook_account_id, pipeline_id=pipeline_id,
            connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
        ).first()
        if account is None:
            raise WorkerError(
                f'Account {job.facebook_account_id} not found, not CONNECTED, or not in Pipeline {pipeline_id}.'
            )

        group = FacebookGroup.objects.filter(
            pk=job.facebook_group_id, pipeline_id=pipeline_id, is_enabled=True,
        ).first()
        if group is None:
            raise WorkerError(
                f'Group {job.facebook_group_id} not found, disabled, or not in Pipeline {pipeline_id}.'
            )

        now = timezone.now()
        eligibility = AccountGroupEligibility.objects.filter(
            pipeline_id=pipeline_id, account_id=account.pk, group_id=group.pk,
            state=AccountGroupEligibility.State.VERIFIED,
            can_post_anonymous=True,
            verified_at__lte=now, expires_at__gt=now,
        ).first()
        is_anonymous_enabled = eligibility is not None and eligibility.can_post_anonymous

        from modules.facebook_publishing.services.account_binding import _count_encrypted_cookies
        has_cookies, cookie_count = _count_encrypted_cookies(account.pk)

        bundle = AccountBundle(
            account_id=account.pk,
            account=account,
            proxy=None,
            pin=None,
            proxy_server_url='',
            encrypted_cookies_count=cookie_count,
            has_cookies=has_cookies,
            is_anonymous_enabled=is_anonymous_enabled,
        )

    # Step 1b: Check Group eligibility (anonymous required, membership ANY)
    eligibility = check_group_eligibility(
        pipeline_id=pipeline_id,
        account_id=job.facebook_account_id,
        group_id=job.facebook_group_id,
    )
    audit.log_event(
        'group_eligibility_checked',
        is_eligible=eligibility.is_eligible,
        can_post_anonymous=eligibility.can_post_anonymous,
        membership_status=eligibility.membership_status,
        reason_code=eligibility.reason_code,
    )

    if not eligibility.is_eligible:
        worker_job.state = WorkerResultState.FAILED
        worker_job.error_code = 'GROUP_ELIGIBILITY_FAILED'
        worker_job.error_detail = eligibility.reason_code
        worker_job.save(update_fields=['state', 'error_code', 'error_detail'])
        raise WorkerError(
            f'Group eligibility check failed: {eligibility.reason_code}'
        )

    if not eligibility.can_post_anonymous:
        worker_job.state = WorkerResultState.FAILED
        worker_job.error_code = 'NO_ANONYMOUS_PERMISSION'
        worker_job.error_detail = 'Anonymous posting is required but the Account lacks permission.'
        worker_job.save(update_fields=['state', 'error_code', 'error_detail'])
        raise WorkerError(
            'Anonymous posting is required but the Account lacks permission.'
        )

    # Step 1c: Acquire the running-op lock (concurrency guard)
    try:
        op = acquire_running_op(
            account_id=job.facebook_account_id,
            worker_id=claim_result['audit']._worker_id,
            publish_job=worker_job,
        )
    except Exception as exc:
        audit.log_error('CONCURRENCY_LOCK_FAILED', str(exc))
        worker_job.state = WorkerResultState.FAILED
        worker_job.error_code = 'CONCURRENCY_LOCK_FAILED'
        worker_job.save(update_fields=['state', 'error_code'])
        raise WorkerError(
            f'Account already has a running operation: {exc}'
        ) from exc

    worker_job.state = WorkerResultState.READY
    worker_job.save(update_fields=['state'])
    audit.log_transition(
        from_state=WorkerResultState.PREPARING,
        to_state=WorkerResultState.READY,
    )

    return WorkerSession(
        worker_id=claim_result['audit']._worker_id,
        publish_job=worker_job,
        bundle=bundle,
        staged_images=[],
        image_ids=[],
    )


def _resolve_media_image_ids(*, pipeline_id, job, allocation_payload):
    """Extract the list of AlbumImage UUIDs from the MediaAllocation payload.

    The allocation payload contains 'images' with 'image_id' (the AlbumImage UUID).
    """
    images = allocation_payload.get('images', []) if allocation_payload else []
    image_ids = []
    for img in images:
        image_id = img.get('image_id')
        if image_id:
            image_ids.append(image_id)
    return image_ids


def _resolve_caption(claim_result, settings: WorkerSettings):
    """Resolve the caption text: use AI Caption if enabled, else Job's caption."""
    pipeline_id = claim_result['job_obj'].pipeline_id
    from modules.publishing.caption_models import PipelineCaptionSettings, JobCaption

    cap_settings = PipelineCaptionSettings.objects.filter(
        pipeline_id=pipeline_id, enabled=True,
    ).first()

    if cap_settings and cap_settings.auto_generate and cap_settings.auto_approve:
        job_caption = JobCaption.objects.filter(
            job_id=claim_result['job_obj'].pk,
            state=JobCaption.State.APPROVED,
            settings_version=cap_settings.version,
        ).first()
        if job_caption:
            return job_caption.text

    return claim_result['job_obj'].caption


def prepare_media(claim_result, session, settings: WorkerSettings):
    """Step 2: Prepare media (images + caption) via existing systems.

    Calls prepare_job_media from the Job Engine to reserve images, then
    extracts the image IDs for the MediaStager.
    """
    job = claim_result['job_obj']
    claim_token = claim_result['claim_token']
    worker_job = session.publish_job
    audit = claim_result['audit']

    worker_job.state = WorkerResultState.PREPARING
    worker_job.save(update_fields=['state'])
    audit.log_transition(
        from_state=WorkerResultState.READY,
        to_state=WorkerResultState.PREPARING,
    )

    caption = _resolve_caption(claim_result, settings)

    # Reserve media via Job Engine — this also marks the allocation as consuming
    prepared = prepare_job_media(
        pipeline_id=job.pipeline_id,
        job_id=str(job.pk),
        claim_token=claim_token,
    )

    # Extract image IDs from the allocation payload
    image_ids = _resolve_media_image_ids(
        pipeline_id=job.pipeline_id, job=job, allocation_payload=prepared,
    )
    session.image_ids = image_ids
    session.staged_images = prepared

    worker_job.state = WorkerResultState.READY
    worker_job.save(update_fields=['state'])
    audit.log_transition(
        from_state=WorkerResultState.PREPARING,
        to_state=WorkerResultState.READY,
        caption_length=len(caption),
        image_count=len(image_ids),
    )

    return caption, prepared


def launch_browser(session, settings: WorkerSettings) -> BrowserManager:
    """Step 3: Launch a browser context bound to the Account's Proxy.

    Loads encrypted cookies from the existing FacebookAccount system.
    """
    browser_mgr = BrowserManager(settings)
    try:
        # Build proxy config with credentials for Playwright
        proxy_config = None
        if session.bundle and session.bundle.proxy:
            from modules.facebook_publishing.services.browser_manager import _build_proxy_config
            proxy_config = _build_proxy_config(session.bundle.proxy)

        context = browser_mgr.launch_context(proxy_config=proxy_config)

        # Load encrypted cookies from the existing system
        cookies_loaded, cookie_count = browser_mgr.load_account_cookies(
            context, session.bundle.account,
        )
        session.bundle  # keep reference
        session.context = context
        session.page = context.new_page()

        if not cookies_loaded:
            session.publish_job.add_audit(
                'warning', 'No encrypted cookies found for account.',
            )

        return browser_mgr
    except BrowserManagerError:
        raise
    except Exception as exc:
        raise WorkerError(f'Browser launch failed: {exc}') from exc


def run_dry_run(session, settings: WorkerSettings, eligibility, caption,
                claim_result):
    """DRY_RUN: validate everything but do NOT click Post or create a real post.

    Even if all checks pass, the PublishingJob remains in READY/CLAIMED state.
    The job's Job Engine state is NOT advanced (no begin_dispatch, no post).
    """
    audit = AuditLogger(
        worker_id=session.worker_id,
        job_id=str(session.publish_job.job_id),
    )
    browser_mgr = None

    try:
        # Step: Launch test browser
        browser_mgr = launch_browser(session, settings)
        audit.log_event('browser_launched_dry_run')

        # Step: Verify cookies loaded
        if session.bundle and session.bundle.has_cookies:
            audit.log_event(
                'encrypted_cookies_loaded',
                count=session.bundle.encrypted_cookies_count,
            )
        else:
            audit.log_event('no_encrypted_cookies',
                            detail='Worker will still attempt verification.')

        page = session.page

        # Step: Navigate to the Group
        group_url = session.publish_job.group.group_url
        page.goto(group_url, timeout=int(settings.browser_timeout_seconds) * 1000)
        page.wait_for_timeout(2000)
        audit.log_event('navigated_to_group_dry_run')

        # Step: Check anonymous posting option
        composer = AnonymousComposer(page, settings)
        anon_available = composer.check_anonymous_posting_available()
        audit.log_event(
            'anonymous_posting_checked',
            is_available=anon_available,
        )

        if not anon_available:
            worker_job = session.publish_job
            worker_job.state = WorkerResultState.FAILED
            worker_job.error_code = 'NO_ANONYMOUS_TOGGLE'
            worker_job.save(update_fields=['state', 'error_code'])
            audit.log_transition(
                from_state=WorkerResultState.READY,
                to_state=WorkerResultState.FAILED,
                reason='No anonymous posting toggle found',
            )
            # Release the job back to QUEUED for possible retry
            from modules.publishing.services.job_engine import fail_before_dispatch
            try:
                fail_before_dispatch(
                    pipeline_id=session.publish_job.pipeline_id,
                    job_id=str(session.publish_job.job_id),
                    claim_token=claim_result['claim_token'],
                    error_code='NO_ANONYMOUS_TOGGLE',
                    retry_delay_seconds=300,
                )
                audit.log_event('job_released_to_queue',
                                reason='Anonymous toggle not available')
            except Exception:
                pass
            return {
                'result': 'failure',
                'reason': 'Anonymous posting toggle not found on Group page.',
                'eligibility': {
                    'is_eligible': eligibility.is_eligible,
                    'can_post_anonymous': eligibility.can_post_anonymous,
                    'membership_status': eligibility.membership_status,
                },
            }

        # Step: Fill caption (within authorized environment, but do NOT submit)
        composer.fill_caption(caption)
        audit.log_event('caption_filled_dry_run', length=len(caption))

        # Step: Verify image can be downloaded from R2
        images_downloaded = 0
        stager = MediaStager(settings)
        try:
            if session.image_ids:
                staged = stager.stage_all(
                    pipeline_id=session.publish_job.pipeline_id,
                    image_ids=session.image_ids,
                )
                images_downloaded = len(staged)
                audit.log_event(
                    'images_downloaded_dry_run', count=images_downloaded,
                )
                # Attach images to page for verification (but don't submit)
                for img in staged:
                    try:
                        composer.attach_image(img.temp_path)
                    except Exception:
                        pass
        finally:
            stager.cleanup()

        # Do NOT click Post. Do NOT call begin_dispatch. Do NOT submit.
        audit.log_event('dry_run_ready_to_submit',
                        caption_length=len(caption),
                        anon_checked=anon_available,
                        images_downloaded=images_downloaded)

        worker_job = session.publish_job
        worker_job.state = WorkerResultState.READY
        worker_job.save(update_fields=['state'])

        # Release the job back to QUEUED so the Job Engine can manage it
        # The PUBLISHING JOB stays in its current state; we only update WorkerPublishJob
        audit.log_transition(
            from_state=WorkerResultState.READY,
            to_state=WorkerResultState.READY,
            note='DRY_RUN complete - no post submitted, job released to queue',
        )

        return {
            'result': 'success',
            'reason': 'DRY_RUN completed successfully. No post was submitted.',
            'eligibility': {
                'is_eligible': eligibility.is_eligible,
                'can_post_anonymous': eligibility.can_post_anonymous,
                'membership_status': eligibility.membership_status,
            },
            'media': {
                'images_count': images_downloaded,
                'image_ids': session.image_ids,
                'caption_length': len(caption),
            },
        }

    except WorkerError:
        raise
    except Exception as exc:
        audit.log_error('DRY_RUN_ERROR', str(exc))
        worker_job = session.publish_job
        worker_job.state = WorkerResultState.FAILED
        worker_job.error_code = 'DRY_RUN_ERROR'
        worker_job.error_detail = str(exc)[:2000]
        worker_job.save(update_fields=['state', 'error_code', 'error_detail'])
        raise WorkerError(f'DRY_RUN failed: {exc}') from exc
    finally:
        if browser_mgr:
            browser_mgr.close_context(session.context)
            browser_mgr.shutdown()


def run_publish(session, settings: WorkerSettings, eligibility, caption,
                claim_token, config):
    """Non-dry-run: submit the post and verify visibility.

    WARNING: This only runs when FACEBOOK_PUBLISHING_ENABLED=true AND
    FACEBOOK_PUBLISHING_DRY_RUN=false.
    """
    job = session.publish_job
    audit = AuditLogger(
        worker_id=session.worker_id,
        job_id=str(job.job_id),
    )
    browser_mgr = None
    stager = None

    try:
        # CRITICAL: Check can_publish immediately before any Post click
        if not _can_publish(settings, config):
            audit.log_error(
                'PUBLISH_NOT_ALLOWED',
                'Worker is in dry-run mode or disabled. Not submitting.',
            )
            raise WorkerError(
                'Real publishing is not enabled. '
                'Set FACEBOOK_PUBLISHING_ENABLED=true and '
                'FACEBOOK_PUBLISHING_DRY_RUN=false.'
            )

        # Step: Launch browser and load cookies
        browser_mgr = launch_browser(session, settings)
        audit.log_event('browser_launched_for_publish')

        page = session.page

        # Step: Navigate to the Group
        page.goto(
            session.publish_job.group.group_url,
            timeout=int(settings.browser_timeout_seconds) * 1000,
        )
        page.wait_for_timeout(2000)
        audit.log_event('navigated_to_group_for_publish')

        verification = PublishingVerification(page, settings)

        # Step: Check for CAPTCHA/checkpoint before proceeding
        checkpoint = verification.check_captcha_or_checkpoint()
        if checkpoint:
            audit.log_error(
                'CHECKPOINT_DETECTED',
                f'Facebook checkpoint: {checkpoint}. Not bypassing.',
                checkpoint_type=checkpoint,
            )
            job_obj = session.publish_job
            job_obj.state = WorkerResultState.FAILED
            job_obj.error_code = 'CHECKPOINT_DETECTED'
            job_obj.save(update_fields=['state', 'error_code'])
            safe_transition_to_uncertain(
                pipeline_id=job.pipeline_id,
                job_id=str(job.job_id),
                worker_job=job_obj,
                claim_token=claim_token,
                error_code='CHECKPOINT_DETECTED',
                audit=audit,
            )
            return {'result': 'failed', 'reason': f'Checkpoint: {checkpoint}'}

        # Step: Activate anonymous posting
        composer = AnonymousComposer(page, settings)
        anon_available = composer.check_anonymous_posting_available()
        if not anon_available:
            session.publish_job.state = WorkerResultState.FAILED
            session.publish_job.error_code = 'NO_ANONYMOUS_TOGGLE_AT_SUBMIT'
            session.publish_job.save(update_fields=['state', 'error_code'])
            return {'result': 'failed', 'reason': 'No anonymous toggle at submit time.'}

        composer.activate_anonymous()
        audit.log_event('anonymous_activated')

        # Step: Fill caption
        composer.fill_caption(caption)
        audit.log_event('caption_filled')

        # Step: Stage and attach images from R2
        stager = MediaStager(settings)
        staged_images = []
        try:
            if session.image_ids:
                staged_images = stager.stage_all(
                    pipeline_id=job.pipeline_id,
                    image_ids=session.image_ids,
                )
                audit.log_event(
                    'images_staged', count=len(staged_images),
                )
                for img in staged_images:
                    composer.attach_image(img.temp_path)

            # Step: Mark media as started (irreversible) and begin dispatch
            # This must happen BEFORE the actual Post click
            from modules.publishing.services.media_selection import mark_publishing_started
            mark_publishing_started(
                pipeline_id=job.pipeline_id,
                request_key=job.media_allocation.request_key,
            )
            audit.log_event('media_marked_started')

            begin_dispatch(
                pipeline_id=job.pipeline_id,
                job_id=str(job.job_id),
                claim_token=claim_token,
            )
            audit.log_event('dispatch_begun')

            session.publish_job.state = WorkerResultState.SUBMITTING
            session.publish_job.submitted_at = timezone.now()
            session.publish_job.save(update_fields=['state', 'submitted_at'])
            audit.log_transition(
                from_state=WorkerResultState.READY,
                to_state=WorkerResultState.SUBMITTING,
            )

            # Step: CRITICAL — re-check can_publish immediately before Post click
            if not _can_publish(settings, config):
                raise WorkerError('Publishing disabled at pre-submit check.')

            # Step: Submit post — this is the actual Facebook post creation
            composer.submit_post()
            audit.log_event('post_submitted')

            # Step: Verify visibility (never trust HTTP 200 or post_id alone)
            verification_result = verification.verify_post_visibility()
            audit.log_event(
                'verification_result',
                state=verification_result.state,
                external_post_id=verification_result.external_post_id,
            )

            session.publish_job.state = verification_result.state
            session.publish_job.external_post_id = verification_result.external_post_id or ''
            session.publish_job.verified_at = timezone.now()
            session.publish_job.save(
                update_fields=['state', 'external_post_id', 'verified_at']
            )

            # Step: Cross-check with Job Engine
            recon = reconcile_job_states(
                pipeline_id=job.pipeline_id,
                job_id=str(job.job_id),
                worker_job=session.publish_job,
                audit=audit,
            )

            if verification_result.state == 'PUBLISHED':
                confirm_published(
                    pipeline_id=job.pipeline_id,
                    job_id=str(job.job_id),
                    external_post_id=verification_result.external_post_id,
                )
                audit.log_transition(
                    from_state=WorkerResultState.SUBMITTING,
                    to_state=WorkerResultState.PUBLISHED,
                )
                return {
                    'result': 'published',
                    'post_id': verification_result.external_post_id,
                    'detail': verification_result.detail,
                }

            elif verification_result.state == 'PENDING_APPROVAL':
                safe_transition_to_uncertain(
                    pipeline_id=job.pipeline_id,
                    job_id=str(job.job_id),
                    worker_job=session.publish_job,
                    claim_token=claim_token,
                    error_code='PENDING_ADMIN_APPROVAL',
                    audit=audit,
                )
                return {
                    'result': 'pending_approval',
                    'detail': 'Post requires admin approval.',
                }

            else:
                safe_transition_to_uncertain(
                    pipeline_id=job.pipeline_id,
                    job_id=str(job.job_id),
                    worker_job=session.publish_job,
                    claim_token=claim_token,
                    error_code='VERIFICATION_FAILED',
                    audit=audit,
                )
                return {
                    'result': 'uncertain',
                    'detail': 'Visibility not verified. Not resending.',
                }

        finally:
            if stager:
                stager.cleanup()

    except WorkerError:
        raise
    except Exception as exc:
        audit.log_error('PUBLISH_ERROR', str(exc))
        session.publish_job.state = WorkerResultState.FAILED
        session.publish_job.error_code = 'PUBLISH_ERROR'
        session.publish_job.error_detail = str(exc)[:2000]
        session.publish_job.save(update_fields=['state', 'error_code', 'error_detail'])
        safe_transition_to_uncertain(
            pipeline_id=job.pipeline_id,
            job_id=str(job.job_id),
            worker_job=session.publish_job,
            claim_token=claim_token,
            error_code='PUBLISH_ERROR',
            audit=audit,
        )
        raise WorkerError(f'Publish failed: {exc}') from exc
    finally:
        if browser_mgr:
            browser_mgr.close_context(session.context)
            browser_mgr.shutdown()
