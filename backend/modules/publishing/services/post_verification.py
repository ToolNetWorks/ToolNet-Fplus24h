"""Post-verification ledger plus dormant authorized-readback adapter boundary.

A SANITIZED HAR/HTTP 200/story ID/pending_post_info is observational evidence.
It NEVER changes PublishingJob state or releases a held Account/Group.

Only `verify_with_authorized_adapter` can confirm, and only if deployment opts
in to a real independent *authorized readback* adapter implemented on server.
This project does not ship such an adapter or any private Facebook API caller.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.verification_models import (
    PostVerificationObservation, TrustedPostVerification,
)
from modules.publishing.services.job_engine import confirm_published, JobConflict


class VerificationError(ValueError):
    pass


class VerificationConflict(VerificationError):
    pass


SECRET_MARKER = re.compile(
    r'(?i)(?:\b(?:cookie|set-cookie|authorization|fb_dtsg|jazoest|access_token|'
    r'csrf_token|claim_token|secret_key|sessionid|xs|datr)\s*[:=]|'
    r'\bbearer\s+\S+|\bEA[A-Za-z0-9]{30,})'
)
POST_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}$')


def _safe_facebook_url(value):
    if not value:
        return ''
    if not isinstance(value, str) or len(value) > 800:
        raise VerificationError('URL bằng chứng không hợp lệ.')
    try:
        parsed = urlsplit(value.strip())
        bad_port = parsed.port is not None
    except ValueError as exc:
        raise VerificationError('URL bằng chứng không hợp lệ.') from exc
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or host not in ('facebook.com', 'www.facebook.com', 'm.facebook.com')
            or parsed.username or parsed.password or bad_port or parsed.query or parsed.fragment
            or not parsed.path.startswith('/')):
        raise VerificationError('Chỉ nhận HTTPS facebook.com không có query, fragment hoặc tài khoản.')
    return value.strip()


def _payload(row):
    return {
        'id': str(row.pk), 'job_id': str(row.job_id),
        'source': row.source, 'outcome': row.outcome,
        'note': row.note, 'evidence_url': row.evidence_url or None,
        'actor': row.actor.username, 'recorded_at': row.recorded_at.isoformat(),
    }


def job_verification_snapshot(*, pipeline_id, job_id, page=1, page_size=20):
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 50:
        raise VerificationError('Phân trang không hợp lệ.')
    job = PublishingJob.objects.filter(pk=job_id, pipeline_id=pipeline_id).first()
    if job is None:
        raise VerificationError('Không tìm thấy Job trong Pipeline.')
    qs = PostVerificationObservation.objects.filter(
        pipeline_id=pipeline_id, job_id=job.pk,
    ).select_related('actor').order_by('-recorded_at', '-pk')
    paged = Paginator(qs, page_size)
    page_obj = paged.get_page(page)
    if page_obj.number != page:
        raise VerificationError('Trang không tồn tại.')
    receipt = TrustedPostVerification.objects.filter(pipeline_id=pipeline_id, job_id=job.pk).first()
    verified = bool(job.state == PublishingJob.State.PUBLISHED and job.external_post_id)
    return {
        'pipeline_id': str(pipeline_id), 'job_id': str(job.pk), 'job_state': job.state,
        'verified_published': verified,
        'verified_post_id': job.external_post_id if verified else None,
        'trusted_receipt_recorded': receipt is not None,
        'most_recent_observation': qs.values_list('outcome', flat=True).first(),
        'observations': [_payload(row) for row in page_obj.object_list],
        'pagination': {
            'page': page_obj.number, 'page_size': page_size,
            'total': paged.count, 'total_pages': paged.num_pages,
            'has_next': page_obj.has_next(), 'has_previous': page_obj.has_previous(),
        },
        'manual_observations_are_proof': False,
        'facebook_readback_configured': bool(
            getattr(settings, 'TOOLNET_PUBLICATION_VERIFIER_ENABLED', False)
            and getattr(settings, 'TOOLNET_PUBLICATION_VERIFIER_ID', '')
        ),
    }


@transaction.atomic
def record_observation(*, pipeline_id, job_id, actor, idempotency_key, source, outcome,
                       note, evidence_url=''):
    """Record redacted metadata only; never set job.state or touch media."""
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise VerificationError('Pipeline không tồn tại.')
    if not (actor.is_active and ((actor.is_staff and actor.is_superuser)
                                 or pipeline.ctv_id == actor.pk)):
        raise VerificationError('Người ghi không có quyền trên Pipeline.')
    job = PublishingJob.objects.select_for_update().filter(pk=job_id, pipeline_id=pipeline.pk).first()
    if job is None:
        raise VerificationError('Job không thuộc Pipeline.')
    if source not in PostVerificationObservation.Source.values:
        raise VerificationError('Nguồn quan sát không hợp lệ.')
    if outcome not in PostVerificationObservation.Outcome.values:
        raise VerificationError('Trạng thái quan sát không hợp lệ.')
    if type(note) is not str or not 10 <= len(note.strip()) <= 1000 or SECRET_MARKER.search(note):
        raise VerificationError('Ghi chú 10–1000 ký tự và không chứa cookie/token/secret.')
    safe_url = _safe_facebook_url(evidence_url)
    try:
        key = uuid.UUID(str(idempotency_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise VerificationError('idempotency_key UUID không hợp lệ.') from exc
    cleaned = note.strip()
    old = PostVerificationObservation.objects.filter(job=job, idempotency_key=key).first()
    if old:
        if (old.source, old.outcome, old.note, old.evidence_url, old.actor_id) != (
                source, outcome, cleaned, safe_url, actor.pk):
            raise VerificationConflict('idempotency_key đã được sử dụng cho dữ liệu khác.')
        return _payload(old), False
    if job.state not in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN,
                         PublishingJob.State.PUBLISHED, PublishingJob.State.FAILED):
        raise VerificationConflict('Chưa có thử đăng; không được gán trạng thái quan sát.')
    row = PostVerificationObservation.objects.create(
        pipeline=pipeline, job=job, actor=actor, idempotency_key=key,
        source=source, outcome=outcome, note=cleaned, evidence_url=safe_url,
    )
    return _payload(row), True


@dataclass(frozen=True)
class VisibilityReadback:
    """Response from an explicitly configured AUTHORIZED server-side readback adapter.

    This is not parseable from HAR/GraphQL submit replies or manual text.
    """
    visibility: str
    external_post_id: str
    pipeline_id: str
    account_id: str
    group_id: str
    observed_at: object


def verify_with_authorized_adapter(*, pipeline_id, job_id, adapter):
    """Dormant integration point; NEVER exposed through the CTV API/CLI.

    A future adapter must independently read back live Group visibility via a
    permitted mechanism, bound to the exact Group/Account and post. The adapter
    may use network I/O here, deliberately OUTSIDE all DB transactions.
    """
    enabled = getattr(settings, 'TOOLNET_PUBLICATION_VERIFIER_ENABLED', False)
    expected = getattr(settings, 'TOOLNET_PUBLICATION_VERIFIER_ID', '')
    if not enabled or not expected or not adapter or getattr(adapter, 'adapter_id', None) != expected:
        raise VerificationError('Chưa cấu hình bộ xác minh độc lập được cấp phép.')
    snapshot = PublishingJob.objects.filter(pk=job_id, pipeline_id=pipeline_id).values(
        'id', 'pipeline_id', 'facebook_account_id', 'facebook_group_id', 'state',
    ).first()
    if not snapshot:
        raise VerificationError('Job không thuộc Pipeline.')
    if snapshot['state'] not in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN):
        raise VerificationConflict('Chỉ xác minh Job đã bắt đầu thử đăng.')

    # Authoritative readback belongs in a separate, permitted integration.
    result = adapter.readback(
        pipeline_id=str(pipeline_id), job_id=str(job_id),
        account_id=str(snapshot['facebook_account_id']),
        group_id=str(snapshot['facebook_group_id']),
    )
    if not isinstance(result, VisibilityReadback):
        raise VerificationError('Bộ xác minh trả về dữ liệu không hợp lệ.')
    if (result.visibility != 'visible' or
            result.pipeline_id != str(pipeline_id) or
            result.account_id != str(snapshot['facebook_account_id']) or
            result.group_id != str(snapshot['facebook_group_id']) or
            not isinstance(result.external_post_id, str) or
            not POST_ID.fullmatch(result.external_post_id)):
        raise VerificationConflict('Chưa có bằng chứng xuất bản khớp Account/Group/Job.')
    at = result.observed_at
    now = timezone.now()
    if (not hasattr(at, 'utcoffset') or timezone.is_naive(at)
            or not (now - timedelta(minutes=5) <= at <= now + timedelta(seconds=10))):
        raise VerificationConflict('Kết quả xác minh không có thời điểm hợp lệ/gần đây.')
    return _save_trusted_receipt(
        pipeline_id=pipeline_id, job_id=job_id, snapshot=snapshot,
        result=result, verifier_id=expected,
    )


@transaction.atomic
def _save_trusted_receipt(*, pipeline_id, job_id, snapshot, result, verifier_id):
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if not pipeline:
        raise VerificationError('Pipeline không tồn tại.')
    job = PublishingJob.objects.select_for_update().filter(pk=job_id, pipeline_id=pipeline_id).first()
    if not job or (job.facebook_account_id != snapshot['facebook_account_id']
                   or job.facebook_group_id != snapshot['facebook_group_id']):
        raise VerificationConflict('Job thay đổi trong thời gian xác minh.')
    existing = TrustedPostVerification.objects.filter(job=job).first()
    if existing:
        if existing.external_post_id != result.external_post_id or existing.verifier_id != verifier_id:
            raise VerificationConflict('Job đã được xác minh bằng bằng chứng khác.')
        return {'job_id': str(job.pk), 'state': job.state, 'external_post_id': existing.external_post_id}
    if job.state not in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN):
        raise VerificationConflict('Job không còn ở trạng thái cho phép xác minh.')
    if not job.media_allocation_id:
        raise VerificationConflict('Job không có MediaAllocation để đối soát.')
    if TrustedPostVerification.objects.filter(pipeline_id=pipeline_id,
             external_post_id=result.external_post_id).exists():
        raise VerificationConflict('Mã bài đăng đã được dùng cho Job khác.')
    try:
        updated = confirm_published(
            pipeline_id=pipeline_id, job_id=job_id,
            external_post_id=result.external_post_id,
        )
    except JobConflict as exc:
        raise VerificationConflict(str(exc)) from exc
    TrustedPostVerification.objects.create(
        pipeline=pipeline, job=job, external_post_id=result.external_post_id,
        verifier_id=verifier_id, observed_at=result.observed_at,
    )
    return {'job_id': str(job.pk), 'state': updated['state'],
            'external_post_id': result.external_post_id}
