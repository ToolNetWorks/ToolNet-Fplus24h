"""Rollback-only integration test. Never accesses Facebook or R2."""
import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.albums.models import Album, AlbumImage
from modules.publishing.models import (
    PublishingJob, PublishingAttempt, PipelineMediaPolicy, PipelineAlbumSource,
    MediaAllocation,
)
from modules.publishing.services.job_engine import (
    JobConflict, JobEngineError, enqueue_job, claim_due_job,
    prepare_job_media, heartbeat_job, begin_dispatch, confirm_published,
    flag_uncertain, fail_before_dispatch, cancel_queued_job, sweep_expired_jobs,
)

suffix=uuid.uuid4().hex[:10]
User=get_user_model()


def setup(label):
    user=User.objects.create_user(username=f'pubjob_{label}_{suffix}', password='Test!12345x')
    pipeline=Pipeline.objects.create(name=f'PubJob Test {label} {suffix}', ctv=user, status='active')
    account=FacebookAccount.objects.create(pipeline=pipeline, label=f'Account {label}', connection_status='connected')
    group=FacebookGroup.objects.create(pipeline=pipeline, name=f'Group {label}',
                                      group_url=f'https://www.facebook.com/groups/pubjob{label}{suffix}/')
    album=Album.objects.create(pipeline=pipeline, name=f'Album {label}')
    img_id=uuid.uuid4()
    AlbumImage.objects.create(
        id=img_id, album=album, original_filename='test.webp',
        storage_key=f'pipeline-albums/{pipeline.pk}/{album.pk}/{img_id}.webp',
        mime_type='image/webp', file_size=1024, width=20, height=20,
        sha256='a'*64, position=1, upload_status='ready',
    )
    PipelineMediaPolicy.objects.create(pipeline=pipeline, is_enabled=True, images_per_post=1)
    PipelineAlbumSource.objects.create(pipeline=pipeline, album=album, position=1)
    return pipeline, account, group


with transaction.atomic():
    pipeline, account, group=setup('a')
    other, foreign_account, foreign_group=setup('b')
    job=enqueue_job(pipeline_id=pipeline.pk, account_id=account.pk, group_id=group.pk,
                    request_key=f'job-{suffix}', caption='Test draft')
    assert job['state']=='queued'
    assert enqueue_job(pipeline_id=pipeline.pk, account_id=account.pk, group_id=group.pk,
                       request_key=f'job-{suffix}', caption='Test draft')['id']==job['id']
    print('ENQUEUE IDEMPOTENT: PASS')
    try:
        enqueue_job(pipeline_id=pipeline.pk, account_id=foreign_account.pk, group_id=group.pk,
                    request_key=f'foreign-{suffix}', caption='Test draft')
    except JobEngineError: print('CROSS PIPELINE ACCOUNT: BLOCKED')
    else: raise AssertionError('Tenant breach')
    try:
        enqueue_job(pipeline_id=pipeline.pk, account_id=account.pk, group_id=foreign_group.pk,
                    request_key=f'foreigngroup-{suffix}')
    except JobEngineError: print('CROSS PIPELINE GROUP: BLOCKED')
    else: raise AssertionError('Tenant breach')

    delayed=enqueue_job(pipeline_id=pipeline.pk, account_id=account.pk, group_id=group.pk,
        request_key=f'later-{suffix}', scheduled_at=timezone.now()+timedelta(days=1))
    claim=claim_due_job(pipeline_id=pipeline.pk, worker_id='worker-test')
    assert claim and claim['job']['id']==job['id']
    assert claim_due_job(pipeline_id=pipeline.pk, worker_id='worker-test') is None
    print('SCHEDULE + SINGLE CLAIM: PASS')
    token=claim['claim_token']
    assert heartbeat_job(pipeline_id=pipeline.pk, job_id=job['id'], claim_token=token)['state']=='claimed'
    ready=prepare_job_media(pipeline_id=pipeline.pk, job_id=job['id'], claim_token=token)
    assert ready['state']=='ready' and ready['media_allocation_id']
    attempt=PublishingAttempt.objects.get(job_id=job['id'], number=1)
    assert attempt.media_allocation_id==uuid.UUID(ready['media_allocation_id'])
    assert attempt.media_allocation.state=='reserved'
    print('RESERVE + LINK ATTEMPT: PASS')
    try:
        begin_dispatch(pipeline_id=pipeline.pk, job_id=job['id'], claim_token='wrong')
    except JobConflict: print('INVALID CLAIM TOKEN: BLOCKED')
    else: raise AssertionError('Wrong claim token accepted')
    dispatch=begin_dispatch(pipeline_id=pipeline.pk, job_id=job['id'], claim_token=token)
    assert dispatch['state']=='dispatching'
    attempt.refresh_from_db()
    assert attempt.media_allocation.state=='uncertain'
    print('DISPATCH FAIL-CLOSED BOUNDARY: PASS')
    try:
        fail_before_dispatch(pipeline_id=pipeline.pk, job_id=job['id'], claim_token=token)
    except JobConflict: print('POST-DISPATCH RETRY: BLOCKED')
    else: raise AssertionError('Released after dispatch')
    flag_uncertain(pipeline_id=pipeline.pk, job_id=job['id'])
    assert confirm_published(pipeline_id=pipeline.pk, job_id=job['id'], external_post_id='post_123')['state']=='published'
    attempt.refresh_from_db()
    assert attempt.media_allocation.state=='consumed'
    print('VERIFIED PUBLISH + CONSUMED: PASS')

    # Add one new READY image because no-repeat mode already consumed the first.
    album=Album.objects.filter(pipeline=pipeline).first()
    second_id=uuid.uuid4()
    AlbumImage.objects.create(
        id=second_id, album=album, original_filename='new.webp',
        storage_key=f'pipeline-albums/{pipeline.pk}/{album.pk}/{second_id}.webp',
        mime_type='image/webp', file_size=1024, width=20, height=20,
        sha256='b'*64, position=2, upload_status='ready',
    )
    # A second scheduled Job can be retried only BEFORE dispatch; the old
    # media allocation is released, a new permanent idempotency key is used.
    future=PublishingJob.objects.get(pk=delayed['id'])
    future.next_run_at=timezone.now()-timedelta(seconds=1)
    future.save()
    claim2=claim_due_job(pipeline_id=pipeline.pk, worker_id='worker-test')
    assert claim2['job']['id']==delayed['id']
    prepared2=prepare_job_media(pipeline_id=pipeline.pk, job_id=delayed['id'], claim_token=claim2['claim_token'])
    old_alloc_id=prepared2['media_allocation_id']
    assert old_alloc_id
    fail=fail_before_dispatch(pipeline_id=pipeline.pk, job_id=delayed['id'],
        claim_token=claim2['claim_token'], retry_delay_seconds=0)
    assert MediaAllocation.objects.get(pk=old_alloc_id).state == 'released'
    assert fail['state']=='queued' and fail['attempt_count']==1
    claim3=claim_due_job(pipeline_id=pipeline.pk, worker_id='worker-test')
    assert claim3['job']['attempt_count']==2
    prepared3=prepare_job_media(pipeline_id=pipeline.pk, job_id=delayed['id'], claim_token=claim3['claim_token'])
    assert prepared3['media_allocation_id'] != old_alloc_id
    assert PublishingAttempt.objects.filter(job_id=delayed['id']).count()==2
    print('SAFE PREFLIGHT RETRY + ATTEMPT HISTORY: PASS')
    exp=PublishingJob.objects.get(pk=delayed['id'])
    exp.lease_expires_at=timezone.now()-timedelta(seconds=1)
    exp.save()
    assert sweep_expired_jobs(pipeline_id=pipeline.pk)>=1
    exp.refresh_from_db()
    assert exp.state=='uncertain'
    assert claim_due_job(pipeline_id=pipeline.pk, worker_id='worker-test') is None
    print('EXPIRED CLAIM QUARANTINED: PASS')

    queued=enqueue_job(pipeline_id=pipeline.pk, account_id=account.pk, group_id=group.pk,
        request_key=f'cancel-{suffix}')
    assert cancel_queued_job(pipeline_id=pipeline.pk, job_id=queued['id'])['state']=='cancelled'
    print('QUEUED CANCELLATION: PASS')
    transaction.set_rollback(True)

print('DATABASE CHANGES: ROLLED BACK')
print('PUBLISHING JOB ENGINE: PASSED')
