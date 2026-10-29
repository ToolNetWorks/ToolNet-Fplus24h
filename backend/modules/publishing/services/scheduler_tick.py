"""Multi-worker safe, opt-in Scheduler Tick orchestration.

No Facebook requests, cookies, R2 operations, claim/preparation, or posting.
The plan_schedule() service locks Pipeline then Schedule in PostgreSQL.
A second Tick observing the same due slot waits, then receives NOT_DUE.
The unique ScheduledBatch(schedule,slot_at) is a second idempotency boundary.

This service DOES NOT run by import; invoke the CLI explicitly.
"""
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.scheduler_models import PipelineSchedule, ScheduledBatch
from modules.publishing.scheduler_tick_models import SchedulerTickAudit
from modules.publishing.services.scheduler import plan_schedule

logger = logging.getLogger(__name__)

MAX_SCHEDULES_PER_TICK = 100
ERROR_RETRY_BACKOFF_SECONDS = 300
WORKER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$')


class TickValidationError(ValueError):
    pass


def _validate(*, enqueue, limit, worker_id, now):
    if type(enqueue) is not bool:
        raise TickValidationError('enqueue phải là boolean.')
    if type(limit) is not int or not 1 <= limit <= MAX_SCHEDULES_PER_TICK:
        raise TickValidationError('limit phải từ 1 đến 100.')
    if not isinstance(worker_id, str) or not WORKER_RE.fullmatch(worker_id):
        raise TickValidationError('worker_id không hợp lệ.')
    if timezone.is_naive(now):
        raise TickValidationError('now phải có múi giờ.')


def _due_rows(*, now, limit, enqueue, pipeline_id, schedule_id):
    qs = PipelineSchedule.objects.filter(
        enabled=True,
        next_run_at__lte=now,
        pipeline__status=Pipeline.Status.ACTIVE,
    )
    if pipeline_id is not None:
        qs = qs.filter(pipeline_id=pipeline_id)
    if schedule_id is not None:
        qs = qs.filter(pk=schedule_id)
    if enqueue:
        recent_failure = SchedulerTickAudit.objects.filter(
            schedule_id=OuterRef('pk'),
            slot_at=OuterRef('next_run_at'),
            outcome=SchedulerTickAudit.Outcome.ERROR,
            updated_at__gt=now - timedelta(seconds=ERROR_RETRY_BACKOFF_SECONDS),
        )
        qs = qs.annotate(_recent_failure=Exists(recent_failure)).filter(
            _recent_failure=False,
        )
    return list(qs.order_by('next_run_at', 'pk').values(
        'id', 'pipeline_id', 'next_run_at',
    )[:limit])


@transaction.atomic
def _record(*, row, worker_id, outcome, assigned_count=0,
            skipped_count=0, error_code='', batch_id=None):
    # Lock the same Pipeline row first, consistent with plan_schedule lock order.
    pipeline = Pipeline.objects.select_for_update().get(pk=row['pipeline_id'])
    old = SchedulerTickAudit.objects.select_for_update().filter(
        schedule_id=row['id'], slot_at=row['next_run_at'],
    ).first()
    if old:
        old.attempt_count += 1
        old.outcome = outcome
        old.assigned_count = assigned_count
        old.skipped_count = skipped_count
        old.worker_id = worker_id
        old.error_code = error_code
        old.batch_id = batch_id
        old.save()
        return old
    return SchedulerTickAudit.objects.create(
        pipeline=pipeline, schedule_id=row['id'], slot_at=row['next_run_at'],
        outcome=outcome, assigned_count=assigned_count,
        skipped_count=skipped_count, worker_id=worker_id,
        error_code=error_code, batch_id=batch_id,
    )


def tick_due_schedules(*, enqueue=False, limit=25, worker_id='scheduler-tick',
                       pipeline_id=None, schedule_id=None, now=None):
    """Scan a bounded set of due slots.

    enqueue=False: pure preview (does not persist audit).
    enqueue=True: create only PublishingJobs in QUEUED state, and an audit.
    One failed schedule must not roll back successful independent schedules.
    Audits use a separate atomic transaction AFTER plan_schedule commits.
    """
    now = now if now is not None else timezone.now()
    _validate(enqueue=enqueue, limit=limit, worker_id=worker_id, now=now)
    due_rows = _due_rows(
        now=now, limit=limit, enqueue=enqueue,
        pipeline_id=pipeline_id, schedule_id=schedule_id,
    )
    items = []
    for row in due_rows:
        base = {
            'schedule_id': str(row['id']),
            'pipeline_id': str(row['pipeline_id']),
            'slot_at': row['next_run_at'].isoformat(),
        }
        try:
            # Never hold an outer transaction before plan_schedule: that
            # service owns Pipeline -> Schedule locks and its own commit.
            result = plan_schedule(schedule_id=row['id'], commit=enqueue, now=now)
        except Exception:
            logger.exception('Scheduler tick error for schedule_id=%s', row['id'])
            item = {**base, 'status': 'error',
                    'error_code': 'SCHEDULE_ERROR',
                    'assigned_count': 0, 'skipped_count': 0}
            if enqueue:
                try:
                    _record(row=row, worker_id=worker_id,
                            outcome=SchedulerTickAudit.Outcome.ERROR,
                            error_code='SCHEDULE_ERROR')
                except Exception:
                    logger.exception('Scheduler audit write failed for schedule_id=%s', row['id'])
                    item['audit_write_failed'] = True
            items.append(item)
            continue

        status = result.get('status', 'unknown')
        if status == 'not_due':
            items.append({**base, 'status': 'not_due',
                          'assigned_count': 0, 'skipped_count': 0})
            continue
        replayed = bool(result.get('replayed'))
        assigned_count = int(result.get('assigned_count', 0))
        skipped_count = len(result.get('skipped', []))
        item = {
            **base, 'status': 'replayed' if replayed else
            ('queued' if enqueue else 'preview'),
            'assigned_count': assigned_count,
            'skipped_count': skipped_count,
            'batch_id': result.get('batch_id'),
        }
        if enqueue:
            try:
                _record(
                    row=row, worker_id=worker_id,
                    outcome=(SchedulerTickAudit.Outcome.REPLAYED if replayed
                             else SchedulerTickAudit.Outcome.QUEUED),
                    assigned_count=assigned_count,
                    skipped_count=skipped_count,
                    batch_id=result.get('batch_id'),
                )
            except Exception:
                logger.exception('Committed batch audit failed for schedule_id=%s', row['id'])
                item['audit_write_failed'] = True
        items.append(item)

    return {
        'mode': 'enqueue' if enqueue else 'preview',
        'scanned_count': len(due_rows),
        'queued_count': sum(x['status'] == 'queued' for x in items),
        'preview_count': sum(x['status'] == 'preview' for x in items),
        'error_count': sum(x['status'] == 'error' for x in items),
        'replayed_count': sum(x['status'] == 'replayed' for x in items),
        'items': items,
        'facebook_dispatch_enabled': False,
    }


def pipeline_tick_status(*, pipeline_id, now=None):
    """Safe CTV-scoped summary; caller must enforce Pipeline membership."""
    now = now if now is not None else timezone.now()
    schedules = list(
        PipelineSchedule.objects.filter(pipeline_id=pipeline_id)
        .order_by('name', 'pk')[:100]
    )
    schedule_ids = [row.pk for row in schedules]
    audits = SchedulerTickAudit.objects.filter(
        pipeline_id=pipeline_id, schedule_id__in=schedule_ids,
    ).order_by('schedule_id', '-updated_at', '-pk').distinct('schedule_id')
    latest_audit = {}
    for row in audits:
        if row.schedule_id not in latest_audit:
            latest_audit[row.schedule_id] = row
    batches = ScheduledBatch.objects.filter(
        pipeline_id=pipeline_id, schedule_id__in=schedule_ids,
    ).order_by('schedule_id', '-created_at', '-pk').distinct('schedule_id')
    latest_batch = {}
    for row in batches:
        if row.schedule_id not in latest_batch:
            latest_batch[row.schedule_id] = row

    return {
        'pipeline_id': str(pipeline_id),
        'schedule_count': PipelineSchedule.objects.filter(pipeline_id=pipeline_id).count(),
        'active_schedule_count': PipelineSchedule.objects.filter(
            pipeline_id=pipeline_id, enabled=True,
        ).count(),
        'due_schedule_count': PipelineSchedule.objects.filter(
            pipeline_id=pipeline_id, enabled=True, next_run_at__lte=now,
        ).count(),
        'schedules': [
            {
                'schedule_id': str(schedule.pk),
                'name': schedule.name,
                'enabled': schedule.enabled,
                'due': bool(schedule.enabled and schedule.next_run_at <= now),
                'next_run_at': schedule.next_run_at.isoformat(),
                'last_tick': (
                    {
                        'outcome': latest_audit[schedule.pk].outcome,
                        'slot_at': latest_audit[schedule.pk].slot_at.isoformat(),
                        'attempt_count': latest_audit[schedule.pk].attempt_count,
                        'assigned_count': latest_audit[schedule.pk].assigned_count,
                        'skipped_count': latest_audit[schedule.pk].skipped_count,
                        'error_code': latest_audit[schedule.pk].error_code or None,
                        'updated_at': latest_audit[schedule.pk].updated_at.isoformat(),
                    }
                    if schedule.pk in latest_audit else None
                ),
                'last_batch': (
                    {
                        'id': str(latest_batch[schedule.pk].pk),
                        'slot_at': latest_batch[schedule.pk].slot_at.isoformat(),
                        'assigned_count': latest_batch[schedule.pk].assigned_count,
                    }
                    if schedule.pk in latest_batch else None
                ),
            }
            for schedule in schedules
        ],
    }
