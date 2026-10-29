"""Rollback-only regression for worker lease quarantine, access isolation and idempotency.

Never touches Facebook, R2 or actual VPS services.
"""
from datetime import timedelta
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.publishing.worker_reliability_views import WorkerGuardAPIView
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob, PublishingAttempt, MediaAllocation
from modules.publishing.services.job_engine import heartbeat_job, begin_dispatch, JobConflict
from modules.publishing.services.reconciliation import held_subject_ids
from modules.publishing.services.worker_reliability import (
    worker_guard_snapshot, quarantine_stale_leases, WorkerGuardError,
)
from modules.publishing.worker_models import WorkerLeaseEvent

User = get_user_model()
factory = APIRequestFactory()
now = timezone.now()
suffix = uuid.uuid4().hex[:10]


def fixture(pipeline, account, group, state, *, lease, media_state=None):
    alloc = None
    if media_state:
        alloc = MediaAllocation.objects.create(
            pipeline=pipeline, request_key=f'wguard-media-{uuid.uuid4().hex[:12]}',
            state=media_state, images_requested=1,
            lease_expires_at=now + timedelta(hours=1), policy_snapshot={'image_selection': 'in_order'},
        )
    job = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group,
        request_key=f'wguard-job-{uuid.uuid4().hex[:12]}',
        state=state, attempt_count=1, media_allocation=alloc,
        claim_token='test-token-not-real', worker_id='test-worker',
        lease_expires_at=lease, scheduled_at=now, next_run_at=now,
    )
    PublishingAttempt.objects.create(job=job, number=1, state=state,
                                      media_allocation=alloc)
    return job, alloc


def api(pipeline, user=None, query=''):
    req = factory.get(f'/api/v1/pipelines/{pipeline.pk}/worker-guard/{query}')
    if user is not None:
        force_authenticate(req, user=user)
    return WorkerGuardAPIView.as_view()(req, pipeline_id=pipeline.pk)


with transaction.atomic():
    ctv = User.objects.create_user(username=f'wg_{suffix}', password='Test!12345alpha')
    outsider = User.objects.create_user(username=f'wg_x_{suffix}', password='Test!12345alpha')
    own = Pipeline.objects.create(name='Worker Guard '+suffix, ctv=ctv, status='active')
    other = Pipeline.objects.create(name='Other Worker Guard '+suffix, ctv=outsider, status='active')
    acc = FacebookAccount.objects.create(pipeline=own, label='Mock A', connection_status='connected')
    grp = FacebookGroup.objects.create(pipeline=own, name='Mock G',
        group_url=f'https://www.facebook.com/groups/wg{suffix}/')
    other_acc = FacebookAccount.objects.create(pipeline=other, label='Mock Other', connection_status='connected')
    other_grp = FacebookGroup.objects.create(pipeline=other, name='Mock Other Group',
        group_url=f'https://www.facebook.com/groups/wgx{suffix}/')
    a, _ = fixture(own, acc, grp, 'claimed', lease=now-timedelta(minutes=5))
    b, media_b = fixture(own, acc, grp, 'ready', lease=now-timedelta(minutes=10), media_state='reserved')
    c, media_c = fixture(own, acc, grp, 'dispatching', lease=now+timedelta(minutes=10), media_state='uncertain')
    foreign, _ = fixture(other, other_acc, other_grp, 'claimed', lease=now-timedelta(minutes=10))
    with patch('socket.socket', side_effect=AssertionError('Unexpected network')):
        snap = worker_guard_snapshot(pipeline_id=own.pk, limit=1, now=now)
        assert snap['summary']['expired_or_missing_lease'] == 2
        assert snap['truncated'] is True and len(snap['items']) == 1
        assert snap['read_only'] and not snap['auto_retry_enabled']
        assert not WorkerLeaseEvent.objects.filter(pipeline=own).exists()
        assert PublishingJob.objects.get(pk=a.pk).state == 'claimed'
        assert api(own, ctv).status_code == 200
        assert api(own, outsider).status_code == 404
        assert api(other, ctv).status_code == 404
        assert api(own).status_code in (401, 403)
        assert api(own, ctv, '?limit=0').status_code == 400
        assert api(own, ctv, '?limit=51').status_code == 400
        try:
            worker_guard_snapshot(pipeline_id=uuid.uuid4())
        except WorkerGuardError:
            pass
        else:
            raise AssertionError('Missing Pipeline accepted')
        print('READ ONLY / TENANT ISOLATION / LIMIT / NO NETWORK: PASS')

        part = quarantine_stale_leases(pipeline_id=own.pk, limit=1, now=now)
        assert part['quarantined_count'] == 1 and not part['complete']
        done = quarantine_stale_leases(pipeline_id=own.pk, limit=2, now=now)
        assert done['quarantined_count'] == 1 and done['complete']
        again = quarantine_stale_leases(pipeline_id=own.pk, limit=10, now=now)
        assert again['quarantined_count'] == 0
        assert WorkerLeaseEvent.objects.filter(pipeline=own).count() == 2
        assert WorkerLeaseEvent.objects.filter(pipeline=other).count() == 0
        for item in (a, b):
            item.refresh_from_db()
            assert item.state == 'uncertain' and item.worker_id == '' and item.claim_token == ''
            assert item.lease_expires_at is None and item.error_code == 'WORKER_LEASE_EXPIRED'
            assert PublishingAttempt.objects.get(job=item).state == 'uncertain'
        media_b.refresh_from_db()
        media_c.refresh_from_db()
        c.refresh_from_db()
        foreign.refresh_from_db()
        assert media_b.state == 'uncertain' and media_c.state == 'uncertain'
        assert c.state == 'dispatching' and foreign.state == 'claimed'
        assert acc.pk in held_subject_ids(pipeline_id=own.pk)[0]
        assert grp.pk in held_subject_ids(pipeline_id=own.pk)[1]
        print('EXPLICIT QUARANTINE / MEDIA HOLD / IDEMPOTENT / NO RETRY: PASS')

        for operation in (
            lambda: heartbeat_job(pipeline_id=own.pk, job_id=a.pk,
                                  claim_token='test-token-not-real'),
            lambda: begin_dispatch(pipeline_id=own.pk, job_id=b.pk,
                                   claim_token='test-token-not-real'),
        ):
            try:
                operation()
            except JobConflict:
                pass
            else:
                raise AssertionError('Old worker token was accepted after quarantine')
        assert not PublishingJob.objects.filter(pipeline=own, state='published').exists()
        print('OLD CLAIM/HEARTBEAT/DISPATCH DENIED: PASS')
    transaction.set_rollback(True)

print('ROLLBACK-ONLY WORKER RELIABILITY: PASS')
