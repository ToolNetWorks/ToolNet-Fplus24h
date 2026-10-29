"""Tenant-scoped reconciliation and operational alerting.

Read-only inspection: no Facebook, credentials, proxy connections, or state
changes. Only a separately invoked CLI may quarantine expired worker claims.
PUBLISHED without an external post id is *never* considered verified.
"""
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import AccountProxyPin, GroupHealth

REVIEW_STATES = (
    PublishingJob.State.UNCERTAIN,
    PublishingJob.State.DISPATCHING,
    PublishingJob.State.FAILED,
)
HOLD_STATES = (
    PublishingJob.State.CLAIMED,
    PublishingJob.State.READY,
    PublishingJob.State.DISPATCHING,
    PublishingJob.State.UNCERTAIN,
)


def _risk_filter(now):
    return (
        Q(state__in=REVIEW_STATES)
        | Q(state__in=(PublishingJob.State.CLAIMED, PublishingJob.State.READY),
            lease_expires_at__lte=now)
        | Q(state=PublishingJob.State.PUBLISHED, external_post_id='')
    )


def _reason(job, now):
    if job.state == PublishingJob.State.UNCERTAIN:
        return 'UNVERIFIED_POST_RESULT', 'critical'
    if job.state == PublishingJob.State.DISPATCHING:
        if job.lease_expires_at and job.lease_expires_at <= now:
            return 'DISPATCH_LEASE_EXPIRED', 'critical'
        return 'DISPATCH_AWAITING_VERIFICATION', 'warning'
    if job.state in (PublishingJob.State.CLAIMED, PublishingJob.State.READY):
        return 'WORKER_LEASE_EXPIRED', 'critical'
    if job.state == PublishingJob.State.PUBLISHED:
        return 'PUBLISHED_MISSING_POST_ID', 'critical'
    return 'JOB_FAILED', 'warning'


def held_subject_ids(*, pipeline_id):
    """Account/Group hold from unverified or in-flight operations.

    Includes malformed PUBLISHED without external_post_id, which is unverified.
    A read-only query; never releases or retries a held Job.
    """
    rows = PublishingJob.objects.filter(pipeline_id=pipeline_id).filter(
        Q(state__in=HOLD_STATES)
        | Q(state=PublishingJob.State.PUBLISHED, external_post_id='')
    ).values_list('facebook_account_id', 'facebook_group_id').distinct()
    account_ids = set()
    group_ids = set()
    for account_id, group_id in rows:
        account_ids.add(account_id)
        group_ids.add(group_id)
    return account_ids, group_ids


def blocked_account_ids(*, pipeline_id):
    return held_subject_ids(pipeline_id=pipeline_id)[0]


def reconciliation_snapshot(*, pipeline_id, page=1, page_size=20, now=None):
    """Read only. Every query is scoped to exactly one Pipeline."""
    if type(page) is not int or page < 1:
        raise ValueError('page phải >= 1.')
    if type(page_size) is not int or not 1 <= page_size <= 50:
        raise ValueError('page_size phải từ 1 đến 50.')
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise ValueError('Thời gian không có múi giờ.')

    all_jobs = PublishingJob.objects.filter(pipeline_id=pipeline_id)
    flagged = all_jobs.filter(_risk_filter(now)).exclude(review_case__status='closed')
    counts = all_jobs.aggregate(
        total=Count('pk'),
        queued=Count('pk', filter=Q(state=PublishingJob.State.QUEUED)),
        claimed=Count('pk', filter=Q(state=PublishingJob.State.CLAIMED)),
        ready=Count('pk', filter=Q(state=PublishingJob.State.READY)),
        dispatching=Count('pk', filter=Q(state=PublishingJob.State.DISPATCHING)),
        uncertain=Count('pk', filter=Q(state=PublishingJob.State.UNCERTAIN)),
        failed=Count('pk', filter=Q(state=PublishingJob.State.FAILED)),
        published_verified=Count('pk', filter=(
            Q(state=PublishingJob.State.PUBLISHED) & ~Q(external_post_id='')
        )),
        published_missing_id=Count('pk', filter=Q(
            state=PublishingJob.State.PUBLISHED, external_post_id=''
        )),
    )
    held_ids, held_group_ids = held_subject_ids(pipeline_id=pipeline_id)

    paged = Paginator(flagged.select_related(
        'facebook_account', 'facebook_group'
    ).order_by('-updated_at', '-pk'), page_size)
    page_obj = paged.get_page(page)
    # get_page() clamps out-of-range page numbers, so explicitly reject them.
    if page_obj.number != page:
        raise ValueError('Trang yêu cầu không tồn tại.')
    alerts = []
    for job in page_obj.object_list:
        reason, severity = _reason(job, now)
        alerts.append({
            'job_id': str(job.pk),
            'state': job.state,
            'reason_code': reason,
            'severity': severity,
            'error_code': job.error_code or None,
            'account': {'id': str(job.facebook_account_id), 'label': job.facebook_account.label},
            'group': {'id': str(job.facebook_group_id), 'name': job.facebook_group.name},
            'scheduled_at': job.scheduled_at.isoformat(),
            'updated_at': job.updated_at.isoformat(),
            'lease_expires_at': job.lease_expires_at.isoformat() if job.lease_expires_at else None,
            'can_auto_retry': False,
        })

    # Account and Group alerts are advisory; never alter their database status.
    account_alerts = []
    accounts = list(FacebookAccount.objects.filter(
        pipeline_id=pipeline_id
    ).order_by('label', 'pk')[:500])
    account_ids = [x.pk for x in accounts]
    proxies = {x.account_id: x for x in ProxyEndpoint.objects.filter(
        pipeline_id=pipeline_id, account_id__in=account_ids)}
    pins = {x.account_id: x for x in AccountProxyPin.objects.filter(
        pipeline_id=pipeline_id, account_id__in=account_ids)}
    for account in accounts:
        issues = []
        if account.pk in held_ids:
            issues.append('ACCOUNT_HAS_IN_FLIGHT_OR_UNVERIFIED_JOB')
        if account.connection_status != FacebookAccount.ConnectionStatus.CONNECTED:
            issues.append('ACCOUNT_NOT_CONNECTED')
        proxy = proxies.get(account.pk)
        pin = pins.get(account.pk)
        if proxy is None:
            issues.append('PROXY_MISSING')
        else:
            if not proxy.is_enabled or proxy.health_status != ProxyEndpoint.HealthStatus.HEALTHY:
                issues.append('PROXY_NOT_HEALTHY')
            if not proxy.last_checked_at or not (
                now - timedelta(hours=24) <= proxy.last_checked_at <= now
            ):
                issues.append('PROXY_HEALTH_STALE')
            if pin and (pin.proxy_id != proxy.pk or pin.pinned_exit_ip != proxy.exit_ip):
                issues.append('PROXY_PIN_MISMATCH')
        if issues:
            account_alerts.append({
                'account_id': str(account.pk), 'label': account.label, 'codes': issues,
            })

    health = list(GroupHealth.objects.filter(
        pipeline_id=pipeline_id,
    ).exclude(state=GroupHealth.State.ACTIVE).select_related('group').order_by('group__name', 'pk')[:500])
    group_alerts = [{
        'group_id': str(row.group_id), 'name': row.group.name,
        'state': row.state, 'reason_code': row.reason_code or None,
        'review_after': row.review_after.isoformat() if row.review_after else None,
    } for row in health]
    return {
        'pipeline_id': str(pipeline_id),
        'summary': {
            **counts,
            'review_required_jobs': paged.count,
            'held_accounts': len(held_ids),
            'held_groups': len(held_group_ids),
            'group_health_alerts': GroupHealth.objects.filter(
                pipeline_id=pipeline_id,
            ).exclude(state=GroupHealth.State.ACTIVE).count(),
            'account_alerts_shown': len(account_alerts),
        },
        'jobs': alerts,
        'account_alerts': account_alerts,
        'group_alerts': group_alerts,
        'pagination': {
            'page': page_obj.number, 'page_size': page_size,
            'total': paged.count, 'total_pages': paged.num_pages,
            'has_next': page_obj.has_next(), 'has_previous': page_obj.has_previous(),
        },
        'account_alerts_truncated': FacebookAccount.objects.filter(pipeline_id=pipeline_id).count() > len(accounts),
        'group_alerts_truncated': GroupHealth.objects.filter(pipeline_id=pipeline_id).exclude(state=GroupHealth.State.ACTIVE).count() > len(group_alerts),
        'facebook_dispatch_enabled': False,
        'auto_retry_enabled': False,
    }
