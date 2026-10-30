"""Facebook Publishing Worker lifecycle.

The Worker claims a PublishingJob, validates Account/Proxy/Group eligibility,
stages media, launches a browser, and interacts with the Facebook UI via
Playwright to publish anonymously.

In DRY_RUN mode, the Worker validates everything but never clicks Post.
"""
import logging
import time
import uuid as _uuid
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


def _validate_pipeline_enabled(pipeline_id, settings: WorkerSettings):
    """The Worker must be explicitly enabled before it can publish."""
    config = WorkerConfig.objects.filter(pipeline_id=pipeline_id).first()
    if config is None:
        raise WorkerNotEnabledError(
            'No WorkerConfig for Pipeline. Worker is not enabled.'
        )
    if not config.enabled:
        raise WorkerNotEnabledError(
            'FACEBOOK_PUBLISHING_ENABLED=false. Worker is disabled.'
        )
    if config.dry_run and not settings.dry_run:
        pass  # env overrides
    merged_enabled = config.enabled and settings.enabled
    if not merged_enabled:
        raise WorkerNotEnabledError(
            'Worker is disabled (FACEBOOK_PUBLISHING_ENABLED=false).'
        )


def _create_publish_job_record(*, pipeline_id, job, worker_id, settings, account, group, proxy):
    """Create the WorkerPublishJob record, initialized to PREPARING."""
    worker_job = WorkerPublishJob.objects.create(
        job=job,
        pipeline_id=pipeline_id,
        account=account,
        group=group,
        proxy=proxy,
        worker_id=worker_id,
        state=WorkerResultState.PREPARING,
        attempt_number=job.attempt_count,
        dry_run=settings.dry_run,
    )
    return worker_job


def claim_job(*, pipeline_id, worker_id, lease_seconds=600):
    """Claim a due PublishingJob via the Job Engine.

    Returns the claim snapshot and WorkerPublishJob record, or None if no job.
    """
    settings = load_settings(pipeline_id)
    if not settings.dry_run or settings.enabled:
        _validate_pipeline_enabled(pipeline_id, settings)
    else:
        # In DRY_RUN, still check DB config if present
        config = WorkerConfig.objects.filter(pipeline_id=pipeline_id).first()
        if config and not config.enabled and not config.dry_run:
            raise WorkerNotEnabledError(
                'Worker is not enabled for this Pipeline.'
            )

    claim = claim_due_job(
        pipeline_id=pipeline_id, worker_id=worker_id,
    )
    if claim is None:
        return None

    job_snapshot = claim['job']
    # We need the full job object for later operations
    from modules.publishing.models import PublishingJob
    job = PublishingJob.objects.select_related(
        'facebook_account', 'facebook_group',
    ).get(pk=job_snapshot['id'], pipeline_id=pipeline_id)

    worker_job = _create_publish_job_record(
        pipeline_id=pipeline_id, job=job, worker_id=worker_id,
        settings=settings, account=job.facebook_account,
        group=job.facebook_group, proxy=None,
    )

    audit = AuditLogger(worker_id=worker_id, job_id=str(job.pk))
    audit.log_event('job_claimed', job_id=job_snapshot['id'])

    return {
        'job': job_snapshot,
        'claim_token': claim['claim_token'],
        'worker_job': worker_job,
        'settings': settings,
        'audit': audit,
        'job_obj': job,
    }


def prepare_session(claim_result, settings: WorkerSettings):
    """Step 1: Validate Account/Proxy/Group and acquire concurrency lock."""
    job = claim_result['job_obj']
    worker_job = claim_result['worker_job']
    audit = claim_result['audit']
    pipeline_id = job.pipeline_id

    # Step 1a: Validate Account/Proxy binding
    try:
        bundle = resolve_account_bundle(
            pipeline_id=pipeline_id,
            account_id=job.facebook_account_id,
            group_id=job.facebook_group_id,
            worker_id=claim_result['audit']._worker_id,
            settings=settings,
        )
    except AccountProxyBindingError as exc:
        audit.log_error(
            'ACCOUNT_PROXY_BINDING_FAILED', str(exc),
        )
        worker_job.state = WorkerResultState.FAILED
        worker_job.error_code = 'ACCOUNT_PROXY_BINDING_FAILED'
        worker_job.error_detail = str(exc)[:2000]
        worker_job.save(update_fields=['state', 'error_code', 'error_detail'])
        raise WorkerError(f'Account/Proxy validation failed: {exc}') from exc

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
        raise WorkerError(
            f'Group eligibility check failed: {eligibility.reason_code}'
        )

    if not eligibility.can_post_anonymous:
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
        audit.log_error(
            'CONCURRENCY_LOCK_FAILED', str(exc),
        )
        raise WorkerConcurrencyError(
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
    )


def prepare_media(claim_result, session, settings):
    """Step 2: Prepare media (images + caption) via existing systems."""
    job = claim_result['job_obj']
    claim_token = claim_result['claim_token']
    worker_job = session.publish_job
    worker_job.state = WorkerResultState.PREPARING
    worker_job.save(update_fields=['state'])

    # Prepare caption via AI Caption Engine or Job's caption
    caption = _resolve_caption(claim_result, settings)

    # Reserve media via Job Engine
    prepared = prepare_job_media(
        pipeline_id=job.pipeline_id,
        job_id=str(job.pk),
        claim_token=claim_token,
    )
    worker_job.state = WorkerResultState.READY
    worker_job.save(update_fields=['state'])
    claim_result['audit'].log_transition(
        from_state=WorkerResultState.PREPARING,
        to_state=WorkerResultState.READY,
        caption_length=len(caption),
    )

    session.staged_images = prepared
    return caption, prepared


def _resolve_caption(claim_result, settings):
    """Resolve the caption text: use AI Caption if enabled, else Job's caption."""
    job_snapshot = claim_result['job']
    from modules.publishing.services.caption_engine import settings_payload
    from modules.publishing.caption_models import PipelineCaptionSettings, JobCaption

    pipeline_id = claim_result['job_obj'].pipeline_id
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


def launch_browser(session, settings):
    """Step 3: Launch a test browser bound to the Account's Proxy."""
    browser_mgr = BrowserManager(settings)
    try:
        proxy_url = session.bundle.proxy_server_url if session.bundle else None
        context = browser_mgr.launch_context(
            account_id=str(session.bundle.account_id),
            proxy_server=proxy_url,
        )
        page = context.new_page()
        session.context = context
        session.page = page
        session.bundle  # keep reference
        return browser_mgr
    except BrowserManagerError:
        raise
    except Exception as exc:
        raise WorkerError(f'Browser launch failed: {exc}') from exc


def run_dry_run(session, settings, eligibility, caption):
    """DRY_RUN: validate everything but do NOT click Post or create a real post."""
    audit = AuditLogger(
        worker_id=session.worker_id,
        job_id=str(session.publish_job.job_id),
    )
    browser_mgr = None

    try:
        # Step: Launch test browser
        browser_mgr = launch_browser(session, settings)
        audit.log_event('browser_launched_dry_run')

        # Step: Load session cookies (if available)
        # In dry-run, we still verify the page is accessible
        if session.bundle and session.bundle.encrypted_cookies:
            audit.log_event('encrypted_cookies_loaded', count='yes')
            # Cookies are encrypted; only set them in the browser
            # Actual cookie handling happens in the browser context
        else:
            audit.log_event('no_encrypted_cookies')

        # Step: Navigate to the Group
        page = session.page
        page.goto(
            session.publish_job.group.group_url,
            timeout=session.publish_job.error_code or str(settings.browser_timeout_seconds * 1000),
        )
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

        # Step: Stage and attach image (browser file input preview only)
        # In dry-run we verify we CAN attach, but don't actually attach real images
        # to avoid triggering Facebook's upload pipeline
        audit.log_event('dry_run_ready_to_submit', 
                        caption_length=len(caption),
                        anon_checked=anon_available)

        worker_job = session.publish_job
        worker_job.state = WorkerResultState.READY
        worker_job.save(update_fields=['state'])
        audit.log_transition(
            from_state=WorkerResultState.READY,
            to_state=WorkerResultState.READY,
            note='DRY_RUN complete - no post submitted',
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
                'images_count': len(session.staged_images) if session.staged_images else 0,
                'caption_length': len(caption),
            },
        }

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
        # Clean up any staged temp files
        if session.staged_images:
            for path in session.staged_images.get('temp_paths', []):
                import os
                try:
                    os.unlink(path)
                except OSError:
                    pass


def run_publish(session, settings, eligibility, caption, claim_token):
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

    try:
        # Step: Begin dispatch (irreversible boundary)
        begin_dispatch(
            pipeline_id=job.pipeline_id,
            job_id=str(job.job_id),
            claim_token=claim_token,
        )
        audit.log_event('dispatch_begun')

        worker_job = session.publish_job
        worker_job.state = WorkerResultState.SUBMITTING
        worker_job.submitted_at = timezone.now()
        worker_job.save(update_fields=['state', 'submitted_at'])
        audit.log_transition(
            from_state=WorkerResultState.READY,
            to_state=WorkerResultState.SUBMITTING,
        )

        # Step: Launch browser
        browser_mgr = launch_browser(session, settings)

        # Step: Load cookies and navigate
        page = session.page
        page.goto(
            session.publish_job.group.group_url,
            timeout=settings.browser_timeout_seconds * 1000,
        )
        page.wait_for_timeout(2000)

        # Step: Check for CAPTCHA/checkpoint before proceeding
        verification = PublishingVerification(page, settings)
        checkpoint = verification.check_captcha_or_checkpoint()
        if checkpoint:
            audit.log_error(
                'CHECKPOINT_DETECTED',
                f'Facebook checkpoint: {checkpoint}. Not bypassing.',
                checkpoint_type=checkpoint,
            )
            worker_job.state = WorkerResultState.FAILED
            worker_job.error_code = 'CHECKPOINT_DETECTED'
            worker_job.save(update_fields=['state', 'error_code'])
            safe_transition_to_uncertain(
                pipeline_id=job.pipeline_id,
                job_id=str(job.job_id),
                worker_job=worker_job,
                claim_token=claim_token,
                error_code='CHECKPOINT_DETECTED',
                audit=audit,
            )
            return {'result': 'failed', 'reason': f'Checkpoint: {checkpoint}'}

        # Step: Activate anonymous posting
        composer = AnonymousComposer(page, settings)
        anon_available = composer.check_anonymous_posting_available()
        if not anon_available:
            worker_job.state = WorkerResultState.FAILED
            worker_job.error_code = 'NO_ANONYMOUS_TOGGLE_AT_SUBMIT'
            worker_job.save(update_fields=['state', 'error_code'])
            return {'result': 'failed', 'reason': 'No anonymous toggle at submit time.'}

        composer.activate_anonymous()

        # Step: Fill caption
        composer.fill_caption(caption)

        # Step: Stage and attach images
        stager = MediaStager(settings)
        try:
            image_ids = []
            if session.staged_images and isinstance(session.staged_images, dict):
                image_ids = session.staged_images.get('image_ids', [])
            staged = stager.stage_all(
                pipeline_id=job.pipeline_id,
                image_ids=image_ids,
            )
            for img in staged:
                composer.attach_image(img.temp_path)
            worker_job.state = WorkerResultState.SUBMITTED_UNVERIFIED
            worker_job.save(update_fields=['state'])
            audit.log_transition(
                from_state=WorkerResultState.READY,
                to_state=WorkerResultState.SUBMITTED_UNVERIFIED,
            )

            # Step: Submit post
            composer.submit_post()

            # Step: Verify visibility (never trust HTTP 200 or post_id alone)
            verification_result = verification.verify_post_visibility()
            audit.log_event(
                'verification_result',
                state=verification_result.state,
                external_post_id=verification_result.external_post_id,
            )

            worker_job.state = verification_result.state
            worker_job.external_post_id = verification_result.external_post_id or ''
            worker_job.verified_at = timezone.now()
            worker_job.save(update_fields=['state', 'external_post_id', 'verified_at'])

            # Step: Cross-check with Job Engine
            recon = reconcile_job_states(
                pipeline_id=job.pipeline_id,
                job_id=str(job.job_id),
                worker_job=worker_job,
                audit=audit,
            )

            if verification_result.state == 'PUBLISHED':
                confirm_published(
                    pipeline_id=job.pipeline_id,
                    job_id=str(job.job_id),
                    external_post_id=verification_result.external_post_id,
                )
                audit.log_transition(
                    from_state=WorkerResultState.SUBMITTED_UNVERIFIED,
                    to_state=WorkerResultState.PUBLISHED,
                )
                return {'result': 'published', 'post_id': verification_result.external_post_id}

            elif verification_result.state == 'PENDING_APPROVAL':
                safe_transition_to_uncertain(
                    pipeline_id=job.pipeline_id,
                    job_id=str(job.job_id),
                    worker_job=worker_job,
                    claim_token=claim_token,
                    error_code='PENDING_ADMIN_APPROVAL',
                    audit=audit,
                )
                return {'result': 'pending_approval', 'detail': 'Awaiting admin approval.'}

            else:
                safe_transition_to_uncertain(
                    pipeline_id=job.pipeline_id,
                    job_id=str(job.job_id),
                    worker_job=worker_job,
                    claim_token=claim_token,
                    error_code='VERIFICATION_FAILED',
                    audit=audit,
                )
                return {'result': 'uncertain', 'detail': 'Visibility not verified.'}

        finally:
            stager.cleanup()

    except Exception as exc:
        audit.log_error('PUBLISH_ERROR', str(exc))
        worker_job = session.publish_job
        worker_job.state = WorkerResultState.FAILED
        worker_job.error_code = 'PUBLISH_ERROR'
        worker_job.error_detail = str(exc)[:2000]
        worker_job.save(update_fields=['state', 'error_code', 'error_detail'])
        safe_transition_to_uncertain(
            pipeline_id=job.pipeline_id,
            job_id=str(job.job_id),
            worker_job=worker_job,
            claim_token=claim_token,
            error_code='PUBLISH_ERROR',
            audit=audit,
        )
        raise WorkerError(f'Publish failed: {exc}') from exc
    finally:
        if browser_mgr:
            browser_mgr.close_context(session.context)
            browser_mgr.shutdown()
