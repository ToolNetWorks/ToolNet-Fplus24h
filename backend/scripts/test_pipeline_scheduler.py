"""Rollback-only real ORM test: 10 Accounts / 10 Proxy / 50 Groups.

No network, R2, Facebook, cookies, or access to other Pipeline data.
"""
import uuid
from collections import Counter
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import (
    PipelineSchedule, AccountGroupEligibility, GroupHealth,
    AccountProxyPin, ScheduledBatch, ScheduledAssignment,
)
from modules.publishing.services.scheduler import plan_schedule
from modules.api.v1.publishing.scheduler_views import (
    PipelineScheduleListCreateAPIView, SchedulePreviewAPIView,
    AccountGroupEligibilityAPIView,
)

User = get_user_model()
suffix = uuid.uuid4().hex[:10]
now = timezone.now()
factory = APIRequestFactory()


def new_pipeline(tag):
    user = User.objects.create_user(
        username=f'scheduler_{tag}_{suffix}', password=f'Test#{suffix}Aa1!'
    )
    return Pipeline.objects.create(
        name=f'Scheduler {tag} {suffix}', ctv=user, status=Pipeline.Status.ACTIVE,
    ), user


def authenticated(view, method, url, user, pipeline, *, data=None, schedule=None):
    request = (factory.post(url, data or {}, format='json') if method == 'POST'
               else factory.get(url))
    if user is not None:
        force_authenticate(request, user=user)
    kw = {'pipeline_id': pipeline.pk}
    if schedule:
        kw['schedule_id'] = schedule.pk
    return view.as_view()(request, **kw)


with transaction.atomic():
    pipeline, ctv = new_pipeline('primary')
    other, outsider = new_pipeline('foreign')
    accounts = []
    proxies = []
    for i in range(10):
        acc = FacebookAccount.objects.create(
            pipeline=pipeline, label=f'Account {i}',
            connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
        )
        proxy = ProxyEndpoint.objects.create(
            pipeline=pipeline, account=acc,
            host=f'8.8.{i}.8', port=10000 + i, protocol='http',
            is_enabled=True, health_status='healthy',
            exit_ip=f'8.8.{i}.8', last_checked_at=now,
        )
        accounts.append(acc)
        proxies.append(proxy)

    groups = []
    for j in range(50):
        group = FacebookGroup.objects.create(
            pipeline=pipeline, name=f'Group {j}',
            group_url=f'https://www.facebook.com/groups/test{suffix}{j}/',
        )
        groups.append(group)
    records = [
        AccountGroupEligibility(
            pipeline=pipeline, account=acc, group=group,
            state='verified', can_post_anonymous=True,
            can_post_nonmember=True, verified_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=7),
            evidence_note='Manually verified test fixture.',
        )
        for acc in accounts for group in groups
    ]
    AccountGroupEligibility.objects.bulk_create(records)
    GroupHealth.objects.create(
        pipeline=pipeline, group=groups[3], state='unavailable',
        reason_code='MANUAL_VERIFICATION',
        evidence_note='Mock explicit human verification for test.',
    )
    schedule = PipelineSchedule.objects.create(
        pipeline=pipeline, name='Daily trial', enabled=True,
        start_at=now - timedelta(minutes=1),
        next_run_at=now - timedelta(minutes=1),
        interval_minutes=1440, max_groups_per_run=50,
        caption_template='Thông báo: {group_name} - {date}',
        require_anonymous=True, require_nonmember=True,
    )

    preview = plan_schedule(schedule_id=schedule.pk, now=now)
    assert preview['committed'] is False, preview
    assert preview['assigned_count'] == 49, preview
    assert PublishingJob.objects.filter(pipeline=pipeline).count() == 0
    assert AccountProxyPin.objects.filter(pipeline=pipeline).count() == 0
    assert ScheduledBatch.objects.filter(pipeline=pipeline).count() == 0
    print('10 ACCOUNTS / 50 GROUPS PREVIEW READ-ONLY: PASS')

    preview2 = plan_schedule(schedule_id=schedule.pk, now=now)
    assert preview2['assignments'] == preview['assignments']
    print('DETERMINISTIC SLOT ASSIGNMENT: PASS')

    counts = Counter(x['account_id'] for x in preview['assignments'])
    assert len(counts) == 10
    assert max(counts.values()) - min(counts.values()) <= 1
    assert max(counts.values()) <= 12
    assert len(set(x['group_id'] for x in preview['assignments'])) == 49
    assert all('exit_ip' in x and x['proxy_id'] for x in preview['assignments'])
    print('BALANCED ASSIGNMENT + ACCOUNT RATE CAPS: PASS')

    commit = plan_schedule(schedule_id=schedule.pk, now=now, commit=True)
    assert commit['assigned_count'] == 49, commit
    assert all(x.get('job_id') for x in commit['assignments'])
    assert PublishingJob.objects.filter(pipeline=pipeline, state='queued').count() == 49
    assert ScheduledAssignment.objects.filter(batch_id=commit['batch_id']).count() == 49
    assert AccountProxyPin.objects.filter(pipeline=pipeline).count() == 10
    assert not PublishingJob.objects.filter(pipeline=pipeline, state='published').exists()
    assert not ScheduledAssignment.objects.filter(group=groups[3]).exists()
    print('COMMIT ENQUEUES ONLY + PINS 10 PROXIES: PASS')

    # Simulate retry of the exact same schedule cursor after a transport retry.
    old_slot = schedule.start_at
    PipelineSchedule.objects.filter(pk=schedule.pk).update(next_run_at=old_slot)
    duplicate = plan_schedule(schedule_id=schedule.pk, now=now, commit=True)
    assert duplicate['replayed'] is True
    assert PublishingJob.objects.filter(pipeline=pipeline).count() == 49
    print('SAME SLOT REPLAY WITHOUT DUPLICATE JOBS: PASS')

    # New group eligible ONLY for account 0, with its pinned IP changed.
    future_now = now + timedelta(days=2)
    new_group = FacebookGroup.objects.create(
        pipeline=pipeline, name='Pinned Account Only',
        group_url=f'https://www.facebook.com/groups/pinonly{suffix}/',
    )
    AccountGroupEligibility.objects.create(
        pipeline=pipeline, account=accounts[0], group=new_group,
        state='verified', can_post_anonymous=True, can_post_nonmember=True,
        verified_at=now, expires_at=now + timedelta(days=7),
        evidence_note='Account zero checked manually in test.',
    )
    PipelineSchedule.objects.filter(pk=schedule.pk).update(next_run_at=future_now)
    ProxyEndpoint.objects.filter(pipeline=pipeline).update(last_checked_at=future_now)
    proxies[0].refresh_from_db()
    original_exit = proxies[0].exit_ip
    proxies[0].exit_ip = '1.1.1.1'
    proxies[0].save()
    changed = plan_schedule(schedule_id=schedule.pk, now=future_now)
    assert not any(x['account_id'] == str(accounts[0].pk)
                   for x in changed['assignments'])
    assert any(x['group_id'] == str(new_group.pk) and
               x['code'] == 'ACCOUNT_PROXY_NOT_READY'
               for x in changed['skipped']), changed['skipped']
    proxies[0].exit_ip = original_exit
    proxies[0].save()
    print('PROXY EXIT IP CHANGE: FAIL CLOSED: PASS')

    # Verify tenant scope in API; non-owners cannot read or create schedules.
    url = f'/api/v1/pipelines/{pipeline.pk}/schedules/'
    owned = authenticated(PipelineScheduleListCreateAPIView, 'GET', url, ctv, pipeline)
    assert owned.status_code == 200 and len(owned.data['data']) == 1
    forbidden = authenticated(PipelineScheduleListCreateAPIView, 'GET', url, outsider, pipeline)
    assert forbidden.status_code == 404
    print('CTV PIPELINE TENANCY: PASS')

    preview_url = f'/api/v1/pipelines/{pipeline.pk}/schedules/{schedule.pk}/preview/'
    public_request = authenticated(SchedulePreviewAPIView, 'GET', preview_url, None,
                                   pipeline, schedule=schedule)
    assert public_request.status_code in (401, 403)
    print('ANONYMOUS API ACCESS: BLOCKED')

    # Unknown/unverified pairs must not produce any Job, even with healthy proxy.
    stranger_group = FacebookGroup.objects.create(
        pipeline=pipeline, name='Unverified Group',
        group_url=f'https://www.facebook.com/groups/notverified{suffix}/',
    )
    changed = plan_schedule(schedule_id=schedule.pk, now=now + timedelta(days=3))
    assert any(row['group_id'] == str(stranger_group.pk) and
               row['code'] == 'NO_VERIFIED_ELIGIBLE_ACCOUNT'
               for row in changed['skipped'])
    print('UNVERIFIED / NONMEMBER ANONYMOUS: SKIPPED: PASS')

    # Self-reported group-unavailable flags require evidence at the model layer.
    group_health = GroupHealth(pipeline=pipeline, group=stranger_group,
                               state='unavailable', evidence_note='')
    from django.core.exceptions import ValidationError
    try:
        group_health.full_clean()
    except ValidationError:
        pass
    else:
        raise AssertionError('Unverified unavailable flag was accepted')
    print('GROUP UNAVAILABLE WITHOUT EVIDENCE: BLOCKED')

    transaction.set_rollback(True)

print('ALL TEST CHANGES: ROLLED BACK')
print('STEP 9.7 SCHEDULER: PASSED')
