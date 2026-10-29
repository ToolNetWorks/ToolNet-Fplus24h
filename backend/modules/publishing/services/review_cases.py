"""Auditable, pipeline-scoped HUMAN review case workflow.

No Facebook calls, no client-side publication confirmation, no job-state
mutations, no release of MediaAllocation and no retries. Safety holds remain
computed from the underlying PublishingJob state, not from case status.
"""
from urllib.parse import urlsplit

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.review_models import PublishingReviewCase, PublishingReviewEvent


class CaseError(ValueError):
    pass


class CaseConflict(CaseError):
    pass


ALLOWED_OPEN_STATES = (
    PublishingJob.State.FAILED, PublishingJob.State.UNCERTAIN,
    PublishingJob.State.DISPATCHING, PublishingJob.State.PUBLISHED,
    PublishingJob.State.CLAIMED, PublishingJob.State.READY,
)
HOLD_STATES = (
    PublishingJob.State.CLAIMED, PublishingJob.State.READY,
    PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN,
)


def _is_held(job):
    return job.state in HOLD_STATES or (job.state == PublishingJob.State.PUBLISHED and not job.external_post_id)


def _is_terminal_verified(job):
    if job.state == PublishingJob.State.PUBLISHED:
        return bool(job.external_post_id)
    return job.state in (PublishingJob.State.FAILED, PublishingJob.State.CANCELLED)


def _reason_to_open(job, now):
    if job.state == PublishingJob.State.PUBLISHED:
        return not bool(job.external_post_id)
    if job.state in (PublishingJob.State.FAILED, PublishingJob.State.DISPATCHING,
                     PublishingJob.State.UNCERTAIN):
        return True
    if job.state in (PublishingJob.State.CLAIMED, PublishingJob.State.READY):
        return bool(job.lease_expires_at and job.lease_expires_at <= now)
    return False


def _serialize(case, *, include_events=False):
    job = case.job
    result = {
        'id': str(case.pk),
        'pipeline_id': str(case.pipeline_id),
        'job_id': str(case.job_id),
        'job_state': job.state,
        'job_error_code': job.error_code or None,
        'has_verified_post_id': bool(job.state == PublishingJob.State.PUBLISHED and job.external_post_id),
        'held': _is_held(job),
        'can_close': _is_terminal_verified(job),
        'account': {'id': str(job.facebook_account_id), 'label': job.facebook_account.label},
        'group': {'id': str(job.facebook_group_id), 'name': job.facebook_group.name},
        'status': case.status,
        'version': case.version,
        'assigned_to': (case.assigned_to.username if case.assigned_to_id else None),
        'created_at': case.created_at.isoformat(),
        'updated_at': case.updated_at.isoformat(),
        'closed_at': case.closed_at.isoformat() if case.closed_at else None,
    }
    if include_events:
        result['events'] = [
            {
                'id': str(event.pk), 'kind': event.kind,
                'actor': event.actor.username,
                'note': event.note, 'evidence_url': event.evidence_url or None,
                'job_state_snapshot': event.job_state_snapshot,
                'created_at': event.created_at.isoformat(),
            }
            for event in case.events.select_related('actor').order_by('created_at', 'pk')[:500]
        ]
        result['event_count'] = case.events.count()
        result['events_truncated'] = result['event_count'] > 500
    return result


def _base_cases(pipeline_id):
    return PublishingReviewCase.objects.filter(pipeline_id=pipeline_id).select_related(
        'job', 'job__facebook_account', 'job__facebook_group', 'assigned_to'
    )


def list_cases(*, pipeline_id, page=1, page_size=20, status=None, job_id=None):
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 50:
        raise CaseError('Phân trang không hợp lệ.')
    if status and status not in PublishingReviewCase.Status.values:
        raise CaseError('Trạng thái hồ sơ không hợp lệ.')
    qs = _base_cases(pipeline_id)
    if status:
        qs = qs.filter(status=status)
    if job_id:
        qs = qs.filter(job_id=job_id)
    paginator = Paginator(qs.order_by('-updated_at', '-pk'), page_size)
    page_obj = paginator.get_page(page)
    if page_obj.number != page:
        raise CaseError('Trang không tồn tại.')
    return {
        'pipeline_id': str(pipeline_id),
        'data': [_serialize(row) for row in page_obj.object_list],
        'pagination': {
            'page': page_obj.number, 'page_size': page_size,
            'total': paginator.count, 'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(), 'has_previous': page_obj.has_previous(),
        },
    }


def get_case(*, pipeline_id, case_id):
    case = _base_cases(pipeline_id).filter(pk=case_id).first()
    if case is None:
        raise CaseError('Không tìm thấy hồ sơ trong Pipeline.')
    return _serialize(case, include_events=True)


def _make_event(case, actor, kind, job, note='', evidence_url=''):
    return PublishingReviewEvent.objects.create(
        case=case, actor=actor, kind=kind,
        note=note, evidence_url=evidence_url,
        job_state_snapshot=job.state,
    )


@transaction.atomic
def open_case(*, pipeline_id, job_id, actor):
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise CaseError('Pipeline không tồn tại.')
    job = PublishingJob.objects.select_for_update().filter(pk=job_id, pipeline_id=pipeline.pk).first()
    if job is None:
        raise CaseError('Job không thuộc Pipeline.')
    case = _base_cases(pipeline.pk).filter(job_id=job.pk).first()
    if case:
        return _serialize(case, include_events=True), False
    if not _reason_to_open(job, timezone.now()):
        raise CaseConflict('Job chưa có dấu hiệu cần mở hồ sơ đối soát.')
    case = PublishingReviewCase.objects.create(pipeline=pipeline, job=job)
    _make_event(case, actor, PublishingReviewEvent.Kind.OPENED, job,
                'Tạo hồ sơ để đối soát; không thay đổi trạng thái Job.')
    return _serialize(_base_cases(pipeline.pk).get(pk=case.pk), include_events=True), True


def _verified_evidence_url(raw):
    if not raw:
        return ''
    if not isinstance(raw, str) or len(raw) > 1000:
        raise CaseError('URL bằng chứng không hợp lệ.')
    try:
        parsed = urlsplit(raw.strip())
    except ValueError as exc:
        raise CaseError('URL bằng chứng không hợp lệ.') from exc
    try:
        invalid = parsed.scheme != 'https' or bool(parsed.username) or bool(parsed.password) or parsed.port is not None
    except ValueError as exc:
        raise CaseError('URL bằng chứng không hợp lệ.') from exc
    if invalid:
        raise CaseError('Chỉ chấp nhận URL HTTPS không có thông tin đăng nhập.')
    host = (parsed.hostname or '').lower()
    if host not in ('facebook.com', 'www.facebook.com', 'm.facebook.com'):
        raise CaseError('Liên kết bằng chứng phải thuộc facebook.com; ảnh chụp ghi qua mô tả.')
    if len(raw) > 1000:
        raise CaseError('URL quá dài.')
    return raw.strip()


@transaction.atomic
def take_action(*, pipeline_id, case_id, actor, action, expected_version,
                note='', evidence_url=''):
    if type(expected_version) is not int or expected_version < 1:
        raise CaseError('expected_version không hợp lệ.')
    if action not in ('assign_me', 'unassign', 'add_evidence', 'request_verification', 'close'):
        raise CaseError('Thao tác không hợp lệ.')
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise CaseError('Pipeline không tồn tại.')
    meta = PublishingReviewCase.objects.filter(pk=case_id, pipeline_id=pipeline.pk).values('job_id').first()
    if meta is None:
        raise CaseError('Không tìm thấy hồ sơ trong Pipeline.')
    job = PublishingJob.objects.select_for_update().filter(pk=meta['job_id'], pipeline_id=pipeline.pk).first()
    if job is None:
        raise CaseError('Job không thuộc Pipeline.')
    case = PublishingReviewCase.objects.select_for_update().get(pk=case_id, pipeline_id=pipeline.pk)
    if case.version != expected_version:
        raise CaseConflict('Hồ sơ đã thay đổi. Tải lại để tránh ghi đè.')
    if case.status == PublishingReviewCase.Status.CLOSED:
        raise CaseConflict('Hồ sơ đã đóng, không thể thêm sự kiện.')
    note = (note or '').strip()
    if len(note) > 2000:
        raise CaseError('Ghi chú tối đa 2.000 ký tự.')
    evidence_url = _verified_evidence_url(evidence_url)
    kind = None
    if action == 'assign_me':
        if case.assigned_to_id not in (None, actor.pk):
            raise CaseConflict('Hồ sơ đang được người khác phụ trách.')
        if case.assigned_to_id == actor.pk:
            raise CaseConflict('Bạn đã phụ trách hồ sơ này.')
        if pipeline.ctv_id != actor.pk:
            raise CaseConflict('Chỉ CTV của Pipeline được nhận hồ sơ.')
        case.assigned_to = actor
        case.status = PublishingReviewCase.Status.IN_REVIEW
        kind = PublishingReviewEvent.Kind.ASSIGNED
    else:
        if case.assigned_to_id != actor.pk and not (actor.is_staff and actor.is_superuser):
            raise CaseConflict('Chỉ người được giao phụ trách được thực hiện thao tác này.')
        if action == 'unassign':
            case.assigned_to = None
            case.status = PublishingReviewCase.Status.OPEN
            kind = PublishingReviewEvent.Kind.UNASSIGNED
        elif action == 'add_evidence':
            if len(note) < 10:
                raise CaseError('Bằng chứng phải có ghi chú tối thiểu 10 ký tự.')
            kind = PublishingReviewEvent.Kind.EVIDENCE
        elif action == 'request_verification':
            if not case.events.filter(kind=PublishingReviewEvent.Kind.EVIDENCE).exists():
                raise CaseConflict('Cần ghi bằng chứng trước khi yêu cầu xác minh.')
            case.status = PublishingReviewCase.Status.AWAITING
            kind = PublishingReviewEvent.Kind.ESCALATED
        elif action == 'close':
            if not _is_terminal_verified(job):
                raise CaseConflict('Job chưa kết thúc hợp lệ; không thể gỡ giữ bằng hồ sơ.')
            if not case.events.filter(kind=PublishingReviewEvent.Kind.EVIDENCE).exists():
                raise CaseConflict('Cần ghi bằng chứng trước khi đóng hồ sơ.')
            case.status = PublishingReviewCase.Status.CLOSED
            case.closed_at = timezone.now()
            kind = PublishingReviewEvent.Kind.CLOSED
    case.version += 1
    case.save()
    _make_event(case, actor, kind, job, note=note, evidence_url=evidence_url)
    return _serialize(_base_cases(pipeline.pk).get(pk=case.pk), include_events=True)
