"""Human-operated content preparation for Facebook Groups.

A user must intentionally open their own Facebook browser, choose the correct
account, and submit in Facebook's own composer. Nothing sends Facebook requests.
States are independent from verified publication; all actions are tenant scoped.

Lock order: Pipeline -> Job -> MediaAllocation -> handoff. Never do I/O here.
"""
from django.db import transaction
from django.utils import timezone
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.publishing.models import (
    PublishingJob, PublishingAttempt, MediaAllocation,
)
from modules.publishing.scheduler_models import AccountGroupEligibility
from modules.publishing.manual_handoff_models import (
    ManualPublishingHandoff as Handoff, ManualPublishingEvent as Event,
)
from modules.publishing.services import media_selection
from modules.publishing.services.post_verification import SECRET_MARKER
from modules.publishing.services.reconciliation import held_subject_ids
from modules.publishing.services.caption_engine import ready_for_dispatch


class HandoffError(ValueError):
    pass


class HandoffConflict(HandoffError):
    pass


REPORT_STATES = (
    Handoff.State.SUBMITTED, Handoff.State.PENDING,
    Handoff.State.REJECTED, Handoff.State.INCONCLUSIVE,
)


def _get_job(pipeline_id, job_id, *, lock=False):
    query = PublishingJob.objects.select_related('facebook_group', 'facebook_account').filter(
        pk=job_id, pipeline_id=pipeline_id,
    )
    job = (query.select_for_update() if lock else query).first()
    if job is None:
        raise HandoffError('Job không tồn tại trong Pipeline này.')
    return job


def _require_actor(pipeline, actor):
    if not actor or not actor.is_active or not (
        (actor.is_staff and actor.is_superuser) or pipeline.ctv_id == actor.pk
    ):
        raise HandoffError('Không được thao tác ngoài Pipeline được cấp.')


def _media(handoff):
    job = handoff.job
    if not job.media_allocation_id:
        return []
    rows = job.media_allocation.items.select_related('image').order_by('position')[:10]
    return [
        {
            'album_id': str(item.album_uuid), 'image_id': str(item.image_uuid),
            'position': item.position,
            'available': bool(item.image and item.image.upload_status == 'ready'),
            # The client constructs the existing same-origin protected image URL.
        }
        for item in rows
    ]


def _payload(row, *, include_events=True):
    job = row.job
    result = {
        'id': str(row.pk), 'job_id': str(job.pk),
        'pipeline_id': str(row.pipeline_id), 'state': row.state,
        'version': row.version, 'account_label': job.facebook_account.label,
        'group_name': job.facebook_group.name,
        'group_url': job.facebook_group.group_url,
        'caption': job.caption,
        'job_state': job.state,
        'media': _media(row), 'note': row.note,
        'prepared_at': row.prepared_at.isoformat(),
        'opened_at': row.opened_at.isoformat() if row.opened_at else None,
        'publication_verified': False,
        'automatic_facebook_posting': False,
    }
    if include_events:
        qs = row.events.order_by('-recorded_at', '-pk')
        events = list(qs[:51])
        result['events'] = [
            {'id': str(event.pk), 'kind': event.kind, 'outcome': event.outcome,
             'note': event.note, 'recorded_at': event.recorded_at.isoformat()}
            for event in events[:50]
        ]
        result['events_truncated'] = len(events) > 50
    return result


def get_handoff(*, pipeline_id, job_id):
    job = _get_job(pipeline_id, job_id)
    row = Handoff.objects.select_related('job__facebook_account', 'job__facebook_group',
                                         'job__media_allocation').filter(job=job).first()
    return {
        'handoff': _payload(row) if row else None,
        'can_prepare': bool(not row and job.state == PublishingJob.State.QUEUED
                            and job.attempt_count == 0 and job.next_run_at <= timezone.now()
                            and ready_for_dispatch(job)),
        'job_state': job.state,
        'facebook_groups_api_supported': False,
    }


@transaction.atomic
def prepare_handoff(*, pipeline_id, job_id, actor):
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise HandoffError('Pipeline không tồn tại.')
    _require_actor(pipeline, actor)
    job = _get_job(pipeline.pk, job_id, lock=True)
    old = Handoff.objects.filter(job=job).first()
    if old:
        return _payload(old)
    if pipeline.status != Pipeline.Status.ACTIVE:
        raise HandoffConflict('Pipeline đang bị khóa.')
    if not ready_for_dispatch(job):
        raise HandoffConflict('Caption AI chưa duyệt hoặc trang đích không hợp lệ.')
    if (job.state != PublishingJob.State.QUEUED or job.attempt_count != 0
            or job.media_allocation_id or job.next_run_at > timezone.now()):
        raise HandoffConflict('Job không ở trạng thái chờ đến hạn để bàn giao thủ công.')
    if (job.facebook_account.connection_status != FacebookAccount.ConnectionStatus.CONNECTED
            or not job.facebook_group.is_enabled):
        raise HandoffConflict('Account/Group không sẵn sàng; cần kiểm tra thủ công.')
    # No simulated group permissions. Require a recent, evidenced individual check.
    eligible = AccountGroupEligibility.objects.filter(
        pipeline=pipeline, account_id=job.facebook_account_id,
        group_id=job.facebook_group_id,
        state=AccountGroupEligibility.State.VERIFIED,
        can_post_anonymous=True, verified_at__lte=timezone.now(),
        expires_at__gt=timezone.now(),
    ).exclude(evidence_note='').exists()
    if not eligible:
        raise HandoffConflict('Chưa xác minh quyền đăng ẩn danh của Account tại Group.')
    accounts, groups = held_subject_ids(pipeline_id=pipeline.pk)
    if job.facebook_account_id in accounts or job.facebook_group_id in groups:
        raise HandoffConflict('Account/Group đang có thao tác chưa đối soát.')
    # Use the existing media reservation engine (exact policy and no-repeat rules).
    try:
        reservation = media_selection._reserve_media_tx(
            pipeline_id=pipeline.pk,
            request_key=f'manual-{job.pk.hex}', lease_seconds=3600,
        )
    except media_selection.MediaSelectionError as exc:
        raise HandoffConflict(str(exc)) from exc
    allocation = MediaAllocation.objects.get(pk=reservation['id'], pipeline=pipeline)
    if allocation.state != MediaAllocation.State.RESERVED:
        raise HandoffConflict('Không thể sử dụng ảnh chưa được giữ chỗ an toàn.')
    job.media_allocation = allocation
    job.save(update_fields=['media_allocation', 'updated_at'])
    row = Handoff.objects.create(pipeline=pipeline, job=job, actor=actor)
    Event.objects.create(handoff=row, actor=actor, kind=Event.Kind.PREPARED)
    return _payload(row)


@transaction.atomic
def mutate_handoff(*, pipeline_id, job_id, actor, action, expected_version, outcome='', note=''):
    if type(expected_version) is not int or expected_version < 1:
        raise HandoffError('expected_version không hợp lệ.')
    if action not in ('open', 'report', 'abandon'):
        raise HandoffError('Hành động không hợp lệ.')
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise HandoffError('Pipeline không tồn tại.')
    _require_actor(pipeline, actor)
    job = _get_job(pipeline.pk, job_id, lock=True)
    row = Handoff.objects.select_for_update().filter(job=job).first()
    if row is None:
        raise HandoffError('Chưa chuẩn bị bàn giao.')
    if row.version != expected_version:
        raise HandoffConflict('Handoff đã được cập nhật. Tải lại trước khi tiếp tục.')
    if action == 'open':
        if row.state != Handoff.State.PREPARED or job.state != PublishingJob.State.QUEUED:
            raise HandoffConflict('Chỉ được mở Facebook một lần sau khi đã chuẩn bị.')
        if not job.media_allocation_id:
            raise HandoffConflict('Thiếu ảnh đã cấp phát.')
        # This boundary is BEFORE user can submit through their own browser.
        try:
            _, error = media_selection._mark_started_tx(
                pipeline_id=pipeline.pk,
                request_key=job.media_allocation.request_key,
            )
        except media_selection.MediaSelectionError as exc:
            raise HandoffConflict(str(exc)) from exc
        if error:
            raise HandoffConflict(error)
        job.attempt_count = 1
        job.state = PublishingJob.State.UNCERTAIN
        job.error_code = 'MANUAL_HANDOFF_UNVERIFIED'
        job.claim_token = ''
        job.worker_id = ''
        job.lease_expires_at = None
        job.save()
        PublishingAttempt.objects.create(
            job=job, number=1, state=PublishingAttempt.State.UNCERTAIN,
            media_allocation=job.media_allocation,
        )
        row.state = Handoff.State.OPENED
        row.opened_at = timezone.now()
        kind = Event.Kind.OPENED
    elif action == 'report':
        if row.state not in (Handoff.State.OPENED, *REPORT_STATES):
            raise HandoffConflict('Chưa mở trình đăng bài Facebook.')
        if outcome not in REPORT_STATES:
            raise HandoffError('Chỉ nhận trạng thái quan sát, không được tự xác nhận published.')
        if type(note) is not str or len(note.strip()) > 500 or SECRET_MARKER.search(note):
            raise HandoffError('Ghi chú không hợp lệ hoặc chứa token/cookie.')
        if job.state != PublishingJob.State.UNCERTAIN:
            raise HandoffConflict('Job đã đổi trạng thái; không được ghi đè.')
        row.state = outcome
        row.note = note.strip()
        kind = Event.Kind.REPORTED
    else:
        if row.state != Handoff.State.PREPARED or job.state != PublishingJob.State.QUEUED:
            raise HandoffConflict('Không được tự hủy khi đã mở Facebook hoặc có thể đã gửi bài.')
        try:
            _, error = media_selection._release_tx(
                pipeline_id=pipeline.pk,
                request_key=job.media_allocation.request_key,
            )
        except media_selection.MediaSelectionError as exc:
            raise HandoffConflict(str(exc)) from exc
        if error:
            raise HandoffConflict(error)
        job.state = PublishingJob.State.CANCELLED
        job.finalized_at = timezone.now()
        job.save()
        row.state = Handoff.State.ABANDONED
        kind = Event.Kind.ABANDONED
    row.version += 1
    row.save()
    Event.objects.create(handoff=row, actor=actor, kind=kind,
                         outcome=outcome if action == 'report' else '',
                         note=note.strip() if action == 'report' else '')
    return _payload(row)
