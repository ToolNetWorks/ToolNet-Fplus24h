"""Read-only, bounded operational telemetry; no Facebook calls or secrets."""
from datetime import timedelta
from time import monotonic

from django.db import connection
from django.db.models import Count, Q
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import PipelineSchedule
from modules.publishing.scheduler_tick_models import SchedulerTickAudit
from modules.publishing.services.integrity_audit import integrity_snapshot


class OperationsHealthError(ValueError):
    pass


def health_snapshot(*, pipeline_id, sample_limit=250, now=None):
    """Tenant scoped. A partial or failed inspection is NEVER healthy."""
    if not isinstance(sample_limit, int) or isinstance(sample_limit, bool) or not 1 <= sample_limit <= 1000:
        raise OperationsHealthError('sample_limit must be 1..1000')
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise OperationsHealthError('now must be timezone aware')
    started = monotonic()
    pipeline = Pipeline.objects.filter(pk=pipeline_id).values('id', 'status').first()
    if not pipeline:
        raise OperationsHealthError('Pipeline not found')
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        db_ok = cursor.fetchone() == (1,)
    jobs = PublishingJob.objects.filter(pipeline_id=pipeline_id)
    states = dict(jobs.values_list('state').annotate(n=Count('pk')))
    schedules = PipelineSchedule.objects.filter(pipeline_id=pipeline_id)
    due = schedules.filter(enabled=True, next_run_at__lte=now)
    overdue_15m = due.filter(next_run_at__lt=now - timedelta(minutes=15)).count()
    ticks = SchedulerTickAudit.objects.filter(pipeline_id=pipeline_id)
    last_tick = ticks.order_by('-updated_at').values('updated_at', 'outcome', 'error_code').first()
    recent_tick_errors = ticks.filter(outcome=SchedulerTickAudit.Outcome.ERROR,
                                      updated_at__gte=now - timedelta(hours=1)).count()
    stale_uncertain = jobs.filter(state=PublishingJob.State.UNCERTAIN,
                                  updated_at__lt=now - timedelta(hours=48)).count()
    expired_claims = jobs.filter(state__in=[PublishingJob.State.CLAIMED, PublishingJob.State.READY],
                                 lease_expires_at__lt=now).count()
    integrity = integrity_snapshot(pipeline_id=pipeline_id, sample_limit=sample_limit, now=now)
    alerts = []
    if not db_ok:
        alerts.append('DATABASE_UNAVAILABLE')
    if overdue_15m:
        alerts.append('SCHEDULE_OVERDUE')
    if recent_tick_errors:
        alerts.append('SCHEDULER_TICK_ERRORS')
    if stale_uncertain:
        alerts.append('UNRESOLVED_JOBS_OVER_48H')
    if expired_claims:
        alerts.append('EXPIRED_WORKER_LEASES')
    if integrity['status'] != 'consistent':
        alerts.append('INTEGRITY_' + integrity['status'].upper())
    return {
        'pipeline_id': str(pipeline_id), 'checked_at': now.isoformat(),
        'status': 'attention' if alerts else 'healthy',
        'pipeline_status': pipeline['status'],
        'database': {'connected': db_ok, 'vendor': connection.vendor},
        'jobs_by_state': states,
        'schedules': {'total': schedules.count(), 'enabled': schedules.filter(enabled=True).count(),
                      'due': due.count(), 'overdue_15m': overdue_15m},
        'tick': {'last_at': last_tick['updated_at'].isoformat() if last_tick else None,
                 'last_outcome': last_tick['outcome'] if last_tick else None,
                 'errors_1h': recent_tick_errors},
        'worker': {'expired_claims': expired_claims, 'uncertain_over_48h': stale_uncertain},
        'integrity': {'status': integrity['status'], 'complete': integrity.get('complete'),
                      'issues': len(integrity.get('findings', []))},
        'alerts': alerts, 'query_duration_ms': round((monotonic() - started) * 1000, 1),
        'note': 'Read-only database snapshot; not proof of Facebook publication or running systemd processes.',
    }
