"""Publishing Job Engine: internal-only preparation and reconciliation.

IMPORTANT: This module NEVER sends a Facebook request. Only trusted workers
may call these functions. Do not expose claim_token via public APIs.

All mutating entry points acquire locks in this order: Pipeline -> Job ->
MediaAllocation/Album (through media_selection). Keep network I/O outside DB
transactions and never blindly retry after begin_dispatch().
"""

import re
import secrets
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q, F
from django.utils import timezone

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.models import MediaAllocation, PublishingJob, PublishingAttempt
from modules.publishing.services import media_selection
from modules.publishing.services.reconciliation import held_subject_ids
from modules.publishing.services.caption_engine import ready_for_dispatch

KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
EXTERNAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}$")


class JobEngineError(Exception):
    pass


class JobConflict(JobEngineError):
    pass


def _pipeline(pipeline_id):
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise JobEngineError("Pipeline không tồn tại.")
    return pipeline


def _job(pipeline_id, job_id):
    result = (PublishingJob.objects.select_for_update()
              .filter(pk=job_id, pipeline_id=pipeline_id).first())
    if result is None:
        raise JobEngineError("Job không tồn tại trong Pipeline.")
    return result


def _attempt(job):
    attempt = (PublishingAttempt.objects.select_for_update()
               .filter(job_id=job.pk, number=job.attempt_count).first())
    if attempt is None:
        raise JobConflict("Không tìm thấy attempt đang xử lý.")
    return attempt


def _validate_claim(job, token, states):
    if not isinstance(token, str) or not secrets.compare_digest(job.claim_token, token):
        raise JobConflict("Worker token không hợp lệ.")
    if job.state not in states:
        raise JobConflict("Trạng thái Job không hợp lệ.")
    if not job.lease_expires_at or job.lease_expires_at <= timezone.now():
        raise JobConflict("Worker lease đã hết hạn, phải đối soát.")


def _snapshot(job):
    return {
        "id": str(job.pk),
        "pipeline_id": str(job.pipeline_id),
        "request_key": job.request_key,
        "state": job.state,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "scheduled_at": job.scheduled_at.isoformat(),
        "next_run_at": job.next_run_at.isoformat(),
        "facebook_account_id": str(job.facebook_account_id),
        "facebook_group_id": str(job.facebook_group_id),
        "media_allocation_id": str(job.media_allocation_id) if job.media_allocation_id else None,
        "external_post_id": job.external_post_id or None,
        "error_code": job.error_code or None,
    }


@transaction.atomic
def enqueue_job(*, pipeline_id, account_id, group_id, request_key,
                caption="", scheduled_at=None, max_attempts=3):
    """Idempotent creation. Does not publish anything."""
    if not isinstance(request_key, str) or not KEY_RE.fullmatch(request_key):
        raise JobEngineError("request_key không hợp lệ.")
    if not isinstance(caption, str) or len(caption) > 5000:
        raise JobEngineError("Caption không hợp lệ hoặc quá 5000 ký tự.")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
        raise JobEngineError("max_attempts phải từ 1 đến 5.")
    if scheduled_at is not None and (
        not isinstance(scheduled_at, datetime) or timezone.is_naive(scheduled_at)
    ):
        raise JobEngineError("scheduled_at phải là datetime có múi giờ.")
    pipeline = _pipeline(pipeline_id)
    existing = PublishingJob.objects.filter(
        pipeline_id=pipeline.pk, request_key=request_key,
    ).first()
    if existing:
        if (str(existing.facebook_account_id) != str(account_id)
                or str(existing.facebook_group_id) != str(group_id)
                or existing.caption != caption
                or existing.max_attempts != max_attempts
                or (scheduled_at is not None and existing.scheduled_at != scheduled_at)):
            raise JobConflict("request_key đã thuộc Job có nội dung khác.")
        return _snapshot(existing)
    if pipeline.status != Pipeline.Status.ACTIVE:
        raise JobConflict("Pipeline đang bị khóa.")
    account = FacebookAccount.objects.filter(pk=account_id, pipeline_id=pipeline.pk).first()
    group = FacebookGroup.objects.filter(pk=group_id, pipeline_id=pipeline.pk).first()
    if account is None or group is None:
        raise JobEngineError("Facebook Account hoặc Group không thuộc Pipeline.")
    if not group.is_enabled:
        raise JobConflict("Group đang tắt.")
    at = scheduled_at or timezone.now()
    job = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group,
        request_key=request_key, caption=caption, scheduled_at=at,
        next_run_at=at, max_attempts=max_attempts,
    )
    return _snapshot(job)


@transaction.atomic
def claim_due_job(*, pipeline_id, worker_id, lease_seconds=600):
    """One worker claims one due Job; no external publishing here."""
    if not isinstance(worker_id, str) or not WORKER_RE.fullmatch(worker_id):
        raise JobEngineError("worker_id không hợp lệ.")
    if type(lease_seconds) is not int or not 60 <= lease_seconds <= 3600:
        raise JobEngineError("lease_seconds phải từ 60 đến 3600.")
    pipeline = _pipeline(pipeline_id)
    if pipeline.status != Pipeline.Status.ACTIVE:
        return None
    now = timezone.now()
    blocked_accounts, blocked_groups = held_subject_ids(pipeline_id=pipeline.pk)
    job = (PublishingJob.objects.select_for_update(of=('self',))
           .filter(pipeline_id=pipeline.pk, state=PublishingJob.State.QUEUED,
                   facebook_account__connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
                   facebook_group__is_enabled=True,
                   next_run_at__lte=now, attempt_count__lt=5)
           .exclude(facebook_account_id__in=blocked_accounts)
           .exclude(facebook_group_id__in=blocked_groups)
           .exclude(manual_handoff__state='prepared')
           .filter(Q(pipeline__caption_settings__isnull=True) |
                   Q(pipeline__caption_settings__enabled=False) |
                   Q(ai_caption__state='approved',
                     ai_caption__settings_version=F('pipeline__caption_settings__version'),
                     ai_caption__destination_snapshot=F('pipeline__caption_settings__destination'),
                     caption=F('ai_caption__text')))
           .order_by("next_run_at", "scheduled_at", "id").first())
    if job is None:
        return None
    if not ready_for_dispatch(job):
        return None
    if job.attempt_count >= job.max_attempts:
        job.state = PublishingJob.State.FAILED
        job.error_code = "ATTEMPTS_EXHAUSTED"
        job.finalized_at = now
        job.save()
        return None
    if not job.facebook_group.is_enabled:
        job.state = PublishingJob.State.FAILED
        job.error_code = "GROUP_DISABLED"
        job.finalized_at = now
        job.save()
        return None
    job.attempt_count += 1
    job.state = PublishingJob.State.CLAIMED
    job.worker_id = worker_id
    job.claim_token = secrets.token_urlsafe(32)
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.error_code = ""
    job.save()
    PublishingAttempt.objects.create(job=job, number=job.attempt_count)
    return {"job": _snapshot(job), "claim_token": job.claim_token}


@transaction.atomic
def prepare_job_media(*, pipeline_id, job_id, claim_token):
    """Reserve images AND attach allocation to attempt atomically.

    Uses private transaction-aware reserve implementation to avoid creating
    an orphan reservation between preparation and attachment.
    """
    _pipeline(pipeline_id)
    job = _job(pipeline_id, job_id)
    _validate_claim(job, claim_token, {PublishingJob.State.CLAIMED, PublishingJob.State.READY})
    if job.state == PublishingJob.State.READY:
        return _snapshot(job)
    attempt = _attempt(job)
    media_key = f"pubjob-{job.pk.hex}-a{job.attempt_count}"
    allocation = media_selection._reserve_media_tx(
        pipeline_id=job.pipeline_id, request_key=media_key,
        lease_seconds=max(60, min(3600, int((job.lease_expires_at - timezone.now()).total_seconds()))),
    )
    if allocation["state"] != MediaAllocation.State.RESERVED:
        raise JobConflict("Cấp phát ảnh không còn trạng thái giữ chỗ.")
    obj = MediaAllocation.objects.get(pk=allocation["id"], pipeline_id=job.pipeline_id)
    job.media_allocation = obj
    job.state = PublishingJob.State.READY
    job.save()
    attempt.media_allocation = obj
    attempt.state = PublishingAttempt.State.READY
    attempt.save()
    return _snapshot(job)


@transaction.atomic
def heartbeat_job(*, pipeline_id, job_id, claim_token, lease_seconds=600):
    if type(lease_seconds) is not int or not 60 <= lease_seconds <= 3600:
        raise JobEngineError("lease_seconds không hợp lệ.")
    _pipeline(pipeline_id)
    job = _job(pipeline_id, job_id)
    _validate_claim(job, claim_token, {PublishingJob.State.CLAIMED, PublishingJob.State.READY})
    if job.media_allocation_id:
        result, error = media_selection._heartbeat_tx(
            pipeline_id=job.pipeline_id,
            request_key=job.media_allocation.request_key,
            lease_seconds=lease_seconds,
        )
        if error:
            raise JobConflict(error)
    job.lease_expires_at = timezone.now() + timedelta(seconds=lease_seconds)
    job.save()
    return _snapshot(job)


@transaction.atomic
def begin_dispatch(*, pipeline_id, job_id, claim_token):
    """Irreversible boundary: must COMMIT before external network I/O."""
    pipeline = _pipeline(pipeline_id)
    job = _job(pipeline_id, job_id)
    _validate_claim(job, claim_token, {PublishingJob.State.READY})
    if pipeline.status != Pipeline.Status.ACTIVE:
        raise JobConflict("Pipeline đang bị khóa.")
    if not job.facebook_group.is_enabled:
        raise JobConflict("Group đang tắt.")
    if job.facebook_account.connection_status != FacebookAccount.ConnectionStatus.CONNECTED:
        raise JobConflict("Tài khoản Facebook chưa kết nối hoặc đã hết phiên.")
    if not job.media_allocation_id:
        raise JobConflict("Job chưa có ảnh.")
    result, error = media_selection._mark_started_tx(
        pipeline_id=pipeline.pk, request_key=job.media_allocation.request_key,
    )
    if error:
        raise JobConflict(error)
    job.state = PublishingJob.State.DISPATCHING
    job.save()
    attempt = _attempt(job)
    attempt.state = PublishingAttempt.State.DISPATCHING
    attempt.save()
    return _snapshot(job)


@transaction.atomic
def confirm_published(*, pipeline_id, job_id, external_post_id):
    """Trusted adapter ONLY after independently verifying external post ID."""
    if not isinstance(external_post_id, str) or not EXTERNAL_RE.fullmatch(external_post_id):
        raise JobEngineError("external_post_id không hợp lệ.")
    _pipeline(pipeline_id)
    job = _job(pipeline_id, job_id)
    if job.state == PublishingJob.State.PUBLISHED:
        if job.external_post_id != external_post_id:
            raise JobConflict("Job đã xác minh với bài đăng khác.")
        return _snapshot(job)
    if job.state not in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN):
        raise JobConflict("Job chưa được phép bắt đầu đăng.")
    if not job.media_allocation_id:
        raise JobConflict("Job chưa có cấp phát ảnh.")
    media_selection.confirm_consumed(
        pipeline_id=job.pipeline_id,
        request_key=job.media_allocation.request_key,
    )
    job.state = PublishingJob.State.PUBLISHED
    job.external_post_id = external_post_id
    job.finalized_at = timezone.now()
    job.claim_token = ""
    job.worker_id = ""
    job.lease_expires_at = None
    job.save()
    attempt = _attempt(job)
    attempt.state = PublishingAttempt.State.PUBLISHED
    attempt.finalized_at = job.finalized_at
    attempt.save()
    return _snapshot(job)


@transaction.atomic
def flag_uncertain(*, pipeline_id, job_id, code="UNVERIFIED_RESULT"):
    """Quarantine after possible external call. Never automatically retry."""
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9_]{1,80}", code):
        raise JobEngineError("error_code không hợp lệ.")
    _pipeline(pipeline_id)
    job = _job(pipeline_id, job_id)
    if job.state not in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN):
        raise JobConflict("Chỉ đối soát Job đã bắt đầu thử đăng.")
    job.state = PublishingJob.State.UNCERTAIN
    job.error_code = code
    job.claim_token = ""
    job.worker_id = ""
    job.lease_expires_at = None
    job.save()
    attempt = _attempt(job)
    attempt.state = PublishingAttempt.State.UNCERTAIN
    attempt.save()
    return _snapshot(job)


@transaction.atomic
def fail_before_dispatch(*, pipeline_id, job_id, claim_token,
                         error_code="PREFLIGHT_FAILED", retry_delay_seconds=60):
    """Safe preflight-only retry with a NEW media idempotency key per attempt."""
    if not isinstance(error_code, str) or not re.fullmatch(r"[A-Z0-9_]{1,80}", error_code):
        raise JobEngineError("error_code không hợp lệ.")
    if type(retry_delay_seconds) is not int or not 0 <= retry_delay_seconds <= 3600:
        raise JobEngineError("retry_delay_seconds phải từ 0 đến 3600.")
    _pipeline(pipeline_id)
    job = _job(pipeline_id, job_id)
    _validate_claim(job, claim_token, {PublishingJob.State.CLAIMED, PublishingJob.State.READY})
    if job.media_allocation_id:
        result, error = media_selection._release_tx(
            pipeline_id=job.pipeline_id,
            request_key=job.media_allocation.request_key,
        )
        if error:
            raise JobConflict(error)
    attempt = _attempt(job)
    attempt.state = PublishingAttempt.State.RELEASED
    attempt.finalized_at = timezone.now()
    attempt.save()
    job.media_allocation = None
    job.claim_token = ""
    job.worker_id = ""
    job.lease_expires_at = None
    job.error_code = error_code
    if job.attempt_count < job.max_attempts:
        job.state = PublishingJob.State.QUEUED
        job.next_run_at = timezone.now() + timedelta(seconds=retry_delay_seconds)
    else:
        job.state = PublishingJob.State.FAILED
        job.finalized_at = timezone.now()
    job.save()
    return _snapshot(job)


@transaction.atomic
def cancel_queued_job(*, pipeline_id, job_id):
    """Only queued jobs can be cancelled without checking external state."""
    _pipeline(pipeline_id)
    job = _job(pipeline_id, job_id)
    if job.state != PublishingJob.State.QUEUED:
        raise JobConflict("Chỉ có thể hủy Job đang chờ.")
    if hasattr(job, "manual_handoff"):
        raise JobConflict("Job đã bàn giao thủ công; hủy qua quy trình handoff.")
    job.state = PublishingJob.State.CANCELLED
    job.finalized_at = timezone.now()
    job.save()
    return _snapshot(job)


@transaction.atomic
def sweep_expired_jobs(*, pipeline_id):
    """Fail closed. Expired claims are quarantined, NEVER queued for retry."""
    _pipeline(pipeline_id)
    now = timezone.now()
    jobs = list(PublishingJob.objects.select_for_update().filter(
        pipeline_id=pipeline_id,
        state__in=(PublishingJob.State.CLAIMED, PublishingJob.State.READY,
                   PublishingJob.State.DISPATCHING),
        lease_expires_at__lte=now,
    ).order_by("pk"))
    for job in jobs:
        job.state = PublishingJob.State.UNCERTAIN
        job.error_code = "WORKER_LEASE_EXPIRED"
        job.claim_token = ""
        job.worker_id = ""
        job.lease_expires_at = None
        job.save()
        attempt = _attempt(job)
        attempt.state = PublishingAttempt.State.UNCERTAIN
        attempt.save()
    media_selection._expire_reservations(pipeline_id, now)
    return len(jobs)
