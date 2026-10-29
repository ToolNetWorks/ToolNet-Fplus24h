"""Rollback-only Scheduler Tick integration checks on the configured Neon DB.

No network access, no Facebook publishing, no R2. Uses transactions to remove
all fixtures and audits. This is NOT a simultaneous multi-process load test.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import (
    PipelineSchedule, AccountGroupEligibility, ScheduledBatch,
)
from modules.publishing.scheduler_tick_models import SchedulerTickAudit
from modules.publishing.services.scheduler import ScheduleError
from modules.publishing.services.scheduler_tick import (
    tick_due_schedules, pipeline_tick_status,
)
from modules.api.v1.publishing.scheduler_tick_views import SchedulerTickStatusAPIView

suffix = uuid.uuid4().hex[:10]
now = timezone.now()
User = get_user_model()


def new_pipeline(tag):
    user = User.objects.create_user(
        username=f'tick_{tag}_{suffix}',
        password=f'Test#{suffix}Aa1!',
    )
    pipeline = Pipeline.objects.create(
        name=f'Scheduler Tick {tag} {suffix}', ctv=user,
        status=Pipeline.Status.ACTIVE,
    )
    return pipeline, user


def schedule_for(pipeline, name, *, enabled=True):
    start = now - timedelta(minutes=1)
    return PipelineSchedule.objects.create(
        pipeline=pipeline, name=f'{name} {suffix}', enabled=enabled,
        start_at=start, next_run_at=start,
        interval_minutes=60, max_groups_per_run=5,
        timezone_name='Asia/Ho_Chi_Minh',
        caption_template='Thông báo nhóm {group_name} - {date}',
        require_anonymous=True, require_nonmember=True,
    )


with transaction.atomic():
    pipeline, ctv = new_pipeline('a')
    other, other_user = new_pipeline('b')
    account = FacebookAccount.objects.create(
        pipeline=pipeline, label='Tick Test Account',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    )
    ProxyEndpoint.objects.create(
        pipeline=pipeline, account=account, protocol='http',
        host='8.8.8.8', port=9876, is_enabled=True,
        health_status=ProxyEndpoint.HealthStatus.HEALTHY,
        exit_ip='8.8.8.8', last_checked_at=now,
    )
    for i in range(2):
        group = FacebookGroup.objects.create(
            pipeline=pipeline, name=f'Tick Group {i}',
            group_url=f'https://www.facebook.com/groups/tick{suffix}{i}/',
        )
        AccountGroupEligibility.objects.create(
            pipeline=pipeline, account=account, group=group,
            state=AccountGroupEligibility.State.VERIFIED,
            can_post_anonymous=True, can_post_nonmember=True,
            verified_at=now - timedelta(minutes=2),
            expires_at=now + timedelta(days=6),
            evidence_note='Human-reviewed test fixture only.',
        )
    sched = schedule_for(pipeline, 'Hourly')
    disabled = schedule_for(pipeline, 'Disabled', enabled=False)

    preview = tick_due_schedules(
        enqueue=False, pipeline_id=pipeline.pk,
        schedule_id=sched.pk, now=now, worker_id='worker-preview',
    )
    assert preview['scanned_count'] == 1
    assert preview['preview_count'] == 1
    assert preview['items'][0]['assigned_count'] == 2
    assert not SchedulerTickAudit.objects.exists()
    assert not PublishingJob.objects.exists()
    assert not ScheduledBatch.objects.exists()
    print('DEFAULT PREVIEW: NO DATABASE WRITES')

    committed = tick_due_schedules(
        enqueue=True, pipeline_id=pipeline.pk,
        schedule_id=sched.pk, now=now, worker_id='worker-a',
    )
    assert committed['queued_count'] == 1, committed
    assert committed['items'][0]['assigned_count'] == 2
    assert PublishingJob.objects.filter(pipeline=pipeline, state='queued').count() == 2
    assert ScheduledBatch.objects.filter(schedule=sched).count() == 1
    audit = SchedulerTickAudit.objects.get(schedule=sched)
    assert audit.outcome == SchedulerTickAudit.Outcome.QUEUED
    assert audit.assigned_count == 2 and audit.attempt_count == 1
    assert audit.batch_id is not None
    sched.refresh_from_db()
    assert sched.next_run_at > now
    print('ENQUEUE ONLY: 2 QUEUED JOBS + AUDIT: PASS')

    again = tick_due_schedules(
        enqueue=True, pipeline_id=pipeline.pk,
        schedule_id=sched.pk, now=now, worker_id='worker-b',
    )
    assert again['scanned_count'] == 0
    assert PublishingJob.objects.filter(pipeline=pipeline).count() == 2
    assert SchedulerTickAudit.objects.filter(schedule=sched).count() == 1
    print('SECOND WORKER: SAME SLOT NOT RE-ENQUEUED: PASS')

    # Recover a stale cursor pointing to an already committed Batch.
    old_slot = sched.start_at
    PipelineSchedule.objects.filter(pk=sched.pk).update(next_run_at=old_slot)
    replay = tick_due_schedules(
        enqueue=True, pipeline_id=pipeline.pk,
        schedule_id=sched.pk, now=now, worker_id='worker-b',
    )
    assert replay['replayed_count'] == 1, replay
    sched.refresh_from_db()
    assert sched.next_run_at > now, 'Stale replay cursor not advanced'
    assert PublishingJob.objects.filter(pipeline=pipeline).count() == 2
    audit.refresh_from_db()
    assert audit.attempt_count == 2
    assert audit.outcome == SchedulerTickAudit.Outcome.REPLAYED
    print('STALE CURSOR REPLAY: ADVANCES WITHOUT DUPLICATE JOB: PASS')

    not_enabled = tick_due_schedules(
        enqueue=True, pipeline_id=pipeline.pk,
        schedule_id=disabled.pk, now=now,
    )
    assert not_enabled['scanned_count'] == 0
    print('DISABLED SCHEDULE: SKIPPED')

    broken = schedule_for(pipeline, 'Broken')
    with patch(
        'modules.publishing.services.scheduler_tick.plan_schedule',
        side_effect=ScheduleError('Intentional test error'),
    ):
        failed = tick_due_schedules(
            enqueue=True, pipeline_id=pipeline.pk,
            schedule_id=broken.pk, now=now,
        )
    assert failed['error_count'] == 1
    assert failed['items'][0]['error_code'] == 'SCHEDULE_ERROR'
    bad_audit = SchedulerTickAudit.objects.get(schedule=broken)
    assert bad_audit.outcome == SchedulerTickAudit.Outcome.ERROR
    assert bad_audit.error_code == 'SCHEDULE_ERROR'
    print('FAILURE AUDIT WITH SANITIZED CODE: PASS')

    backoff = tick_due_schedules(
        enqueue=True, pipeline_id=pipeline.pk,
        schedule_id=broken.pk, now=now,
    )
    assert backoff['scanned_count'] == 0
    print('ERROR BACKOFF: NO HOT RETRY LOOP: PASS')

    # Use a changed injected wall clock for retry; recent_error uses its timestamp.
    # The test models the elapsed interval by moving the audit updated_at.
    SchedulerTickAudit.objects.filter(pk=bad_audit.pk).update(
        updated_at=now - timedelta(minutes=6),
    )
    recovered = tick_due_schedules(
        enqueue=True, pipeline_id=pipeline.pk,
        schedule_id=broken.pk, now=now,
    )
    assert recovered['queued_count'] == 1, recovered
    bad_audit.refresh_from_db()
    assert bad_audit.outcome == SchedulerTickAudit.Outcome.QUEUED
    assert bad_audit.attempt_count == 2
    assert SchedulerTickAudit.objects.filter(schedule=broken).count() == 1
    print('ERROR RECOVERY: SAME AUDIT ROW REUSED: PASS')

    result = pipeline_tick_status(pipeline_id=pipeline.pk, now=now)
    assert result['schedule_count'] == 3
    assert result['active_schedule_count'] == 2
    assert len(result['schedules']) == 3
    assert 'claim_token' not in str(result)
    assert result['due_schedule_count'] == 0
    print('PIPELINE TICK STATUS SUMMARY: PASS')

    request_factory = APIRequestFactory()
    url = f'/api/v1/pipelines/{pipeline.pk}/scheduler-ticks/status/'
    view = SchedulerTickStatusAPIView.as_view()
    own = request_factory.get(url)
    force_authenticate(own, user=ctv)
    response = view(own, pipeline_id=pipeline.pk)
    assert response.status_code == 200
    assert response.data['data']['schedule_count'] == 3
    print('CTV AUTHENTICATED STATUS API: PASS')

    forbidden = request_factory.get(url)
    force_authenticate(forbidden, user=other_user)
    response = view(forbidden, pipeline_id=pipeline.pk)
    assert response.status_code == 404
    print('FOREIGN CTV: NO CROSS-PIPELINE ACCESS: PASS')

    anonymous = request_factory.get(url)
    response = view(anonymous, pipeline_id=pipeline.pk)
    assert response.status_code in (401, 403)
    print('ANONYMOUS STATUS API: BLOCKED')

    foreign_audit = SchedulerTickAudit(
        pipeline=other, schedule=sched, slot_at=sched.start_at,
        outcome=SchedulerTickAudit.Outcome.ERROR,
        worker_id='worker-a',
    )
    try:
        foreign_audit.full_clean()
    except ValidationError:
        print('CROSS-PIPELINE AUDIT RECORD: BLOCKED')
    else:
        raise AssertionError('Foreign audit record accepted')

    transaction.set_rollback(True)

print('ALL TEST DATA: ROLLED BACK')
print('STEP 9.7.3 SCHEDULER TICK: PASSED')
