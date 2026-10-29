"""Step 9.7.19: bounded, read-only latency and query-count diagnostics.

This is a baseline sampled measurement, NOT a high-concurrency load test.
No Facebook/R2 network, cookies, tokens or SQL statements in the response.
No scheduler enqueue, worker claim, retry, or Job state mutations.
"""
import math
from time import monotonic

from django.db import connection
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import PipelineSchedule
from modules.publishing.services.operations_health import health_snapshot
from modules.publishing.services.pilot_readiness import pilot_readiness_snapshot
from modules.publishing.services.security_audit import security_snapshot
from modules.publishing.services.scheduler_tick import tick_due_schedules
from modules.publishing.services.worker_reliability import worker_guard_snapshot


class PerformanceStabilityError(ValueError):
    pass


# Advisory defaults, NOT a certified SLA. Tunable from CLI only.
DEFAULT_BUDGETS = {
    'database_ping': 500,
    'operations_health': 2500,
    'scheduler_preview': 1500,
    'worker_guard': 1500,
    'pilot_readiness': 2500,
    'security_audit': 2500,
}


class _QueryCounter:
    """Only count execute calls; never save SQL, SQL params or sensitive values."""
    def __init__(self):
        self.total = 0

    def __call__(self, execute, sql, params, many, context):
        self.total += 1
        return execute(sql, params, many, context)


def _quantile(values, percentile):
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return round(ordered[index], 2)


def _query_ping():
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        if cursor.fetchone() != (1,):
            raise PerformanceStabilityError('Database ping did not return 1')
    return {'complete': True, 'attention': False}


def _workloads(pipeline_id, limit, now):
    def ops():
        data = health_snapshot(pipeline_id=pipeline_id, sample_limit=limit, now=now)
        return {'complete': bool(data['integrity']['complete']),
                'attention': data['status'] != 'healthy'}

    def scheduler():
        data = tick_due_schedules(enqueue=False, limit=3, pipeline_id=pipeline_id,
                                  worker_id='performance-preview', now=now)
        if data['mode'] != 'preview' or data['queued_count'] != 0:
            raise PerformanceStabilityError('Scheduler preview violated read-only contract')
        # Preview sees the oldest 3 schedules; partial due work is disclosed.
        due = PipelineSchedule.objects.filter(
            pipeline_id=pipeline_id, enabled=True, next_run_at__lte=now,
            pipeline__status=Pipeline.Status.ACTIVE,
        ).count()
        return {'complete': due <= 3, 'attention': data['error_count'] > 0}

    def worker():
        data = worker_guard_snapshot(pipeline_id=pipeline_id, limit=limit, now=now)
        return {'complete': not data['truncated'],
                'attention': data['summary']['expired_or_missing_lease'] > 0}

    def pilot():
        data = pilot_readiness_snapshot(pipeline_id=pipeline_id, limit=limit, now=now)
        return {'complete': not data['truncated'], 'attention': False}

    def security():
        data = security_snapshot(pipeline_id=pipeline_id, limit=limit)
        return {'complete': data['complete'],
                'attention': data['status'] != 'consistent'}

    return {
        'database_ping': _query_ping,
        'operations_health': ops,
        'scheduler_preview': scheduler,
        'worker_guard': worker,
        'pilot_readiness': pilot,
        'security_audit': security,
    }


def performance_snapshot(*, pipeline_id, repeats=1, limit=25, threshold_ms=None, now=None):
    """Bounded sequential reads of one Pipeline; fail closed on partial work.

    No SQL query bodies or exception details are returned. Timing limits are
    advisory and *not* enforced timeouts. Do not call in an unbounded loop.
    """
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise PerformanceStabilityError('repeats phải từ 1 đến 5.')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise PerformanceStabilityError('limit phải từ 1 đến 100.')
    if threshold_ms is not None and (type(threshold_ms) is not int or not 100 <= threshold_ms <= 15000):
        raise PerformanceStabilityError('threshold_ms phải từ 100 đến 15000.')
    now = timezone.now() if now is None else now
    if timezone.is_naive(now):
        raise PerformanceStabilityError('now phải có múi giờ.')
    pipeline = Pipeline.objects.filter(pk=pipeline_id).values('id', 'status').first()
    if pipeline is None:
        raise PerformanceStabilityError('Pipeline không tồn tại.')

    # Snapshot configuration counts only; these are not published-post metrics.
    total_jobs = PublishingJob.objects.filter(pipeline_id=pipeline_id).count()
    total_schedules = PipelineSchedule.objects.filter(pipeline_id=pipeline_id).count()
    samples = []
    errors, slow, incomplete, business_alerts = 0, 0, 0, 0
    for name, probe in _workloads(pipeline_id, limit, now).items():
        measurements, queries = [], []
        probe_incomplete = False
        probe_attention = False
        failure = False
        for _ in range(repeats):
            counter = _QueryCounter()
            started = monotonic()
            try:
                with connection.execute_wrapper(counter):
                    observation = probe()
                # Enforce a strict, minimal response shape on internal probes.
                if observation.get('complete') is not True:
                    probe_incomplete = True
                if observation.get('attention') is True:
                    probe_attention = True
            except Exception:
                failure = True
                # Do not leak database exceptions or credentials.
            elapsed = round((monotonic() - started) * 1000, 2)
            measurements.append(elapsed)
            queries.append(counter.total)
            if failure:
                break
        budget = threshold_ms if threshold_ms is not None else DEFAULT_BUDGETS[name]
        p95 = _quantile(measurements, .95)
        if failure:
            state = 'error'
            errors += 1
        elif probe_incomplete:
            state = 'incomplete'
            incomplete += 1
        elif p95 > budget:
            state = 'slow'
            slow += 1
        else:
            state = 'pass'
        if probe_attention:
            business_alerts += 1
        samples.append({
            'name': name, 'status': state, 'runs': len(measurements),
            'p50_ms': _quantile(measurements, .5), 'p95_ms': p95,
            'max_ms': round(max(measurements), 2), 'query_count_max': max(queries),
            'budget_ms': budget, 'operational_attention': probe_attention,
        })

    if errors:
        status = 'error'
    elif incomplete:
        status = 'incomplete'
    elif slow or business_alerts:
        status = 'attention'
    elif not total_jobs and not total_schedules:
        status = 'not_configured'
    else:
        status = 'pass'
    return {
        'pipeline_id': str(pipeline_id), 'checked_at': timezone.now().isoformat(),
        'status': status, 'pipeline_status': pipeline['status'],
        'summary': {'probes': len(samples), 'errors': errors, 'slow': slow,
                    'incomplete': incomplete, 'operational_attention': business_alerts,
                    'jobs': total_jobs, 'schedules': total_schedules},
        'probes': samples, 'repeats': repeats, 'sample_limit': limit,
        'read_only': True, 'facebook_dispatch_enabled': False,
        'load_test_performed': False, 'production_capacity_certified': False,
        'note': ('Đây là phép đo truy vấn nội bộ tuần tự trên Neon; không kiểm thử HTTP, '
                 'concurrency, throughput thực hoặc năng lực đăng bài Facebook. '
                 'Ngưỡng thời gian chỉ mang tính gợi ý, không phải timeout cứng.'),
    }
