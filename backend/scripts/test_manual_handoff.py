"""Step 9.7.16 rollback-only test; zero Facebook / R2 network I/O."""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.publishing.manual_handoff_views import ManualHandoffAPIView
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.albums.models import Album, AlbumImage
from modules.publishing.models import (
    PublishingJob, PublishingAttempt, PipelineMediaPolicy,
    PipelineAlbumSource, MediaAllocation,
)
from modules.publishing.manual_handoff_models import ManualPublishingHandoff, ManualPublishingEvent
from modules.publishing.scheduler_models import AccountGroupEligibility
from modules.publishing.services.job_engine import (
    claim_due_job, cancel_queued_job, JobConflict,
)
from modules.publishing.services.reconciliation import held_subject_ids
from modules.publishing.services.manual_handoff import (
    prepare_handoff, mutate_handoff, get_handoff, HandoffConflict, HandoffError,
)

suffix = uuid.uuid4().hex[:10]
now = timezone.now()
factory = APIRequestFactory()
User = get_user_model()


def rejects(fn, *errors):
    try:
        fn()
    except errors:
        return
    raise AssertionError('Expected an explicit failure.')


def api(pipe, job, actor=None, payload=None):
    url = f'/api/v1/pipelines/{pipe.pk}/publishing-jobs/{job.pk}/manual-handoff/'
    req = (factory.post(url, payload, format='json') if payload is not None else factory.get(url))
    if actor is not None:
        force_authenticate(req, user=actor)
    return ManualHandoffAPIView.as_view()(req, pipeline_id=pipe.pk, job_id=job.pk)


with transaction.atomic():
    ctv = User.objects.create_user(username='manual_' + suffix, password='TestOnly!12345')
    outsider = User.objects.create_user(username='outsider_' + suffix, password='TestOnly!12345')
    pipe = Pipeline.objects.create(name='Manual ' + suffix, ctv=ctv, status='active')
    other = Pipeline.objects.create(name='Foreign ' + suffix, ctv=outsider, status='active')
    acc = FacebookAccount.objects.create(pipeline=pipe, label='Manual Test', connection_status='connected')
    group = FacebookGroup.objects.create(pipeline=pipe, name='Manual Group',
        group_url=f'https://www.facebook.com/groups/manual{suffix}/')
    album = Album.objects.create(pipeline=pipe, name='Manual Album')
    for index in range(2):
        image_id = uuid.uuid4()
        AlbumImage.objects.create(
            id=image_id, album=album, original_filename=f'{index}.webp',
            storage_key=f'pipeline-albums/{pipe.pk}/{album.pk}/{image_id}.webp',
            mime_type='image/webp', file_size=1024, width=20, height=20,
            sha256='a' * 64, position=index + 1, upload_status='ready',
        )
    PipelineMediaPolicy.objects.create(pipeline=pipe, is_enabled=True, images_per_post=1)
    PipelineAlbumSource.objects.create(pipeline=pipe, album=album, position=1)
    job = PublishingJob.objects.create(
        pipeline=pipe, facebook_account=acc, facebook_group=group,
        request_key=f'manual-{suffix}', caption='Manual caption',
        next_run_at=now - timedelta(minutes=1), scheduled_at=now - timedelta(minutes=1),
    )
    eligibility = AccountGroupEligibility.objects.create(
        pipeline=pipe, account=acc, group=group,
        state='verified', can_post_anonymous=True,
        can_post_nonmember=False, verified_at=now - timedelta(minutes=2),
        expires_at=now + timedelta(days=1), evidence_note='Explicit operator check.',
    )

    with patch('socket.socket', side_effect=AssertionError('Unexpected network')):
        response = api(pipe, job, ctv)
        assert response.status_code == 200 and response.data['data']['can_prepare']
        assert api(pipe, job, outsider).status_code == 404
        assert api(other, job, outsider).status_code == 404
        assert api(pipe, job).status_code in (401, 403)
        assert api(pipe, job, ctv, {'action': 'prepare', 'force_published': True}).status_code == 400
        print('TENANT AUTH + STRICT PAYLOAD + NO NETWORK: PASS')

        # No permission claim without evidence.
        eligibility.state = 'unknown'
        eligibility.save()
        rejects(lambda: prepare_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv), HandoffConflict)
        eligibility.state = 'verified'
        eligibility.save()
        record = prepare_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv)
        assert record['state'] == 'prepared' and len(record['media']) == 1
        same = prepare_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv)
        assert same['id'] == record['id']
        job.refresh_from_db()
        allocation = job.media_allocation
        assert allocation.state == 'reserved'
        assert claim_due_job(pipeline_id=pipe.pk, worker_id='worker-test') is None
        assert acc.pk in held_subject_ids(pipeline_id=pipe.pk)[0]
        rejects(lambda: cancel_queued_job(pipeline_id=pipe.pk, job_id=job.pk), JobConflict)
        rejects(lambda: prepare_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=outsider), HandoffError)
        print('RESERVE IMAGE + REPLAY + WORKER EXCLUSION + ELIGIBILITY: PASS')

        # Open boundary is before the browser action; no external post is sent.
        opened = mutate_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv,
            action='open', expected_version=record['version'])
        job.refresh_from_db(); allocation.refresh_from_db()
        assert opened['state'] == 'opened' and job.state == 'uncertain'
        assert job.attempt_count == 1 and allocation.state == 'uncertain'
        assert PublishingAttempt.objects.filter(job=job, state='uncertain').count() == 1
        rejects(lambda: mutate_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv,
            action='abandon', expected_version=opened['version']), HandoffConflict)
        rejects(lambda: mutate_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv,
            action='open', expected_version=opened['version']), HandoffConflict)
        print('OPEN BOUNDARY -> UNCERTAIN + ACCOUNT/IMAGE HOLD: PASS')

        report = mutate_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv,
            action='report', expected_version=opened['version'],
            outcome='pending_reported', note='Facebook reported a moderation queue.')
        job.refresh_from_db(); allocation.refresh_from_db()
        assert report['state'] == 'pending_reported' and job.state == 'uncertain'
        assert allocation.state == 'uncertain' and not job.external_post_id
        rejects(lambda: mutate_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv,
            action='report', expected_version=report['version'], outcome='published',
            note='Forced publication'), HandoffError)
        rejects(lambda: mutate_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv,
            action='report', expected_version=opened['version'], outcome='submitted_reported'), HandoffConflict)
        assert api(pipe, job, ctv, {
            'action': 'report', 'expected_version': report['version'],
            'outcome': 'pending_reported', 'note': 'Cookie: secret',
        }).status_code == 400
        assert ManualPublishingEvent.objects.filter(handoff__job=job).count() == 3
        print('PENDING REPORT DOES NOT CONFIRM PUBLICATION OR RELEASE MEDIA: PASS')

        # Separate account, group and job: release reserved images ONLY before opening.
        second_acc = FacebookAccount.objects.create(pipeline=pipe, label='Second', connection_status='connected')
        second_group = FacebookGroup.objects.create(pipeline=pipe, name='Second Group',
            group_url=f'https://www.facebook.com/groups/second{suffix}/')
        AccountGroupEligibility.objects.create(
            pipeline=pipe, account=second_acc, group=second_group,
            state='verified', can_post_anonymous=True,
            verified_at=now - timedelta(minutes=1), expires_at=now + timedelta(days=1),
            evidence_note='Explicit operator check.',
        )
        second = PublishingJob.objects.create(
            pipeline=pipe, facebook_account=second_acc, facebook_group=second_group,
            request_key=f'manual-second-{suffix}', caption='Second caption',
            next_run_at=now - timedelta(minutes=1), scheduled_at=now - timedelta(minutes=1),
        )
        second_record = prepare_handoff(pipeline_id=pipe.pk, job_id=second.pk, actor=ctv)
        second.refresh_from_db()
        second_allocation = second.media_allocation
        abandoned = mutate_handoff(pipeline_id=pipe.pk, job_id=second.pk, actor=ctv,
            action='abandon', expected_version=second_record['version'])
        second.refresh_from_db(); second_allocation.refresh_from_db()
        assert abandoned['state'] == 'abandoned' and second.state == 'cancelled'
        assert second_allocation.state == 'released'
        assert not ManualPublishingHandoff.objects.filter(pipeline=other).exists()
        print('ABANDON BEFORE OPEN: CANCEL JOB / RELEASE RESERVED MEDIA: PASS')

    transaction.set_rollback(True)

print('ALL FIXTURES ROLLED BACK — STEP 9.7.16: PASSED')
