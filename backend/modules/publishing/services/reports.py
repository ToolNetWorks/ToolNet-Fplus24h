"""Tenant-scoped, read-only reporting of scheduler slots and publishing jobs.

A queued/ready job is not a Facebook post. `published_verified` requires
both the PUBLISHED state and a nonempty external_post_id. No secrets, cookies,
request tokens or network operations are exposed by this module.

Time-window semantics:
- Job figures use the Job's created_at in the last N days, current state.
- Batch/skip figures use the scheduled slot_at in the last N days.
- A schedule filter excludes standalone manually created Jobs.
"""
from collections import Counter
from datetime import timedelta

from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import (
    PipelineSchedule, ScheduledBatch, ScheduledAssignment, GroupHealth,
)
from modules.publishing.scheduler_tick_models import SchedulerTickAudit

JOB_STATES = (
    'queued', 'claimed', 'ready', 'dispatching',
    'uncertain', 'published', 'failed', 'cancelled',
)
VERIFIED = Q(state='published') & ~Q(external_post_id='')


def _date_base(days, now=None):
    return (now or timezone.now()) - timedelta(days=days)


def _validate_schedule(pipeline_id, schedule_id):
    if schedule_id is not None and not PipelineSchedule.objects.filter(
        pk=schedule_id, pipeline_id=pipeline_id,
    ).exists():
        raise Http404('Lịch đăng không thuộc Pipeline.')


def _jobs(pipeline_id, cutoff, schedule_id=None):
    qs = PublishingJob.objects.filter(pipeline_id=pipeline_id, created_at__gte=cutoff)
    if schedule_id:
        qs = qs.filter(scheduled_assignment__batch__schedule_id=schedule_id)
    return qs


def _batches(pipeline_id, cutoff, schedule_id=None):
    qs = ScheduledBatch.objects.filter(pipeline_id=pipeline_id, slot_at__gte=cutoff)
    if schedule_id:
        qs = qs.filter(schedule_id=schedule_id)
    return qs


def _stats(queryset):
    kwargs = {state: Count('id', filter=Q(state=state)) for state in JOB_STATES}
    kwargs['published_verified'] = Count('id', filter=VERIFIED)
    result = queryset.aggregate(total=Count('id'), **kwargs)
    return {key: int(value or 0) for key, value in result.items()}


def _skips(queryset, group_ids=None):
    """Stream JSON skip rows; do not materialize unlimited Batch records."""
    by_code, by_group = Counter(), Counter()
    events = 0
    for skips in queryset.values_list('skipped', flat=True).iterator(chunk_size=200):
        if not isinstance(skips, list):
            continue
        for event in skips:
            if not isinstance(event, dict):
                continue
            group_id = str(event.get('group_id', ''))
            if group_ids is not None and group_id not in group_ids:
                continue
            code = str(event.get('code') or 'UNKNOWN')[:80]
            events += 1
            by_code[code] += 1
            by_group[group_id] += 1
    return events, dict(by_code), dict(by_group)


def report_summary(*, pipeline_id, days=30, schedule_id=None, now=None):
    _validate_schedule(pipeline_id, schedule_id)
    cutoff = _date_base(days, now)
    jobs = _jobs(pipeline_id, cutoff, schedule_id)
    batches = _batches(pipeline_id, cutoff, schedule_id)
    batch_agg = batches.aggregate(total=Count('id'))
    skips, skip_reasons, _ = _skips(batches)
    scheduled_jobs = jobs.filter(scheduled_assignment__isnull=False).count()
    return {
        'pipeline_id': str(pipeline_id), 'window_days': days,
        'schedule_id': str(schedule_id) if schedule_id else None,
        'job_created_at_from': cutoff.isoformat(),
        'batch_slot_at_from': cutoff.isoformat(),
        'jobs': _stats(jobs),
        'scheduled_jobs': scheduled_jobs,
        'manual_jobs': 0 if schedule_id else jobs.count() - scheduled_jobs,
        'batches': int(batch_agg['total'] or 0),
        'skip_events': skips,
        'skip_reasons': skip_reasons,
        'semantics': {
            'queued_is_published': False,
            'published_requires_external_post_id': True,
            'facebook_dispatch_enabled_by_reports': False,
        },
    }


def _page(queryset, page, page_size):
    pages = Paginator(queryset, page_size)
    try:
        selected = pages.page(page)
    except EmptyPage:
        raise Http404('Trang báo cáo không tồn tại.')
    return selected, {
        'page': selected.number, 'page_size': page_size,
        'total': pages.count, 'total_pages': pages.num_pages,
        'has_next': selected.has_next(), 'has_previous': selected.has_previous(),
    }


def report_batches(*, pipeline_id, days=30, schedule_id=None, page=1,
                   page_size=20, now=None):
    _validate_schedule(pipeline_id, schedule_id)
    qs = _batches(pipeline_id, _date_base(days, now), schedule_id)
    selected, pagination = _page(qs.select_related('schedule').order_by('-slot_at', '-pk'), page, page_size)
    items = []
    for batch in selected.object_list:
        items.append({
            'id': str(batch.pk), 'schedule_id': str(batch.schedule_id),
            'schedule_name': batch.schedule.name,
            'slot_at': batch.slot_at.isoformat(),
            'assigned_count': batch.assigned_count,
            'skip_events': len(batch.skipped) if isinstance(batch.skipped, list) else 0,
            'created_at': batch.created_at.isoformat(),
        })
    return {'data': items, 'pagination': pagination}


def report_batch_detail(*, pipeline_id, batch_id):
    batch = ScheduledBatch.objects.filter(
        pk=batch_id, pipeline_id=pipeline_id,
    ).select_related('schedule').first()
    if batch is None:
        raise Http404('Batch không thuộc Pipeline.')
    assignments = list(ScheduledAssignment.objects.filter(
        batch=batch, job__pipeline_id=pipeline_id,
    ).select_related('account', 'group', 'job').order_by('scheduled_at', 'pk'))
    skip_rows = batch.skipped if isinstance(batch.skipped, list) else []
    skip_ids = [row.get('group_id') for row in skip_rows if isinstance(row, dict)]
    skip_groups = {
        str(obj.pk): obj.name
        for obj in FacebookGroup.objects.filter(pipeline_id=pipeline_id, pk__in=skip_ids)
    }
    tick = SchedulerTickAudit.objects.filter(
        pipeline_id=pipeline_id, schedule_id=batch.schedule_id, slot_at=batch.slot_at,
    ).first()
    return {
        'id': str(batch.pk), 'schedule_id': str(batch.schedule_id),
        'schedule_name': batch.schedule.name, 'slot_at': batch.slot_at.isoformat(),
        'assigned_count': batch.assigned_count,
        'created_at': batch.created_at.isoformat(),
        'assignments': [
            {
                'job_id': str(row.job_id),
                'account_id': str(row.account_id), 'account_label': row.account.label,
                'group_id': str(row.group_id), 'group_name': row.group.name,
                'group_url': row.group.group_url,
                'proxy_id': str(row.proxy_id),
                'exit_ip_snapshot': row.exit_ip_snapshot,
                'scheduled_at': row.scheduled_at.isoformat(),
                'job_state': row.job.state,
                'job_error_code': row.job.error_code or None,
                'external_post_id': row.job.external_post_id if (
                    row.job.state == 'published' and row.job.external_post_id
                ) else None,
                'published_verified': bool(row.job.state == 'published' and row.job.external_post_id),
            }
            for row in assignments
        ],
        'skipped': [
            {
                'group_id': str(row.get('group_id', '')),
                'group_name': skip_groups.get(str(row.get('group_id', '')), 'Group không còn tồn tại'),
                'code': str(row.get('code') or 'UNKNOWN')[:80],
            }
            for row in skip_rows if isinstance(row, dict)
        ],
        'tick': {
            'outcome': tick.outcome,
            'attempt_count': tick.attempt_count,
            'error_code': tick.error_code or None,
            'updated_at': tick.updated_at.isoformat(),
        } if tick else None,
    }


def report_groups(*, pipeline_id, days=30, schedule_id=None,
                  search='', page=1, page_size=20, now=None):
    _validate_schedule(pipeline_id, schedule_id)
    qs = FacebookGroup.objects.filter(pipeline_id=pipeline_id)
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(group_url__icontains=search))
    selected, pagination = _page(qs.order_by('name', 'pk'), page, page_size)
    groups = list(selected.object_list)
    ids = [row.pk for row in groups]
    event_stats = {
        row['facebook_group_id']: row for row in
        _jobs(pipeline_id, _date_base(days, now), schedule_id).filter(
            facebook_group_id__in=ids
        ).values('facebook_group_id').annotate(
            jobs=Count('id'),
            queued=Count('id', filter=Q(state='queued')),
            uncertain=Count('id', filter=Q(state='uncertain')),
            published_verified=Count('id', filter=VERIFIED),
        )
    }
    health = {
        row.group_id: row for row in GroupHealth.objects.filter(
            pipeline_id=pipeline_id, group_id__in=ids,
        )
    }
    _, _, skipped = _skips(_batches(pipeline_id, _date_base(days, now), schedule_id),
                            group_ids={str(x) for x in ids})
    return {
        'data': [
            {
                'group_id': str(group.pk), 'name': group.name,
                'group_url': group.group_url, 'is_enabled': group.is_enabled,
                'health_state': health[group.pk].state if group.pk in health else 'active',
                'jobs': event_stats.get(group.pk, {}).get('jobs', 0),
                'queued': event_stats.get(group.pk, {}).get('queued', 0),
                'uncertain': event_stats.get(group.pk, {}).get('uncertain', 0),
                'published_verified': event_stats.get(group.pk, {}).get('published_verified', 0),
                'skip_events': skipped.get(str(group.pk), 0),
            } for group in groups
        ],
        'pagination': pagination,
    }


def report_accounts(*, pipeline_id, days=30, schedule_id=None,
                    search='', page=1, page_size=20, now=None):
    _validate_schedule(pipeline_id, schedule_id)
    qs = FacebookAccount.objects.filter(pipeline_id=pipeline_id)
    if search:
        qs = qs.filter(Q(label__icontains=search) | Q(facebook_user_id__icontains=search))
    selected, pagination = _page(qs.order_by('label', 'pk'), page, page_size)
    accounts = list(selected.object_list)
    ids = [row.pk for row in accounts]
    event_stats = {
        row['facebook_account_id']: row for row in
        _jobs(pipeline_id, _date_base(days, now), schedule_id).filter(
            facebook_account_id__in=ids,
        ).values('facebook_account_id').annotate(
            jobs=Count('id'),
            queued=Count('id', filter=Q(state='queued')),
            uncertain=Count('id', filter=Q(state='uncertain')),
            published_verified=Count('id', filter=VERIFIED),
        )
    }
    proxy_rows = {
        row.account_id: row for row in ProxyEndpoint.objects.filter(
            pipeline_id=pipeline_id, account_id__in=ids,
        )
    }
    return {
        'data': [
            {
                'account_id': str(account.pk), 'label': account.label,
                'connection_status': account.connection_status,
                'proxy_assigned': account.pk in proxy_rows,
                'proxy_health': (
                    proxy_rows[account.pk].health_status if account.pk in proxy_rows else None
                ),
                'jobs': event_stats.get(account.pk, {}).get('jobs', 0),
                'queued': event_stats.get(account.pk, {}).get('queued', 0),
                'uncertain': event_stats.get(account.pk, {}).get('uncertain', 0),
                'published_verified': event_stats.get(account.pk, {}).get('published_verified', 0),
            } for account in accounts
        ],
        'pagination': pagination,
    }
