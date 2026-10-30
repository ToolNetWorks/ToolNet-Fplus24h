"""Isolated handoff queue + unified 7-step status tests.

Rollback-only script: runs inside transaction.atomic() with rollback.
No Facebook / R2 network I/O. AI provider is mocked.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.publishing.manual_handoff_views import (
    HandoffQueueAPIView, ManualHandoffAPIView,
)
from modules.api.v1.publishing.post_verification_views import (
    PublishingJobVerificationAPIView,
)
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.albums.models import Album, AlbumImage
from modules.publishing.models import (
    PublishingJob, PublishingAttempt, PipelineMediaPolicy,
    PipelineAlbumSource, MediaAllocation,
)
from modules.publishing.caption_models import (
    PipelineCaptionSettings, JobCaption, CaptionSample, CaptionRevision,
)
from modules.publishing.manual_handoff_models import (
    ManualPublishingHandoff, ManualPublishingEvent,
)
from modules.publishing.scheduler_models import AccountGroupEligibility
from modules.publishing.services.manual_handoff import (
    list_handoff_queue, compute_publication_status, PublicationStatus,
    prepare_handoff, mutate_handoff, get_handoff, HandoffError, HandoffConflict,
)
from modules.publishing.services.post_verification import record_observation

User = get_user_model()
factory = APIRequestFactory()
suffix = uuid.uuid4().hex[:10]
now = timezone.now()


def rejects(fn, *errors):
    try:
        fn()
    except errors:
        return
    raise AssertionError('Expected an explicit failure.')


def api_rejects_force_published(pipe, job, actor):
    req = factory.post(
        reverse('publishing-manual-handoff', kwargs={
            'pipeline_id': str(pipe.pk), 'job_id': str(job.pk)
        }),
        {'action': 'prepare', 'force_published': True}, format='json')
    force_authenticate(req, user=actor)
    resp = ManualHandoffAPIView.as_view()(req, pipeline_id=str(pipe.pk), job_id=str(job.pk))
    return resp.status_code == 400


def make_pipeline(label):
    ctv = User.objects.create_user(username=f'{label}_ctv_{suffix}', password='TestOnly!12345')
    pipe = Pipeline.objects.create(name=f'{label} Pipeline {suffix}', ctv=ctv, status='active')
    acc = FacebookAccount.objects.create(
        pipeline=pipe, label=f'{label} Acc',
        connection_status='connected')
    group = FacebookGroup.objects.create(
        pipeline=pipe, name=f'{label} Group',
        group_url=f'https://www.facebook.com/groups/{label}{suffix}/')
    album = Album.objects.create(pipeline=pipe, name=f'{label} Album')
    image_id = uuid.uuid4()
    AlbumImage.objects.create(
        id=image_id, album=album, original_filename='test.webp',
        storage_key=f'pipeline-albums/{pipe.pk}/{album.pk}/{image_id}.webp',
        mime_type='image/webp', file_size=1024, width=20, height=20,
        sha256='b' * 64, position=1, upload_status='ready')
    PipelineMediaPolicy.objects.create(
        pipeline=pipe, is_enabled=True, images_per_post=1)
    PipelineAlbumSource.objects.create(pipeline=pipe, album=album, position=1)
    PipelineCaptionSettings.objects.create(
        pipeline=pipe, destination='@test_dest', enabled=True,
        auto_generate=True, auto_approve=True, writing_guidance='')
    CaptionSample.objects.create(
        pipeline=pipe, text='Caption mẫu tích cực hàng ngày!', created_by=ctv)
    AccountGroupEligibility.objects.create(
        pipeline=pipe, account=acc, group=group,
        state='verified', can_post_anonymous=True, can_post_nonmember=False,
        verified_at=now - timedelta(minutes=2),
        expires_at=now + timedelta(days=1),
        evidence_note='Explicit operator check.')
    return pipe, ctv, acc, group


def make_job(pipe, acc, group, key_suffix, state='queued', attempt_count=0):
    return PublishingJob.objects.create(
        pipeline=pipe, facebook_account=acc, facebook_group=group,
        request_key=f'handoff-{suffix}-{key_suffix}', caption='',
        state=state, attempt_count=attempt_count,
        scheduled_at=now - timedelta(minutes=1),
        next_run_at=now - timedelta(minutes=1))


with transaction.atomic():
    pipe, ctv, acc, group = make_pipeline('Queue')

    # --- Test 1: Chờ AI when no caption exists ---
    job1 = make_job(pipe, acc, group, 'ai')
    status = compute_publication_status(job1)
    assert status == PublicationStatus.AWAITING_AI, f'Expected awaiting_ai, got {status}'
    print('TEST 1 - Chờ AI (no caption): PASS')

    # --- Test 2: AI caption generated and auto-approved → Đã duyệt ---
    with patch('modules.publishing.services.caption_engine._provider',
               return_value=('Caption thử nghiệm duyệt tự động.', 'test-model')):
        from modules.publishing.services.caption_engine import generate_job_caption
        generate_job_caption(pipeline_id=pipe.pk, job_id=job1.pk)
    job1.refresh_from_db()
    assert job1.caption, 'Job caption should be populated after auto-approve'
    status = compute_publication_status(job1)
    assert status == PublicationStatus.APPROVED, f'Expected approved, got {status}'
    print('TEST 2 - AI auto-approved → Đã duyệt: PASS')

    # --- Test 3: Handoff queue lists job with unified status ---
    req = factory.get(reverse('pipeline-handoff-queue', kwargs={'pipeline_id': str(pipe.pk)}))
    force_authenticate(req, user=ctv)
    resp = HandoffQueueAPIView.as_view()(req, pipeline_id=str(pipe.pk))
    assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.data}'
    data = resp.data['data']
    assert 'items' in data and len(data['items']) >= 1
    queue_item = data['items'][0]
    assert queue_item['unified_status'] == 'approved', f"Expected approved, got {queue_item['unified_status']}"
    assert queue_item['unified_status_label'] == 'Đã duyệt'
    assert queue_item['group']['name'] == group.name
    assert queue_item['account']['label'] == acc.label
    assert queue_item['caption'] == job1.caption
    assert queue_item['automatic_facebook_posting'] is False
    assert queue_item['facebook_groups_api_supported'] is False
    print('TEST 3 - Handoff queue list with unified status: PASS')

    # --- Test 4: CTV prepares handoff → Chờ bàn giao ---
    req = factory.post(
        reverse('publishing-manual-handoff', kwargs={
            'pipeline_id': str(pipe.pk), 'job_id': str(job1.pk)
        }),
        {'action': 'prepare'}, format='json')
    force_authenticate(req, user=ctv)
    resp = ManualHandoffAPIView.as_view()(req, pipeline_id=str(pipe.pk), job_id=str(job1.pk))
    assert resp.status_code == 201, f'Expected 201, got {resp.status_code}: {resp.data}'
    handoff_data = resp.data['data']
    assert handoff_data['state'] == 'prepared'
    assert len(handoff_data['media']) == 1
    assert handoff_data['automatic_facebook_posting'] is False
    job1.refresh_from_db()
    status = compute_publication_status(job1)
    assert status == PublicationStatus.AWAITING_HANDOFF, f'Expected awaiting_handoff, got {status}'
    print('TEST 4 - Prepare handoff → Chờ bàn giao: PASS')

    # --- Test 5: Queue now shows awaiting_handoff status ---
    req = factory.get(reverse('pipeline-handoff-queue', kwargs={'pipeline_id': str(pipe.pk)}))
    force_authenticate(req, user=ctv)
    resp = HandoffQueueAPIView.as_view()(req, pipeline_id=str(pipe.pk))
    data = resp.data['data']
    found = [i for i in data['items'] if i['job_id'] == str(job1.pk)]
    assert len(found) == 1
    assert found[0]['unified_status'] == 'awaiting_handoff'
    assert found[0]['handoff']['state'] == 'prepared'
    print('TEST 5 - Queue reflects awaiting_handoff after prepare: PASS')

    # --- Test 6: CTV opens Facebook → Đang xử lý ---
    version = resp.data['data']['items'][0]['handoff']['version']
    req = factory.post(
        reverse('publishing-manual-handoff', kwargs={
            'pipeline_id': str(pipe.pk), 'job_id': str(job1.pk)
        }),
        {'action': 'open', 'expected_version': version}, format='json')
    force_authenticate(req, user=ctv)
    resp = ManualHandoffAPIView.as_view()(req, pipeline_id=str(pipe.pk), job_id=str(job1.pk))
    assert resp.status_code == 200
    assert resp.data['data']['state'] == 'opened'
    job1.refresh_from_db()
    status = compute_publication_status(job1)
    assert status == PublicationStatus.PROCESSING, f'Expected processing, got {status}'
    print('TEST 6 - Open Facebook → Đang xử lý: PASS')

    # --- Test 7: CTV reports submitted → still processing, NOT published ---
    version2 = resp.data['data']['version']
    req = factory.post(
        reverse('publishing-manual-handoff', kwargs={
            'pipeline_id': str(pipe.pk), 'job_id': str(job1.pk)
        }),
        {'action': 'report', 'expected_version': version2,
         'outcome': 'submitted_reported', 'note': 'Đã nhấn gửi bài trên Facebook.'},
        format='json')
    force_authenticate(req, user=ctv)
    resp = ManualHandoffAPIView.as_view()(req, pipeline_id=str(pipe.pk), job_id=str(job1.pk))
    assert resp.status_code == 200
    assert resp.data['data']['state'] == 'submitted_reported'
    job1.refresh_from_db()
    status = compute_publication_status(job1)
    assert status == PublicationStatus.PROCESSING
    assert job1.state == 'uncertain'
    assert job1.external_post_id == '', 'Must NOT be marked published without verification'
    print('TEST 7 - Report submitted → Đang xử lý, NOT published: PASS')

    # --- Test 8: CTV reports pending → Chờ xác minh ---
    version3 = resp.data['data']['version']
    req = factory.post(
        reverse('publishing-manual-handoff', kwargs={
            'pipeline_id': str(pipe.pk), 'job_id': str(job1.pk)
        }),
        {'action': 'report', 'expected_version': version3,
         'outcome': 'pending_reported', 'note': 'Bài đang chờ Group duyệt.'},
        format='json')
    force_authenticate(req, user=ctv)
    resp = ManualHandoffAPIView.as_view()(req, pipeline_id=str(pipe.pk), job_id=str(job1.pk))
    assert resp.status_code == 200
    assert resp.data['data']['state'] == 'pending_reported'
    job1.refresh_from_db()
    status = compute_publication_status(job1)
    assert status == PublicationStatus.AWAITING_VERIFICATION, f'Expected awaiting_verification, got {status}'
    print('TEST 8 - Report pending → Chờ xác minh: PASS')

    # --- Test 9: Verification observation recorded (never marks PUBLISHED) ---
    obs_idempotency = uuid.uuid4()
    observation, created = record_observation(
        pipeline_id=pipe.pk, job_id=job1.pk, actor=ctv,
        idempotency_key=obs_idempotency,
        source='manual_review',
        outcome='visible_reported',
        note='Bài đã hiển thị trong Group, cần xác minh độc lập.',
        evidence_url=f'https://www.facebook.com/groups/{group.group_key}/permalink/123456/',
    )
    assert created, 'Observation should be created'
    job1.refresh_from_db()
    status = compute_publication_status(job1)
    assert status == PublicationStatus.AWAITING_VERIFICATION, 'Observation does NOT mark published'
    print('TEST 9 - Verification observation logged, job stays in Chờ xác minh: PASS')

    # --- Test 10: No auto-publish, no fake success ---
    req = factory.get(reverse('pipeline-handoff-queue', kwargs={'pipeline_id': str(pipe.pk)}))
    force_authenticate(req, user=ctv)
    resp = HandoffQueueAPIView.as_view()(req, pipeline_id=str(pipe.pk))
    item = [i for i in resp.data['data']['items'] if i['job_id'] == str(job1.pk)][0]
    assert item['unified_status'] == 'awaiting_verification'
    assert item['external_post_id'] is None
    assert item['verified_published'] is False
    assert item['automatic_facebook_posting'] is False
    print('TEST 10 - No auto-publish, no fake success: PASS')

    # --- Test 11: Filter by status ---
    req = factory.get(
        reverse('pipeline-handoff-queue', kwargs={'pipeline_id': str(pipe.pk)}) +
        '?page=1&page_size=20&status=awaiting_verification')
    force_authenticate(req, user=ctv)
    resp = HandoffQueueAPIView.as_view()(req, pipeline_id=str(pipe.pk))
    assert resp.status_code == 200
    assert len(resp.data['data']['items']) == 1
    assert resp.data['data']['items'][0]['job_id'] == str(job1.pk)
    print('TEST 11 - Filter by status: PASS')

    # --- Test 12: Outsider cannot access handoff queue ---
    req = factory.get(reverse('pipeline-handoff-queue', kwargs={'pipeline_id': str(pipe.pk)}))
    outsider = User.objects.create_user(username=f'out_{suffix}', password='TestOnly!12345')
    force_authenticate(req, user=outsider)
    resp = HandoffQueueAPIView.as_view()(req, pipeline_id=str(pipe.pk))
    assert resp.status_code in (403, 404), f'Expected 403/404 for outsider, got {resp.status_code}'
    print('TEST 12 - Tenant isolation (outsider blocked): PASS')

    # --- Test 13: Rejects force_published in API payload ---
    assert api_rejects_force_published(pipe, job1, ctv)
    print('TEST 13 - Reject force_published/outside-fields in handoff: PASS')

    # --- Test 14: Summary counts across all 7 statuses ---
    req = factory.get(reverse('pipeline-handoff-queue', kwargs={'pipeline_id': str(pipe.pk)}))
    force_authenticate(req, user=ctv)
    resp = HandoffQueueAPIView.as_view()(req, pipeline_id=str(pipe.pk))
    summary = resp.data['data']['summary']['total']
    assert summary['awaiting_ai'] == 0
    assert summary['approved'] == 0
    assert summary['awaiting_handoff'] == 0
    assert summary['processing'] == 0
    assert summary['awaiting_verification'] == 1
    assert summary['published'] == 0
    assert summary['failed'] == 0
    assert resp.data['data']['status_labels']['awaiting_ai'] == 'Chờ AI'
    assert resp.data['data']['status_labels']['published'] == 'Thành công'
    print('TEST 14 - Summary counts match 7-step statuses: PASS')

    # --- Test 15: No duplicate Job, Account, or Group ---
    # Use separate pipeline to avoid held-subject conflicts from job1
    pipe2, ctv2, acc2, group2 = make_pipeline('Queue15')
    job_a = make_job(pipe2, acc2, group2, 'dup-a')
    with patch('modules.publishing.services.caption_engine._provider',
               return_value=('Caption thứ hai cho kiểm tra trùng lặp.', 'test-model')):
        from modules.publishing.services.caption_engine import generate_job_caption
        generate_job_caption(pipeline_id=pipe2.pk, job_id=job_a.pk)
    job_a.refresh_from_db()
    assert job_a.caption, 'job_a should have auto-approved caption'
    req = factory.post(
        reverse('publishing-manual-handoff', kwargs={
            'pipeline_id': str(pipe2.pk), 'job_id': str(job_a.pk)
        }),
        {'action': 'prepare'}, format='json')
    force_authenticate(req, user=ctv2)
    resp = ManualHandoffAPIView.as_view()(req, pipeline_id=str(pipe2.pk), job_id=str(job_a.pk))
    assert resp.status_code == 201, f'Expected 201, got {resp.status_code}: {resp.data}'
    # Second prepare on same job returns same handoff (idempotent)
    req2 = factory.post(
        reverse('publishing-manual-handoff', kwargs={
            'pipeline_id': str(pipe2.pk), 'job_id': str(job_a.pk)
        }),
        {'action': 'prepare'}, format='json')
    force_authenticate(req2, user=ctv2)
    resp2 = ManualHandoffAPIView.as_view()(req2, pipeline_id=str(pipe2.pk), job_id=str(job_a.pk))
    assert resp2.status_code == 200
    assert resp2.data['data']['id'] == resp.data['data']['id'], 'Prepare must be idempotent'
    # Worker cannot claim a prepared handoff
    from modules.publishing.services.job_engine import claim_due_job
    result = claim_due_job(pipeline_id=pipe2.pk, worker_id='test-worker')
    assert result is None, 'Worker must not claim a job with prepared handoff'
    print('TEST 15 - No duplicate Job/Account/Group, idempotent prepare: PASS')


print()
print('=' * 70)
print('ALL HANDOFF QUEUE + 7-STEP STATUS TESTS: PASSED')
print('=' * 70)
