"""Facebook Publishing Worker lifecycle.

The Worker claims a PublishingJob, validates Account/Proxy/Group eligibility,
stages media, launches a browser, and interacts with the Facebook UI via
Playwright to publish anonymously.

In DRY_RUN mode, the Worker validates everything but never clicks Post.
"""
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional
from asgiref.sync import sync_to_async

from django.db import transaction
from django.utils import timezone


def _db_call(func, *args, **kwargs):
    """Run ORM work in a separate thread while Playwright owns this thread's loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return func(*args, **kwargs)
    from django.db import close_old_connections
    def invoke():
        try:
            return func(*args, **kwargs)
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(invoke).result()


def _safe_save(model_instance, **kwargs):
    """Persist state or raise; never silently lose a publishing state change."""
    return _db_call(model_instance.save, **kwargs)

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
from modules.facebook_publishing.services.rules_confirmation import inspect_rules_prompt, find_rules_prompt, response_fields
from modules.facebook_publishing.services.reconciliation import (
    reconcile_job_states, safe_transition_to_uncertain,
)
from modules.facebook_publishing.services.audit_log import AuditLogger
from modules.publishing.services.job_engine import (
    claim_due_job, prepare_job_media, begin_dispatch,
    confirm_submit_clicked, confirm_published, flag_uncertain, fail_before_dispatch,
    JobEngineError, JobConflict,
)
from modules.publishing.services.media_selection import allocation_payload

logger = logging.getLogger(__name__)


@transaction.atomic
def _record_submit_click(*, pipeline_id, job_id, claim_token, worker_job_id):
    confirm_submit_clicked(pipeline_id=pipeline_id, job_id=job_id, claim_token=claim_token,
                           worker_job_id=worker_job_id)
    worker_job = WorkerPublishJob.objects.select_for_update().get(pk=worker_job_id, job_id=job_id)
    worker_job.state = WorkerResultState.SUBMITTED
    worker_job.finalized_at = timezone.now()
    worker_job.error_code = ''
    worker_job.error_detail = ''
    worker_job.save(update_fields=['state', 'finalized_at', 'error_code', 'error_detail'])


class WorkerError(Exception):
    pass


class WorkerNotEnabledError(WorkerError):
    pass


class WorkerConcurrencyError(WorkerError):
    pass


def _wait_for_rules_review(*, session, page, prompt, audit):
    """Keep this browser alive for an authenticated, single-use decision."""
    import re
    from datetime import timedelta
    from modules.facebook_publishing.models import RulesReview
    from modules.facebook_publishing.services.rules_review import (
        create_review, poll_review, consume_approval, finish_review, stop_review, RulesReviewConflict,
    )
    review_id = _db_call(create_review, worker_id=session.publish_job.pk,
                        prompt=prompt, expires_at=timezone.now() + timedelta(minutes=10))
    audit.log_event('rules_confirmation_required', review_id=str(review_id),
                    checkbox_count=prompt.checkbox_count,
                    response_field_count=prompt.response_field_count)
    try:
        missing_prompt_checks = 0
        while True:
            state, expires_at = _db_call(poll_review, review_id=review_id,
                                         worker_job_id=session.publish_job.pk)
            if state == RulesReview.State.REJECTED:
                _db_call(stop_review, review_id=review_id)
                return {'result': 'rules_rejected', 'detail': 'Người dùng từ chối; không gửi lại.'}
            if expires_at <= timezone.now():
                _db_call(stop_review, review_id=review_id, expired=True)
                return {'result': 'uncertain', 'detail': 'Phiên xác nhận hết hạn; cần đối soát.'}
            if state == RulesReview.State.APPROVED:
                break
            if state != RulesReview.State.PENDING:
                raise RulesReviewConflict('Yêu cầu xác nhận không còn chờ.')
            if page.is_closed():
                _db_call(stop_review, review_id=review_id, expired=True)
                return {'result': 'uncertain', 'detail': 'Phiên browser đã đóng; cần đối soát.'}
            # A changed or vanished prompt can mean expiry or a checkpoint.
            # Never recreate the composer or assume that an earlier post failed.
            found = find_rules_prompt(page)
            missing_prompt_checks = 0 if found else missing_prompt_checks + 1
            if missing_prompt_checks >= 3:
                _db_call(stop_review, review_id=review_id, expired=True)
                return {'result': 'uncertain', 'detail': 'Phiên xác nhận không còn hiển thị; cần đối soát.'}
            page.wait_for_timeout(1000)

        current = inspect_rules_prompt(page)
        if (not current or current.digest != prompt.digest or current.questions != prompt.questions or
                current.checkbox_count != prompt.checkbox_count):
            raise RulesReviewConflict('Nội dung Facebook đã thay đổi hoặc cần câu trả lời.')
        found = find_rules_prompt(page)
        if not found:
            raise RulesReviewConflict('Không còn màn hình quy tắc.')
        dialog, _ = found
        checkboxes = dialog.get_by_role('checkbox')
        # Only explicitly labelled rule-agreement controls can be selected.
        agreement = re.compile(r'^(tôi (đã đọc và )?đồng ý.*quy tắc.*|đồng ý.*quy tắc.*|i (have read and )?agree.*rules.*|agree.*rules.*)$', re.I)
        for i in range(checkboxes.count()):
            item = checkboxes.nth(i)
            if not item.is_visible() or not item.is_enabled():
                raise RulesReviewConflict('Không xác minh được checkbox quy tắc.')
            if not item.is_checked():
                label = item.evaluate("e => e.labels?.[0]?.innerText || e.getAttribute('aria-label') || e.closest('label')?.innerText || ''")
                if not agreement.fullmatch(' '.join(label.split())):
                    raise RulesReviewConflict('Checkbox không phải xác nhận quy tắc rõ ràng.')
        submit = dialog.get_by_role('button', name=re.compile(r'^(gửi|submit|send)$', re.I))
        if submit.count() != 1 or not submit.first.is_visible():
            raise RulesReviewConflict('Không tìm thấy nút Gửi duy nhất.')
        # Commit consumption before any irreversible click; crashes never retry.
        answers = _db_call(consume_approval, review_id=review_id, digest=current.digest)
        fields = response_fields(dialog)
        visible_fields = [fields.nth(i) for i in range(fields.count()) if fields.nth(i).is_visible()]
        if len(visible_fields) != len(answers):
            raise RulesReviewConflict('Danh sách câu hỏi đã thay đổi.')
        for field, answer in zip(visible_fields, answers):
            field.fill(answer, timeout=5000)
            if field.input_value() != answer:
                raise RulesReviewConflict('Không thể xác minh câu trả lời.')
        for i in range(checkboxes.count()):
            item = checkboxes.nth(i)
            if not item.is_checked():
                item.check(timeout=5000)
        latest = inspect_rules_prompt(page)
        if (not latest or latest.digest != prompt.digest or latest.response_field_count != prompt.response_field_count or
                latest.checkbox_count != prompt.checkbox_count or
                latest.checked_count != latest.checkbox_count):
            raise RulesReviewConflict('Quy tắc hoặc trạng thái checkbox đã thay đổi.')
        if not submit.first.is_enabled():
            raise RulesReviewConflict('Facebook chưa cho phép gửi quy tắc.')
        submit.first.click(timeout=10000)
        page.wait_for_timeout(1000)
        _db_call(finish_review, review_id=review_id, state=RulesReview.State.SUBMITTED)
        audit.log_event('rules_submit_attempted', review_id=str(review_id))
        return None
    except Exception:
        _db_call(finish_review, review_id=review_id, state=RulesReview.State.UNCERTAIN)
        raise


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
    # Only use account.assigned_proxy if proxy not provided and we're in proxy mode
    final_proxy = proxy
    if proxy is None and settings.use_proxy:
        try:
            final_proxy = account.assigned_proxy
        except Exception:
            final_proxy = None

    worker_job = WorkerPublishJob.objects.create(
        job=job,
        pipeline_id=pipeline_id,
        account=account,
        group=group,
        proxy=final_proxy,
        worker_id=worker_id,
        state=WorkerResultState.QUEUED,
        attempt_number=job.attempt_count,
        dry_run=settings.dry_run,
    )
    return worker_job


def claim_job(*, pipeline_id, worker_id, lease_seconds=600, job_id=None):
    """Claim a due PublishingJob via the Job Engine.

    Returns the claim snapshot and WorkerPublishJob record, or None if no job.
    """
    settings = load_settings(pipeline_id)
    config = _validate_pipeline_enabled(pipeline_id, settings)

    if settings.dry_run:
        logger.info('Worker is in DRY_RUN mode for Pipeline %s.', pipeline_id)

    claim = claim_due_job(
        pipeline_id=pipeline_id, worker_id=worker_id, lease_seconds=lease_seconds,
        job_id=job_id,
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
        try:
            proxy = job.facebook_account.assigned_proxy
        except Exception:
            proxy = None
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
    _safe_save(worker_job, update_fields=['state'])
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
            _safe_save(worker_job, update_fields=['state', 'error_code', 'error_detail'])
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
        _safe_save(worker_job, update_fields=['state', 'error_code', 'error_detail'])
        raise WorkerError(
            f'Group eligibility check failed: {eligibility.reason_code}'
        )

    if not eligibility.can_post_anonymous:
        worker_job.state = WorkerResultState.FAILED
        worker_job.error_code = 'NO_ANONYMOUS_PERMISSION'
        worker_job.error_detail = 'Anonymous posting is required but the Account lacks permission.'
        _safe_save(worker_job, update_fields=['state', 'error_code', 'error_detail'])
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
        _safe_save(worker_job, update_fields=['state', 'error_code'])
        raise WorkerError(
            f'Account already has a running operation: {exc}'
        ) from exc

    worker_job.state = WorkerResultState.READY
    _safe_save(worker_job, update_fields=['state'])
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
    _safe_save(worker_job, update_fields=['state'])
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
    job.refresh_from_db(fields=['media_allocation'])
    prepared = allocation_payload(job.media_allocation)

    # Extract image IDs from the allocation payload
    image_ids = _resolve_media_image_ids(
        pipeline_id=job.pipeline_id, job=job, allocation_payload=prepared,
    )
    session.image_ids = image_ids
    session.staged_images = prepared

    worker_job.state = WorkerResultState.READY
    _safe_save(worker_job, update_fields=['state'])
    audit.log_transition(
        from_state=WorkerResultState.PREPARING,
        to_state=WorkerResultState.READY,
        caption_length=len(caption),
        image_count=len(image_ids),
    )

    return caption, prepared


def launch_browser(session, settings: WorkerSettings, audit=None) -> BrowserManager:
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
            _db_call(session.publish_job.add_audit,
                'warning', 'No encrypted cookies found for account.',
            )

        # Verify account identity against Facebook session
        page = session.page
        page.goto('https://www.facebook.com/', timeout=int(settings.browser_timeout_seconds) * 1000)
        page.wait_for_timeout(2000)
        account_verified = browser_mgr.verify_account_identity(
            page, session.bundle.account.label,
        )
        audit.log_event(
            'account_identity_verified',
            verified=account_verified,
        )
        if not account_verified:
            raise WorkerError(
                'Facebook account identity verification failed. '
                'Logged-in account does not match expected account.'
            )

        return browser_mgr
    except BrowserManagerError:
        raise
    except Exception as exc:
        raise WorkerError(f'Browser launch failed: {exc}') from exc


def run_dry_run(session, settings: WorkerSettings, eligibility, caption,
                claim_result):
    """DRY_RUN: validate everything but do NOT click Post or create a real post.

    New flow:
    1. Open the Group.
    2. Verify the correct account (browser_manager).
    3. Open the composer.
    4. Check anonymous posting permission.
    5. Enable anonymous mode.
    6. Verify the anonymous author.
    7. Fill in the approved Caption.
    8. Verify the R2 image.
    9. Stop before the Post button.

    Even if all checks pass, the PublishingJob remains in READY/CLAIMED state.
    The job's Job Engine state is NOT advanced (no begin_dispatch, no post).
    """
    audit = AuditLogger(
        worker_id=session.worker_id,
        job_id=str(session.publish_job.job_id),
    )
    browser_mgr = None

    try:
        # Step 1: Launch test browser
        browser_mgr = launch_browser(session, settings, audit)
        audit.log_event('browser_launched_dry_run')

        # Step 2: Verify cookies loaded
        if session.bundle and session.bundle.has_cookies:
            audit.log_event(
                'encrypted_cookies_loaded',
                count=session.bundle.encrypted_cookies_count,
            )
        else:
            audit.log_event('no_encrypted_cookies',
                            detail='Worker will still attempt verification.')

        page = session.page

        # Step 3: Navigate to the Group
        group_url = session.publish_job.group.group_url
        page.goto(group_url, timeout=int(settings.browser_timeout_seconds) * 1000)
        page.wait_for_timeout(2000)
        audit.log_event('navigated_to_group_dry_run')

        # Step 4: Open the composer
        composer = AnonymousComposer(page, settings, session.bundle.account.label)
        composer.open_composer()
        audit.log_event('composer_opened_dry_run')

        composer.open_author_menu()
        audit.log_event('author_menu_opened_dry_run')

        # Step 5: Check anonymous posting permission inside composer
        anon_available = composer.check_anonymous_posting_available()
        audit.log_event(
            'anonymous_posting_checked',
            is_available=anon_available,
        )

        if not anon_available:
            worker_job = session.publish_job
            worker_job.state = WorkerResultState.FAILED
            worker_job.error_code = 'NO_ANONYMOUS_TOGGLE'
            _safe_save(worker_job, update_fields=['state', 'error_code'])
            audit.log_transition(
                from_state=WorkerResultState.READY,
                to_state=WorkerResultState.FAILED,
                reason='No anonymous posting toggle found in composer',
            )
            # Release the job back to QUEUED for possible retry
            from modules.publishing.services.job_engine import fail_before_dispatch
            try:
                _db_call(fail_before_dispatch,
                    pipeline_id=session.publish_job.pipeline_id,
                    job_id=str(session.publish_job.job_id),
                    claim_token=claim_result['claim_token'],
                    error_code='NO_ANONYMOUS_TOGGLE',
                    retry_delay_seconds=300,
                )
                audit.log_event('job_released_to_queue',
                                reason='Anonymous toggle not available in composer')
            except Exception:
                pass
            return {
                'result': 'failure',
                'reason': 'Anonymous posting toggle not found in composer.',
                'eligibility': {
                    'is_eligible': eligibility.is_eligible,
                    'can_post_anonymous': eligibility.can_post_anonymous,
                    'membership_status': eligibility.membership_status,
                },
            }

        # Step 6: Enable anonymous mode
        anon_result = composer.activate_anonymous()
        audit.log_event(
            'anonymous_activation_result',
            success=anon_result.success,
            detail=anon_result.detail,
        )
        if not anon_result.success:
            worker_job = session.publish_job
            worker_job.state = WorkerResultState.FAILED
            worker_job.error_code = 'ANONYMOUS_UI_UNCONFIRMED'
            _safe_save(worker_job, update_fields=['state', 'error_code'])
            audit.log_transition(
                from_state=WorkerResultState.READY,
                to_state=WorkerResultState.FAILED,
                reason='Anonymous mode could not be confirmed as enabled',
            )
            from modules.publishing.services.job_engine import fail_before_dispatch
            try:
                _db_call(fail_before_dispatch,
                    pipeline_id=session.publish_job.pipeline_id,
                    job_id=str(session.publish_job.job_id),
                    claim_token=claim_result['claim_token'],
                    error_code='ANONYMOUS_UI_UNCONFIRMED',
                    retry_delay_seconds=300,
                )
            except Exception:
                pass
            return {
                'result': 'failure',
                'reason': 'Anonymous mode could not be confirmed as enabled in composer.',
                'eligibility': {
                    'is_eligible': eligibility.is_eligible,
                    'can_post_anonymous': eligibility.can_post_anonymous,
                    'membership_status': eligibility.membership_status,
                },
            }

        # Verify anonymous author state
        anon_enabled = composer.is_anonymous_enabled()
        audit.log_event(
            'anonymous_author_verified',
            enabled=anon_enabled,
        )
        if not anon_enabled:
            raise WorkerError('Anonymous author could not be verified.')

        session.publish_job.state = WorkerResultState.ANONYMOUS_ENABLED
        _safe_save(session.publish_job, update_fields=['state'])

        composer.fill_caption(caption)
        audit.log_event('caption_filled_dry_run', length=len(caption))
        # Stage and verify the image without submitting.
        images_downloaded = 0
        stager = MediaStager(settings)
        staged = []
        try:
            if session.image_ids:
                staged = _db_call(stager.stage_all,
                    pipeline_id=session.publish_job.pipeline_id,
                    image_ids=session.image_ids,
                )
                images_downloaded = len(staged)
                audit.log_event(
                    'images_downloaded_dry_run', count=images_downloaded,
                )
                for img in staged:
                    composer.attach_image(img.temp_path)
            if not staged:
                raise WorkerError('No image was staged for the dry run.')
            if not composer.verify_caption(caption) or not composer.is_anonymous_enabled():
                raise WorkerError('Caption or anonymous author changed during media upload.')
        finally:
            stager.cleanup()

        # Step 9: Stop before Post button (DRY_RUN)
        audit.log_event('dry_run_ready_to_submit',
                        caption_length=len(caption),
                        anon_checked=anon_available,
                        anon_enabled=anon_enabled,
                        images_downloaded=images_downloaded)

        worker_job = session.publish_job
        worker_job.state = WorkerResultState.READY
        _safe_save(worker_job, update_fields=['state'])

        # Release the job back to QUEUED so the Job Engine can manage it
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
            'anonymous': {
                'available': anon_available,
                'enabled': anon_enabled,
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
        try:
            _safe_save(worker_job, update_fields=['state', 'error_code', 'error_detail'])
        except Exception:
            pass  # DB write may fail after Playwright; job state will be stale
        raise WorkerError(f'DRY_RUN failed: {exc}') from exc
    finally:
        if browser_mgr:
            browser_mgr.close_context(session.context)
            browser_mgr.shutdown()


def run_publish(session, settings: WorkerSettings, eligibility, caption,
                claim_token, config):
    """Non-dry-run: click Post once and record the click without a visibility claim.

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
    dispatch_started = False

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
        browser_mgr = launch_browser(session, settings, audit)
        audit.log_event('browser_launched_for_publish')

        page = session.page

        # Step: Navigate to the Group
        page.goto(
            session.publish_job.group.group_url,
            timeout=int(settings.browser_timeout_seconds) * 1000,
        )
        page.wait_for_timeout(2000)
        audit.log_event('navigated_to_group_for_publish')

        verification = PublishingVerification(page, settings, expected_caption=caption,
                                              monitor_rules=True)

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
            _safe_save(job_obj, update_fields=['state', 'error_code'])
            _db_call(safe_transition_to_uncertain,
                pipeline_id=job.pipeline_id,
                job_id=str(job.job_id),
                worker_job=job_obj,
                claim_token=claim_token,
                error_code='CHECKPOINT_DETECTED',
                audit=audit,
            )
            return {'result': 'failed', 'reason': f'Checkpoint: {checkpoint}'}

        # Step: Open composer
        composer = AnonymousComposer(page, settings, session.bundle.account.label)
        composer.open_composer()
        audit.log_event('composer_opened_for_publish')

        composer.open_author_menu()
        audit.log_event('author_menu_opened_for_publish')

        # Step: Activate anonymous posting
        anon_available = composer.check_anonymous_posting_available()
        if not anon_available:
            session.publish_job.state = WorkerResultState.FAILED
            session.publish_job.error_code = 'NO_ANONYMOUS_TOGGLE_AT_SUBMIT'
            _safe_save(session.publish_job, update_fields=['state', 'error_code'])
            return {'result': 'failed', 'reason': 'No anonymous toggle in composer.'}

        anon_result = composer.activate_anonymous()
        audit.log_event(
            'anonymous_activation_result',
            success=anon_result.success,
            detail=anon_result.detail,
        )
        if not anon_result.success:
            session.publish_job.state = WorkerResultState.FAILED
            session.publish_job.error_code = 'ANONYMOUS_UI_UNCONFIRMED'
            _safe_save(session.publish_job, update_fields=['state', 'error_code'])
            return {
                'result': 'failed',
                'reason': 'Anonymous mode could not be confirmed as enabled.',
            }

        # Verify anonymous author state
        anon_enabled = composer.is_anonymous_enabled()
        audit.log_event(
            'anonymous_author_verified',
            enabled=anon_enabled,
        )
        if not anon_enabled:
            raise WorkerError('Anonymous author could not be verified.')

        composer.fill_caption(caption)
        audit.log_event('caption_filled')

        # Step: Stage and attach images from R2
        session.publish_job.state = WorkerResultState.ANONYMOUS_ENABLED
        _safe_save(session.publish_job, update_fields=['state'])
        stager = MediaStager(settings)
        staged_images = []
        try:
            if session.image_ids:
                staged_images = _db_call(stager.stage_all,
                    pipeline_id=job.pipeline_id,
                    image_ids=session.image_ids,
                )
                audit.log_event(
                    'images_staged', count=len(staged_images),
                )
                for img in staged_images:
                    composer.attach_image(img.temp_path)

            if not staged_images:
                raise WorkerError('No image was staged for publishing.')
            if not composer.verify_caption(caption) or not composer.is_anonymous_enabled():
                raise WorkerError('Caption or anonymous author changed during media upload.')

            session.publish_job.state = WorkerResultState.CONTENT_READY
            _safe_save(session.publish_job, update_fields=['state'])

            # begin_dispatch atomically marks media started before the click.
            _db_call(begin_dispatch,
                pipeline_id=job.pipeline_id,
                job_id=str(job.job_id),
                claim_token=claim_token,
            )
            dispatch_started = True
            audit.log_event('dispatch_begun')

            session.publish_job.state = WorkerResultState.SUBMITTING
            session.publish_job.submitted_at = timezone.now()
            _safe_save(session.publish_job, update_fields=['state', 'submitted_at'])
            audit.log_transition(
                from_state=WorkerResultState.CONTENT_READY,
                to_state=WorkerResultState.SUBMITTING,
            )

            # Step: CRITICAL — re-check can_publish immediately before Post click
            if not _can_publish(settings, config):
                raise WorkerError('Publishing disabled at pre-submit check.')

            # Step: Submit post — this is the actual Facebook post creation
            composer.submit_post()
            audit.log_event('post_submitted')

            # Briefly monitor for a participation prompt. Never click Post again.
            for _ in range(4):
                prompt = inspect_rules_prompt(page)
                if prompt:
                    outcome = _wait_for_rules_review(session=session, page=page, prompt=prompt, audit=audit)
                    if outcome:
                        return outcome
                    break
                page.wait_for_timeout(1000)
            if inspect_rules_prompt(page):
                raise WorkerError('Participation prompt remains after confirmation.')

            # Recognize an explicit response already on screen without searching
            # the Group or treating a closed composer as proof of publication.
            response_text = (page.locator('body').inner_text() or '').lower()
            if any(text in response_text for text in (
                    'your post is pending approval', 'your post is pending admin approval',
                    'bài viết của bạn đang chờ duyệt', 'bài viết của bạn đang chờ phê duyệt')):
                _db_call(flag_uncertain, pipeline_id=job.pipeline_id,
                         job_id=str(job.job_id), code='PENDING_ADMIN_APPROVAL')
                session.publish_job.state = WorkerResultState.PENDING_APPROVAL
                _safe_save(session.publish_job, update_fields=['state'])
                return {'result': 'pending_approval', 'detail': 'Facebook reports pending approval.'}

            # This records only that Playwright completed the click, not that
            # Facebook accepted or made the post visible.
            _db_call(_record_submit_click, pipeline_id=job.pipeline_id,
                     job_id=str(job.job_id), claim_token=claim_token,
                     worker_job_id=session.publish_job.pk)
            audit.log_event('post_click_recorded', visibility_verified=False)
            return {'result': 'submitted',
                    'detail': 'Post button clicked; Facebook visibility was not checked.'}

        finally:
            if stager:
                stager.cleanup()

    except Exception as exc:
        audit.log_error('PUBLISH_ERROR', type(exc).__name__)
        if dispatch_started:
            _db_call(safe_transition_to_uncertain,
                pipeline_id=job.pipeline_id,
                job_id=str(job.job_id),
                worker_job=session.publish_job,
                claim_token=claim_token,
                error_code='PUBLISH_ERROR',
                audit=audit,
            )
        else:
            session.publish_job.state = WorkerResultState.FAILED
            session.publish_job.error_code = 'PUBLISH_ERROR'
            _safe_save(session.publish_job, update_fields=['state', 'error_code'])
        raise WorkerError(f'Publish failed: {type(exc).__name__}') from exc
    finally:
        if browser_mgr:
            browser_mgr.close_context(session.context)
            browser_mgr.shutdown()
