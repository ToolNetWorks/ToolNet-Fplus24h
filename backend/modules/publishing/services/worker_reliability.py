"""Read-only worker lease monitoring + explicitly requested fail-closed quarantine.

The scheduler/worker remain incapable of publishing to Facebook. Quarantine
NEVER retries, releases media, consumes media, or marks a Job as published.
Locks: Pipeline -> Jobs (ordered) -> Attempts / Media. No remote network I/O.
"""
from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob, PublishingAttempt, MediaAllocation
from modules.publishing.worker_models import WorkerLeaseEvent
from modules.publishing.services.reconciliation import held_subject_ids


IN_FLIGHT = (
    PublishingJob.State.CLAIMED,
    PublishingJob.State.READY,
    PublishingJob.State.DISPATCHING,
)


class WorkerGuardError(ValueError):
    pass


class WorkerGuardConflict(WorkerGuardError):
    pass


def _validate(*, pipeline_id, limit, now):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise WorkerGuardError('limit must be between 1 and 100.')
    if timezone.is_naive(now):
        raise WorkerGuardError('now must be timezone aware.')
    if not Pipeline.objects.filter(pk=pipeline_id).exists():
        raise WorkerGuardError('Pipeline does not exist.')


def _stale(qs, now):
    return qs.filter(Q(lease_expires_at__lte=now) | Q(lease_expires_at__isnull=True))


def worker_guard_snapshot(*, pipeline_id, limit=20, now=None):
    """Bounded tenant-safe inspection; never return worker secrets/tokens."""
    now = timezone.now() if now is None else now
    _validate(pipeline_id=pipeline_id, limit=limit, now=now)
    base = PublishingJob.objects.filter(pipeline_id=pipeline_id)
    in_flight = base.filter(state__in=IN_FLIGHT)
    stale = _stale(in_flight, now)
    summary = {
        'queued': base.filter(state=PublishingJob.State.QUEUED).count(),
        'in_flight': in_flight.count(),
        'expired_or_missing_lease': stale.count(),
        'uncertain': base.filter(state=PublishingJob.State.UNCERTAIN).count(),
        'published': base.filter(state=PublishingJob.State.PUBLISHED).count(),
    }
    per_state = dict(stale.values('state').annotate(total=Count('pk')).values_list('state', 'total'))
    rows = list(stale.select_related('facebook_account', 'facebook_group')
                .order_by('lease_expires_at', 'pk')[:limit])
    held_accounts, held_groups = held_subject_ids(pipeline_id=pipeline_id)
    event_count = WorkerLeaseEvent.objects.filter(pipeline_id=pipeline_id).count()
    return {
        'pipeline_id': str(pipeline_id),
        'checked_at': now.isoformat(),
        'summary': {**summary,
                    'expired_claimed': per_state.get(PublishingJob.State.CLAIMED, 0),
                    'expired_ready': per_state.get(PublishingJob.State.READY, 0),
                    'expired_dispatching': per_state.get(PublishingJob.State.DISPATCHING, 0),
                    'held_accounts': len(held_accounts), 'held_groups': len(held_groups),
                    'recorded_quarantines': event_count},
        'items': [{
            'job_id': str(job.pk),
            'state': job.state,
            'attempt_number': job.attempt_count,
            'account': {'id': str(job.facebook_account_id), 'label': job.facebook_account.label},
            'group': {'id': str(job.facebook_group_id), 'name': job.facebook_group.name},
            'lease_expires_at': job.lease_expires_at.isoformat() if job.lease_expires_at else None,
            'reason': 'LEASE_MISSING' if job.lease_expires_at is None else 'LEASE_EXPIRED',
            'requires_reconciliation': True,
            'can_auto_retry': False,
        } for job in rows],
        'truncated': summary['expired_or_missing_lease'] > len(rows),
        'read_only': True,
        'facebook_dispatch_enabled': False,
        'auto_retry_enabled': False,
        'note': 'This is database lease health, not proof of live worker process or Facebook publication.',
    }


@transaction.atomic
def quarantine_stale_leases(*, pipeline_id, limit=20, now=None):
    """Explicit operator action ONLY; idempotent, conservative quarantine.

    A stale worker must not finish any earlier claim after this transaction.
    Even pre-dispatch READY media becomes UNCERTAIN, never silently recycled.
    A concurrent successful terminal transition is excluded under row locks.
    """
    now = timezone.now() if now is None else now
    _validate(pipeline_id=pipeline_id, limit=limit, now=now)
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise WorkerGuardError('Pipeline does not exist.')
    jobs = list(_stale(PublishingJob.objects.select_for_update().filter(
        pipeline_id=pipeline.pk, state__in=IN_FLIGHT), now)
        .order_by('pk')[:limit])
    quarantined = []
    for job in jobs:
        if job.attempt_count < 1:
            raise WorkerGuardConflict('In-flight Job without an Attempt: ' + str(job.pk))
        attempt = (PublishingAttempt.objects.select_for_update()
                   .filter(job_id=job.pk, number=job.attempt_count).first())
        if attempt is None or attempt.state not in (
                PublishingAttempt.State.CLAIMED,
                PublishingAttempt.State.READY,
                PublishingAttempt.State.DISPATCHING,
        ):
            raise WorkerGuardConflict('Inconsistent Attempt, quarantine aborted for ' + str(job.pk))
        if job.media_allocation_id:
            media = MediaAllocation.objects.select_for_update().filter(
                pk=job.media_allocation_id, pipeline_id=pipeline.pk,
            ).first()
            if media is None or media.state not in (
                MediaAllocation.State.RESERVED,
                MediaAllocation.State.UNCERTAIN,
            ):
                raise WorkerGuardConflict('Media is not safe for quarantine: ' + str(job.pk))
            if media.state == MediaAllocation.State.RESERVED:
                media.state = MediaAllocation.State.UNCERTAIN
                media.save(update_fields=['state', 'updated_at'])
        previous_state = job.state
        event = WorkerLeaseEvent.objects.create(
            pipeline=pipeline, job=job, attempt_number=job.attempt_count,
            previous_state=previous_state, reason_code='WORKER_LEASE_EXPIRED',
        )
        job.state = PublishingJob.State.UNCERTAIN
        job.error_code = 'WORKER_LEASE_EXPIRED'
        job.claim_token = ''
        job.worker_id = ''
        job.lease_expires_at = None
        job.save(update_fields=['state', 'error_code', 'claim_token', 'worker_id',
                                'lease_expires_at', 'updated_at'])
        attempt.state = PublishingAttempt.State.UNCERTAIN
        attempt.save(update_fields=['state'])
        quarantined.append({'job_id': str(job.pk), 'event_id': str(event.pk),
                            'previous_state': previous_state})
    remainder = _stale(PublishingJob.objects.filter(
        pipeline_id=pipeline.pk, state__in=IN_FLIGHT), now).count()
    return {
        'pipeline_id': str(pipeline_id),
        'quarantined_count': len(quarantined),
        'quarantined': quarantined,
        'remaining_expired_or_missing_lease': remainder,
        'complete': remainder == 0,
        'auto_retry_enabled': False,
        'facebook_dispatch_enabled': False,
        'action': 'explicit_quarantine_only',
    }
