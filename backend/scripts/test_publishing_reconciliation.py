"""Rollback-only ORM/API test. Never contacts Facebook, sockets, cookies or R2."""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import PublishingJob, PublishingAttempt
from modules.publishing.scheduler_models import PipelineSchedule, AccountGroupEligibility, GroupHealth
from modules.publishing.services.scheduler import plan_schedule
from modules.publishing.services.job_engine import claim_due_job, sweep_expired_jobs
from modules.publishing.services.reconciliation import (
    reconciliation_snapshot, held_subject_ids,
)
from modules.api.v1.publishing.reconciliation_views import PublishingReconciliationAPIView

User = get_user_model()
suffix = uuid.uuid4().hex[:10]
now = timezone.now()
factory = APIRequestFactory()
view = PublishingReconciliationAPIView.as_view()


def create_pipeline(label):
    ctv = User.objects.create_user(
        username=f'recon_{label}_{suffix}', password=f'Test#{suffix}Aa1!',
    )
    pipeline = Pipeline.objects.create(
        name=f'Reconciliation {label} {suffix}', ctv=ctv,
        status=Pipeline.Status.ACTIVE,
    )
    return pipeline, ctv


def get_api(pipeline, user=None, query=''):
    url = f'/api/v1/pipelines/{pipeline.pk}/publishing-reconciliation/{query}'
    req = factory.get(url)
    if user:
        force_authenticate(req, user=user)
    return view(req, pipeline_id=pipeline.pk)


with transaction.atomic():
    pipeline, ctv = create_pipeline('owned')
    foreign, outsider = create_pipeline('foreign')
    account = FacebookAccount.objects.create(
        pipeline=pipeline, label='Account A',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    )
    account2 = FacebookAccount.objects.create(
        pipeline=pipeline, label='Account B',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    )
    group1 = FacebookGroup.objects.create(
        pipeline=pipeline, name='Group uncertain',
        group_url=f'https://www.facebook.com/groups/recon{suffix}a/',
    )
    group2 = FacebookGroup.objects.create(
        pipeline=pipeline, name='Group pending',
        group_url=f'https://www.facebook.com/groups/recon{suffix}b/',
    )
    GroupHealth.objects.create(
        pipeline=pipeline, group=group1, state=GroupHealth.State.PAUSED,
        evidence_note='Mock manual pause',
    )
    proxy = ProxyEndpoint.objects.create(
        pipeline=pipeline, account=account,
        host='8.8.8.8', port=18080,
        protocol=ProxyEndpoint.Protocol.HTTP,
        health_status=ProxyEndpoint.HealthStatus.HEALTHY,
        is_enabled=True, exit_ip='8.8.8.8', last_checked_at=now,
    )
    ProxyEndpoint.objects.create(
        pipeline=pipeline, account=account2,
        host='1.1.1.1', port=18081,
        protocol=ProxyEndpoint.Protocol.HTTP,
        health_status=ProxyEndpoint.HealthStatus.HEALTHY,
        is_enabled=True, exit_ip='1.1.1.1', last_checked_at=now,
    )
    uncertain = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group1,
        request_key=f'uncertain-{suffix}', caption='Not verified',
        scheduled_at=now - timedelta(hours=1),
        next_run_at=now - timedelta(hours=1),
        state=PublishingJob.State.UNCERTAIN,
        error_code='UNVERIFIED_RESULT',
        claim_token='DO-NOT-EXPOSE-SECRET',
    )
    waiting = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group2,
        request_key=f'queued-{suffix}', caption='Queued for review',
        scheduled_at=now, next_run_at=now,
        state=PublishingJob.State.QUEUED,
    )
    foreign_account = FacebookAccount.objects.create(
        pipeline=foreign, label='Private foreign Account',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    )
    foreign_group = FacebookGroup.objects.create(
        pipeline=foreign, name='Private foreign Group',
        group_url=f'https://www.facebook.com/groups/recon{suffix}foreign/',
    )
    PublishingJob.objects.create(
        pipeline=foreign, facebook_account=foreign_account,
        facebook_group=foreign_group, request_key=f'foreign-{suffix}',
        caption='FOREIGN-SENSITIVE', scheduled_at=now,
        next_run_at=now, state=PublishingJob.State.UNCERTAIN,
    )

    with patch('socket.socket', side_effect=AssertionError('Network not allowed')):
        report = reconciliation_snapshot(pipeline_id=pipeline.pk, now=now)
        assert report['summary']['uncertain'] == 1
        assert report['summary']['review_required_jobs'] == 1
        assert report['summary']['held_accounts'] == 1
        assert report['summary']['held_groups'] == 1
        assert report['jobs'][0]['reason_code'] == 'UNVERIFIED_POST_RESULT'
        assert report['jobs'][0]['can_auto_retry'] is False
        assert report['summary']['group_health_alerts'] == 1
        assert 'DO-NOT-EXPOSE-SECRET' not in str(report)
        assert 'FOREIGN-SENSITIVE' not in str(report)
    print('READ-ONLY RECONCILIATION, TENANCY, NO NETWORK: PASS')

    held_account_ids, held_group_ids = held_subject_ids(pipeline_id=pipeline.pk)
    assert account.pk in held_account_ids and account2.pk not in held_account_ids
    assert group1.pk in held_group_ids and group2.pk not in held_group_ids
    assert claim_due_job(pipeline_id=pipeline.pk, worker_id='recon-test') is None
    waiting.refresh_from_db()
    assert waiting.state == PublishingJob.State.QUEUED
    print('CLAIM ENGINE REJECTS ACCOUNT WITH UNCERTAIN RESULT: PASS')

    schedule = PipelineSchedule.objects.create(
        pipeline=pipeline, name='Reconciliation scheduler', enabled=True,
        start_at=now - timedelta(minutes=2), next_run_at=now - timedelta(minutes=2),
        interval_minutes=1440, max_groups_per_run=5,
        caption_template='Test {group_name} {date}',
        require_anonymous=True, require_nonmember=True,
    )
    AccountGroupEligibility.objects.create(
        pipeline=pipeline, account=account, group=group2,
        state=AccountGroupEligibility.State.VERIFIED,
        can_post_anonymous=True, can_post_nonmember=True,
        evidence_note='Manually verified mock',
        verified_at=now - timedelta(minutes=3),
        expires_at=now + timedelta(days=7),
    )
    preview = plan_schedule(schedule_id=schedule.pk, now=now)
    assert preview['assigned_count'] == 0, preview
    assert any(row['group_id'] == str(group2.pk) and row['code'] in (
        'GROUP_HAS_PENDING_JOB', 'ACCOUNT_PROXY_NOT_READY',
    ) for row in preview['skipped'])
    # Group with no pending Job: verify the held Account cannot be assigned.
    group3 = FacebookGroup.objects.create(
        pipeline=pipeline, name='New target',
        group_url=f'https://www.facebook.com/groups/recon{suffix}new/',
    )
    AccountGroupEligibility.objects.create(
        pipeline=pipeline, account=account, group=group3,
        state=AccountGroupEligibility.State.VERIFIED,
        can_post_anonymous=True, can_post_nonmember=True,
        evidence_note='Manually verified mock',
        verified_at=now - timedelta(minutes=3),
        expires_at=now + timedelta(days=7),
    )
    preview = plan_schedule(schedule_id=schedule.pk, now=now)
    assert any(x['group_id'] == str(group3.pk) and
               x['code'] == 'ACCOUNT_PROXY_NOT_READY'
               for x in preview['skipped']), preview
    print('SCHEDULER DOES NOT ASSIGN HELD ACCOUNT: PASS')

    owned = get_api(pipeline, ctv)
    assert owned.status_code == 200, owned.data
    assert owned['Cache-Control'] == 'private, no-store'
    assert owned.data['data']['summary']['uncertain'] == 1
    assert 'claim_token' not in str(owned.data)
    assert 'DO-NOT-EXPOSE-SECRET' not in str(owned.data)
    wrong = get_api(pipeline, outsider)
    assert wrong.status_code == 404
    anonymous = get_api(pipeline)
    assert anonymous.status_code in (401, 403)
    badpage = get_api(pipeline, ctv, '?page_size=51')
    assert badpage.status_code == 400
    print('AUTHENTICATED/SCOPED READ-ONLY API: PASS')

    expired = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account2, facebook_group=group2,
        request_key=f'expired-{suffix}', caption='Lease expired',
        scheduled_at=now - timedelta(hours=2),
        next_run_at=now - timedelta(hours=2),
        state=PublishingJob.State.CLAIMED,
        attempt_count=1,
        lease_expires_at=now - timedelta(minutes=10),
        claim_token='EXP-SECRET', worker_id='expired-worker',
    )
    PublishingAttempt.objects.create(job=expired, number=1)
    before = reconciliation_snapshot(pipeline_id=pipeline.pk, now=now)
    assert before['summary']['review_required_jobs'] == 2
    assert expired.state == PublishingJob.State.CLAIMED
    changed = sweep_expired_jobs(pipeline_id=pipeline.pk)
    assert changed == 1
    expired.refresh_from_db()
    assert expired.state == PublishingJob.State.UNCERTAIN
    assert expired.claim_token == ''
    assert expired.lease_expires_at is None
    assert sweep_expired_jobs(pipeline_id=pipeline.pk) == 0
    print('EXPLICIT EXPIRED QUARANTINE, REPLAY SAFE: PASS')

    # Invalid published job must not be counted as verified and must hold Account.
    malformed = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account2, facebook_group=group3,
        request_key=f'malformed-{suffix}', caption='No post ID',
        scheduled_at=now, next_run_at=now,
        state=PublishingJob.State.PUBLISHED, external_post_id='',
    )
    final = reconciliation_snapshot(pipeline_id=pipeline.pk, now=now)
    assert final['summary']['published_verified'] == 0
    assert final['summary']['published_missing_id'] == 1
    assert any(x['job_id'] == str(malformed.pk) and x['reason_code'] == 'PUBLISHED_MISSING_POST_ID'
               for x in final['jobs'])
    assert final['summary']['held_accounts'] == 2
    print('PUBLISHED WITHOUT VERIFIED POST ID: FAIL CLOSED')

    transaction.set_rollback(True)

print('ALL RECONCILIATION TEST DATA ROLLED BACK')
print('STEP 9.7.6 RECONCILIATION: PASSED')
