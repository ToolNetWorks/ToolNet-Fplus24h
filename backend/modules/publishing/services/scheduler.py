"""Opt-in, idempotent Scheduler + Account/Group Assignment Engine.

Never contacts Facebook, decrypts credentials, or executes publication.
Serializes each Pipeline at the database boundary. Preview makes NO writes.
Eligibility must be manually evidenced and unexpired for EACH Account/Group.
"""
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import (
    PipelineSchedule, AccountGroupEligibility, GroupHealth,
    AccountProxyPin, ScheduledBatch, ScheduledAssignment,
)
from modules.publishing.services.job_engine import enqueue_job
from modules.publishing.services.reconciliation import held_subject_ids

MIN_ACCOUNT_GAP = timedelta(minutes=15)
MIN_GROUP_GAP = timedelta(minutes=60)
MAX_ACCOUNT_24H = 12
PROXY_HEALTH_TTL = timedelta(hours=24)
BLOCKING_JOB_STATES = (
    PublishingJob.State.QUEUED,
    PublishingJob.State.CLAIMED,
    PublishingJob.State.READY,
    PublishingJob.State.DISPATCHING,
    PublishingJob.State.UNCERTAIN,
)


class ScheduleError(Exception):
    pass


def _stable_rank(*parts):
    return hashlib.sha256(':'.join(map(str, parts)).encode('utf-8')).hexdigest()


def _batch_payload(batch):
    return {
        'schedule_id': str(batch.schedule_id),
        'batch_id': str(batch.pk),
        'slot_at': batch.slot_at.isoformat(),
        'assigned_count': batch.assigned_count,
        'skipped': batch.skipped,
        'assignments': [
            {
                'job_id': str(row.job_id),
                'group_id': str(row.group_id),
                'account_id': str(row.account_id),
                'proxy_id': str(row.proxy_id),
                'exit_ip': row.exit_ip_snapshot,
                'scheduled_at': row.scheduled_at.isoformat(),
            }
            for row in batch.assignments.order_by('scheduled_at', 'pk')
        ],
        'replayed': True,
        'committed': True,
    }


def _eligible_accounts(pipeline, accounts, now):
    proxy_by_account = {
        proxy.account_id: proxy
        for proxy in ProxyEndpoint.objects.filter(
            pipeline_id=pipeline.pk, account_id__in=[x.pk for x in accounts]
        )
    }
    pins = {
        row.account_id: row
        for row in AccountProxyPin.objects.filter(pipeline_id=pipeline.pk)
    }
    valid = {}
    held_account_ids, _ = held_subject_ids(pipeline_id=pipeline.pk)
    for account in accounts:
        if account.pk in held_account_ids:
            continue  # Never schedule a second job while prior posting is unverified.
        proxy = proxy_by_account.get(account.pk)
        if not proxy or not proxy.is_enabled or proxy.health_status != ProxyEndpoint.HealthStatus.HEALTHY:
            continue
        if not proxy.exit_ip or not proxy.last_checked_at:
            continue
        if not (now - PROXY_HEALTH_TTL <= proxy.last_checked_at <= now):
            continue
        pin = pins.get(account.pk)
        if pin and (pin.proxy_id != proxy.pk or pin.pinned_exit_ip != proxy.exit_ip):
            continue  # fail closed; never silently change IP or proxy
        valid[account.pk] = (account, proxy, pin)
    return valid


def _historical_constraints(pipeline_id, now, slot):
    existing = list(
        PublishingJob.objects.filter(pipeline_id=pipeline_id).filter(
            Q(state__in=BLOCKING_JOB_STATES) |
            Q(state=PublishingJob.State.PUBLISHED,
              finalized_at__gte=now - timedelta(days=1))
        ).values(
            'facebook_account_id', 'facebook_group_id', 'state',
            'scheduled_at', 'finalized_at'
        )
    )
    group_blocked = set()
    group_last = {}
    account_times = defaultdict(list)
    account_count = defaultdict(int)
    for job in existing:
        acc = job['facebook_account_id']
        grp = job['facebook_group_id']
        state = job['state']
        if state in BLOCKING_JOB_STATES:
            group_blocked.add(grp)
            account_times[acc].append(job['scheduled_at'])
            if now - timedelta(days=1) <= job['scheduled_at'] <= slot + timedelta(days=1):
                account_count[acc] += 1
        else:
            finished = job['finalized_at']
            if finished is not None:
                group_last[grp] = max(group_last.get(grp, finished), finished)
                account_times[acc].append(finished)
                if finished >= now - timedelta(days=1):
                    account_count[acc] += 1
    return group_blocked, group_last, account_times, account_count


@transaction.atomic
def plan_schedule(*, schedule_id, commit=False, now=None):
    """Generate at most one due batch; replays do not create duplicate Jobs.

    commit=False is a read-only preview. commit=True requires schedule.enabled.
    A scheduled Job is not a Facebook post and does not imply Group eligibility
    is still valid when a human actually decides to post later.
    """
    if type(commit) is not bool:
        raise ScheduleError('commit phải là boolean.')
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise ScheduleError('Cần thời gian có múi giờ.')

    meta = PipelineSchedule.objects.filter(pk=schedule_id).values('pipeline_id').first()
    if meta is None:
        raise ScheduleError('Không tìm thấy lịch đăng.')
    pipeline = Pipeline.objects.select_for_update().filter(pk=meta['pipeline_id']).first()
    if pipeline is None:
        raise ScheduleError('Pipeline không tồn tại.')
    schedule = PipelineSchedule.objects.select_for_update().get(pk=schedule_id, pipeline_id=pipeline.pk)
    slot = schedule.next_run_at

    if commit and (pipeline.status != Pipeline.Status.ACTIVE or not schedule.enabled):
        raise ScheduleError('Pipeline hoặc lịch đăng đang tắt.')
    if commit and slot > now:
        return {
            'schedule_id': str(schedule.pk), 'slot_at': slot.isoformat(),
            'status': 'not_due', 'committed': False, 'assignments': [], 'skipped': [],
        }
    old_batch = ScheduledBatch.objects.filter(schedule_id=schedule.pk, slot_at=slot).first()
    if old_batch:
        replay = _batch_payload(old_batch)
        if commit:
            # Repair a stale/rewound cursor in the same Pipeline->Schedule lock.
            # One stored Batch per slot means no duplicate PublishingJobs.
            interval = timedelta(minutes=schedule.interval_minutes)
            schedule.next_run_at = max(slot + interval, now + interval)
            schedule.save(update_fields=['next_run_at', 'updated_at'])
        replay['next_run_at'] = schedule.next_run_at.isoformat()
        return replay

    target_time = max(slot, now)
    accounts = list(FacebookAccount.objects.filter(
        pipeline_id=pipeline.pk,
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    ).order_by('pk'))
    valid_accounts = _eligible_accounts(pipeline, accounts, now)
    groups = list(FacebookGroup.objects.filter(pipeline_id=pipeline.pk).order_by('pk'))
    group_health = {
        row.group_id: row
        for row in GroupHealth.objects.filter(pipeline_id=pipeline.pk)
    }
    eligibilities = defaultdict(list)
    verified_pairs = defaultdict(list)
    for row in AccountGroupEligibility.objects.filter(
        pipeline_id=pipeline.pk,
        state=AccountGroupEligibility.State.VERIFIED,
        verified_at__lte=now,
        expires_at__gt=target_time,
    ):
        if schedule.require_anonymous and not row.can_post_anonymous:
            continue
        # Group membership is not a filtering criterion. Account may be member or non-member.
        verified_pairs[row.group_id].append(row.account_id)
        if row.account_id in valid_accounts:
            eligibilities[row.group_id].append(row.account_id)

    group_blocked, group_last, account_times, account_count = _historical_constraints(
        pipeline.pk, now, target_time
    )
    assigned_in_batch = defaultdict(int)
    next_available = defaultdict(lambda: target_time)
    for account_id, times in account_times.items():
        if times:
            next_available[account_id] = max(target_time, max(times) + MIN_ACCOUNT_GAP)

    candidates = sorted(groups, key=lambda group: _stable_rank(schedule.pk, slot.isoformat(), group.pk))
    assigned = []
    skipped = []
    for group in candidates:
        if len(assigned) >= schedule.max_groups_per_run:
            skipped.append({'group_id': str(group.pk), 'code': 'BATCH_LIMIT'})
            continue
        if not group.is_enabled:
            skipped.append({'group_id': str(group.pk), 'code': 'GROUP_DISABLED'})
            continue
        health = group_health.get(group.pk)
        if health and health.state != GroupHealth.State.ACTIVE:
            skipped.append({'group_id': str(group.pk), 'code': 'GROUP_' + health.state.upper()})
            continue
        if group.pk in group_blocked:
            skipped.append({'group_id': str(group.pk), 'code': 'GROUP_HAS_PENDING_JOB'})
            continue
        last_group = group_last.get(group.pk)
        if last_group and last_group + MIN_GROUP_GAP > target_time:
            skipped.append({'group_id': str(group.pk), 'code': 'GROUP_COOLDOWN'})
            continue
        eligible_ids = eligibilities.get(group.pk, ())
        if not eligible_ids:
            code = ('ACCOUNT_PROXY_NOT_READY' if verified_pairs.get(group.pk)
                    else 'NO_VERIFIED_ELIGIBLE_ACCOUNT')
            skipped.append({'group_id': str(group.pk), 'code': code})
            continue
        choices = [
            acc_id for acc_id in eligible_ids
            if account_count[acc_id] < MAX_ACCOUNT_24H
        ]
        if not choices:
            skipped.append({'group_id': str(group.pk), 'code': 'ACCOUNT_CAPACITY_EXHAUSTED'})
            continue
        # Balanced assignment with deterministic hash tie-breaker; NOT behavior masking.
        acc_id = min(choices, key=lambda aid: (
            assigned_in_batch[aid], next_available[aid],
            _stable_rank(schedule.pk, slot, group.pk, aid)
        ))
        account, proxy, pin = valid_accounts[acc_id]
        at = next_available[acc_id]
        caption = (schedule.caption_template.replace('{group_name}', group.name)
                   .replace('{date}', at.astimezone(ZoneInfo(schedule.timezone_name)).strftime('%d/%m/%Y')))
        if len(caption) > 5000:
            skipped.append({'group_id': str(group.pk), 'code': 'CAPTION_TOO_LONG'})
            continue
        assigned.append({
            'group_id': str(group.pk), 'account_id': str(account.pk),
            'proxy_id': str(proxy.pk), 'exit_ip': str(proxy.exit_ip),
            'scheduled_at': at.isoformat(), 'caption': caption,
            'will_pin_proxy': pin is None,
        })
        assigned_in_batch[acc_id] += 1
        account_count[acc_id] += 1
        next_available[acc_id] = at + MIN_ACCOUNT_GAP

    result = {
        'schedule_id': str(schedule.pk), 'slot_at': slot.isoformat(),
        'status': 'planned', 'committed': False,
        'assigned_count': len(assigned), 'assignments': assigned,
        'skipped': skipped, 'next_run_at': schedule.next_run_at.isoformat(),
    }
    if not commit:
        return result

    batch = ScheduledBatch.objects.create(
        pipeline=pipeline, schedule=schedule, slot_at=slot,
        assigned_count=len(assigned), skipped=skipped,
    )
    for assignment in assigned:
        account_id = assignment['account_id']
        proxy_id = assignment['proxy_id']
        pin, created = AccountProxyPin.objects.get_or_create(
            account_id=account_id,
            defaults={
                'pipeline': pipeline,
                'proxy_id': proxy_id,
                'pinned_exit_ip': assignment['exit_ip'],
            },
        )
        if not created and (str(pin.proxy_id) != proxy_id or pin.pinned_exit_ip != assignment['exit_ip']):
            raise ScheduleError('Proxy Pin đã thay đổi, hủy toàn bộ batch.')
        request_key = 'sch-' + _stable_rank(schedule.pk, slot.isoformat(), assignment['group_id'])
        job = enqueue_job(
            pipeline_id=pipeline.pk,
            account_id=account_id,
            group_id=assignment['group_id'],
            request_key=request_key, caption=assignment['caption'],
            scheduled_at=datetime.fromisoformat(assignment['scheduled_at']),
            max_attempts=3,
        )
        ScheduledAssignment.objects.create(
            batch=batch, job_id=job['id'], account_id=account_id,
            group_id=assignment['group_id'], proxy_id=proxy_id,
            exit_ip_snapshot=assignment['exit_ip'],
            scheduled_at=datetime.fromisoformat(assignment['scheduled_at']),
        )
        assignment['job_id'] = job['id']

    interval = timedelta(minutes=schedule.interval_minutes)
    # Skip missed periods instead of creating a burst of backfilled Jobs.
    schedule.next_run_at = max(slot + interval, now + interval)
    schedule.save(update_fields=['next_run_at', 'updated_at'])
    result.update({
        'status': 'queued_for_review', 'committed': True,
        'batch_id': str(batch.pk), 'next_run_at': schedule.next_run_at.isoformat(),
    })
    return result
