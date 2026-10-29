"""Step 9.7.10: safe, independent publication readback gateway.

The old Meta Facebook Groups API was discontinued. This module includes NO
Facebook network client and NO endpoint to confirm posting from CTV/HAR.
Only a server-installed, explicitly authorized submission source and a
separately authorized independent readback provider can drive the trusted
confirmation service shipped in Step 9.7.9.

Lock order on writes: Pipeline -> Job -> submission/audit -> Job Engine.
Network calls occur OUTSIDE database transactions.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit, unquote
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.readback_models import PostSubmissionReference, PostReadbackAudit
from modules.publishing.verification_models import TrustedPostVerification
from modules.publishing.services.post_verification import (
    verify_with_authorized_adapter, VisibilityReadback,
)

POST_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}$')
SOURCE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$')
HOSTS = frozenset({'facebook.com', 'www.facebook.com', 'm.facebook.com', 'web.facebook.com'})


class ReadbackError(ValueError):
    pass


class ReadbackConflict(ReadbackError):
    pass


@dataclass(frozen=True)
class IndependentReadback:
    """Independent, live readback of exact submission; NEVER from HAR.

    `job_id` is the orchestration correlation. Anonymous post authorship is
    anchored to the trusted submission ref, NOT to public display name.
    `visibility` may be visible, pending, rejected or inconclusive.
    `permalink` must be a canonical group post/permalink for visible results.
    """
    job_id: str
    pipeline_id: str
    group_id: str
    external_post_id: str
    group_key: str
    visibility: str
    permalink: str
    observed_at: datetime


def _validate_key(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReadbackError('request_key phải là UUID.') from exc


def _require_source(enabled_flag, id_name, source_id):
    expected = getattr(settings, id_name, '')
    if (getattr(settings, enabled_flag, False) is not True
            or not expected or not isinstance(source_id, str)
            or not SOURCE_RE.fullmatch(source_id) or source_id != expected):
        raise ReadbackError('Chưa cấu hình nguồn được cấp phép tương ứng.')


def _clean_post_id(post_id):
    if not isinstance(post_id, str) or not POST_ID_RE.fullmatch(post_id):
        raise ReadbackError('Mã bài viết không hợp lệ.')
    return post_id


@transaction.atomic
def register_trusted_submission(*, pipeline_id, job_id, external_post_id,
                                source_id, submitted_at):
    """Server-only. Call after successful submission via authorized adapter.

    NEVER expose this action via CTV API or public CLI. Submission itself
    is not publication verification; it cannot release Account/Group holds.
    """
    _require_source('TOOLNET_SUBMISSION_CAPTURE_ENABLED',
                    'TOOLNET_SUBMISSION_CAPTURE_SOURCE_ID', source_id)
    post_id = _clean_post_id(external_post_id)
    if not isinstance(submitted_at, datetime) or timezone.is_naive(submitted_at):
        raise ReadbackError('submitted_at phải có múi giờ.')
    now = timezone.now()
    if submitted_at > now + timedelta(seconds=30) or submitted_at < now - timedelta(days=7):
        raise ReadbackError('Thời gian nộp bài không hợp lệ.')
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise ReadbackError('Pipeline không tồn tại.')
    job = PublishingJob.objects.select_for_update().filter(pk=job_id, pipeline_id=pipeline.pk).first()
    if job is None:
        raise ReadbackError('Job không thuộc Pipeline.')
    old = PostSubmissionReference.objects.filter(job=job).first()
    if old:
        if (old.external_post_id != post_id or old.source_id != source_id
                or old.submitted_at != submitted_at):
            raise ReadbackConflict('Job đã gắn mã bài viết khác. Không ghi đè.')
        return {'id': str(old.pk), 'job_id': str(job.pk), 'created': False}
    if job.state not in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN):
        raise ReadbackConflict('Job chưa có thao tác gửi hoặc đã kết thúc.')
    if job.attempt_count < 1:
        raise ReadbackConflict('Job không có PublishingAttempt đã bắt đầu.')
    row = PostSubmissionReference.objects.create(
        pipeline=pipeline, job=job, account_id_snapshot=job.facebook_account_id,
        group_id_snapshot=job.facebook_group_id, external_post_id=post_id,
        source_id=source_id, submitted_at=submitted_at,
    )
    return {'id': str(row.pk), 'job_id': str(job.pk), 'created': True}


def _validate_permalink(value, *, group_key, post_id):
    if not isinstance(value, str) or len(value) > 800:
        return False
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname not in HOSTS
                or parsed.username or parsed.password or parsed.port is not None
                or parsed.query or parsed.fragment):
            return False
    except ValueError:
        return False
    parts = [unquote(part) for part in parsed.path.strip('/').split('/')]
    return (len(parts) == 4 and parts[0] == 'groups'
            and parts[1].casefold() == group_key.casefold()
            and parts[2] in ('posts', 'permalink') and parts[3] == post_id)


def _check_response(row, job, group_key, result, now):
    """Validate all bindings; never trust HTTP 200, names or screenshot alone."""
    if not isinstance(result, IndependentReadback):
        return 'mismatch', 'BAD_READBACK_TYPE'
    if (result.job_id != str(job.pk)
            or result.pipeline_id != str(job.pipeline_id)
            or result.group_id != str(job.facebook_group_id)
            or result.external_post_id != row.external_post_id
            or not isinstance(result.group_key, str)
            or result.group_key.casefold() != group_key.casefold()):
        return 'mismatch', 'IDENTITY_MISMATCH'
    at = result.observed_at
    if (not isinstance(at, datetime) or timezone.is_naive(at)
            or at > now + timedelta(seconds=15)
            or at < now - timedelta(minutes=5)
            or at < row.submitted_at - timedelta(seconds=30)):
        return 'mismatch', 'STALE_READBACK'
    if result.visibility not in ('visible', 'pending', 'rejected', 'inconclusive'):
        return 'mismatch', 'UNKNOWN_VISIBILITY'
    if result.visibility == 'visible':
        if not _validate_permalink(result.permalink, group_key=group_key,
                                   post_id=row.external_post_id):
            return 'mismatch', 'POST_URL_MISMATCH'
        return 'verified', ''
    return result.visibility, ''


def _audit_payload(audit):
    return {
        'id': str(audit.pk), 'outcome': audit.outcome,
        'error_code': audit.error_code or None,
        'source_id': audit.source_id,
        'checked_at': audit.checked_at.isoformat(),
    }


class _FrozenAdapter:
    """Pass ONE validated readback to Step 9.7.9 without a second network call."""
    def __init__(self, source_id, job, at, post_id):
        self.adapter_id = source_id
        self.row = VisibilityReadback(
            visibility='visible', external_post_id=post_id,
            pipeline_id=str(job.pipeline_id), account_id=str(job.facebook_account_id),
            group_id=str(job.facebook_group_id), observed_at=at,
        )

    def readback(self, **_kwargs):
        return self.row


def run_authorized_readback(*, pipeline_id, job_id, adapter, request_key):
    """Explicit server-side trigger. Never called by HTTP or scheduler tick.

    A successful readback can transition DISPATCHING/UNCERTAIN -> PUBLISHED.
    Pending, rejected, inconclusive and mismatch only add audit, NOT Job state.
    """
    if adapter is None:
        raise ReadbackError('Thiếu adapter độc lập.')
    source_id = getattr(adapter, 'adapter_id', None)
    _require_source('TOOLNET_PUBLICATION_VERIFIER_ENABLED',
                    'TOOLNET_PUBLICATION_VERIFIER_ID', source_id)
    request_key = _validate_key(request_key)
    job = PublishingJob.objects.select_related('facebook_group').filter(
        pk=job_id, pipeline_id=pipeline_id,
    ).first()
    if job is None:
        raise ReadbackError('Job không thuộc Pipeline.')
    reference = PostSubmissionReference.objects.filter(
        pipeline_id=pipeline_id, job_id=job.pk,
    ).first()
    if reference is None:
        raise ReadbackConflict('Thiếu mã bài viết từ nguồn gửi tin cậy. Không thể xác minh.')
    old = PostReadbackAudit.objects.filter(job=job, request_key=request_key).first()
    if old is not None:
        if old.source_id != source_id:
            raise ReadbackConflict('request_key đã dùng cho nguồn khác.')
        return _audit_payload(old)
    if job.state not in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN):
        raise ReadbackConflict('Job không còn ở trạng thái cần xác minh.')
    # This call is deliberately outside a DB transaction.
    result = adapter.readback(
        pipeline_id=str(pipeline_id), job_id=str(job_id),
        group_id=str(job.facebook_group_id),
        account_id=str(job.facebook_account_id),
        external_post_id=reference.external_post_id,
    )
    now = timezone.now()
    outcome, error_code = _check_response(
        reference, job, job.facebook_group.group_key, result, now,
    )
    # Serialize rechecks and Job finalization on the Pipeline row.
    with transaction.atomic():
        pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
        if pipeline is None:
            raise ReadbackError('Pipeline không tồn tại.')
        locked = PublishingJob.objects.select_for_update().filter(
            pk=job_id, pipeline_id=pipeline.pk,
        ).first()
        if locked is None:
            raise ReadbackConflict('Job đã thay đổi Pipeline.')
        old = PostReadbackAudit.objects.filter(job=locked, request_key=request_key).first()
        if old is not None:
            if old.source_id != source_id:
                raise ReadbackConflict('request_key đã dùng cho nguồn khác.')
            return _audit_payload(old)
        current_ref = PostSubmissionReference.objects.filter(
            job=locked, pipeline_id=pipeline.pk,
        ).first()
        if (current_ref is None or current_ref.pk != reference.pk
                or locked.facebook_account_id != reference.account_id_snapshot
                or locked.facebook_group_id != reference.group_id_snapshot
                or locked.facebook_group.group_key != job.facebook_group.group_key):
            raise ReadbackConflict('Mã liên kết Job đã thay đổi.')
        if locked.state not in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN):
            raise ReadbackConflict('Job đã có kết quả khác; không ghi đè.')
        if outcome == 'verified':
            if locked.media_allocation_id is None:
                raise ReadbackConflict('Thiếu MediaAllocation, không được công bố Job.')
            # Only after independent readback of EXACT submitted post.
            verify_with_authorized_adapter(
                pipeline_id=pipeline.pk, job_id=locked.pk,
                adapter=_FrozenAdapter(source_id, locked, result.observed_at,
                                       reference.external_post_id),
            )
        audit = PostReadbackAudit.objects.create(
            pipeline=pipeline, job=locked, request_key=request_key,
            source_id=source_id, outcome=outcome,
            error_code=error_code,
            observed_at=(result.observed_at if isinstance(result, IndependentReadback)
                         and isinstance(result.observed_at, datetime)
                         and not timezone.is_naive(result.observed_at) else None),
        )
        return _audit_payload(audit)


def readback_snapshot(*, pipeline_id, job_id, page=1, page_size=20):
    """CTV-safe, read-only status. Never return post ID, submission token, HAR."""
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 50:
        raise ReadbackError('Phân trang không hợp lệ.')
    job = PublishingJob.objects.filter(pk=job_id, pipeline_id=pipeline_id).first()
    if job is None:
        raise ReadbackError('Job không thuộc Pipeline.')
    qs = PostReadbackAudit.objects.filter(
        pipeline_id=pipeline_id, job_id=job.pk,
    ).order_by('-checked_at', '-pk')
    number = qs.count()
    start = (page - 1) * page_size
    if start >= number and page != 1:
        raise ReadbackError('Trang không tồn tại.')
    audits = list(qs[start:start + page_size])
    receipt = TrustedPostVerification.objects.filter(pipeline_id=pipeline_id, job_id=job.pk).first()
    submission = PostSubmissionReference.objects.filter(pipeline_id=pipeline_id, job_id=job.pk).first()
    trusted_verified = bool(job.state == PublishingJob.State.PUBLISHED
                            and job.external_post_id and receipt and submission
                            and job.external_post_id == receipt.external_post_id
                            and job.external_post_id == submission.external_post_id)
    return {
        'pipeline_id': str(pipeline_id), 'job_id': str(job.pk),
        'job_state': job.state,
        'trusted_submission_linked': submission is not None,
        'trusted_publication_verified': trusted_verified,
        'last_readback': _audit_payload(qs.first()) if number else None,
        'checks': [_audit_payload(x) for x in audits],
        'pagination': {'page': page, 'page_size': page_size,
                       'total': number, 'total_pages': max(1, (number + page_size - 1) // page_size),
                       'has_next': start + page_size < number},
        'readback_enabled': bool(
            getattr(settings, 'TOOLNET_PUBLICATION_VERIFIER_ENABLED', False)
            and getattr(settings, 'TOOLNET_PUBLICATION_VERIFIER_ID', '')
        ),
        'no_auto_retry': True,
    }
