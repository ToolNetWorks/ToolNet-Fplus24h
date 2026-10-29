"""Rollback-only: simulated authorized provider, NEVER Facebook network calls."""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob, PublishingAttempt, MediaAllocation
from modules.publishing.readback_models import PostSubmissionReference, PostReadbackAudit
from modules.publishing.verification_models import TrustedPostVerification
from modules.publishing.services.reconciliation import held_subject_ids
from modules.publishing.services.authorized_readback import (
    register_trusted_submission, run_authorized_readback, readback_snapshot,
    IndependentReadback, ReadbackError, ReadbackConflict,
)
from modules.api.v1.publishing.readback_views import PublishingJobReadbackAPIView

User = get_user_model()
now = timezone.now()
suffix = uuid.uuid4().hex[:11]
factory = APIRequestFactory()


def fail(fn, exc):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f'Expected {exc.__name__}')


def get_api(pipeline, job, user=None):
    req = factory.get(f'/api/v1/pipelines/{pipeline.pk}/publishing-jobs/{job.pk}/readback/')
    if user is not None:
        force_authenticate(req, user=user)
    return PublishingJobReadbackAPIView.as_view()(req, pipeline_id=pipeline.pk, job_id=job.pk)


class FakeAuthorizedProvider:
    adapter_id = 'mock-registered-independent-provider'

    def __init__(self, visibility='pending', wrong_group=False, wrong_post=False, bad_url=False):
        self.visibility = visibility
        self.wrong_group = wrong_group
        self.wrong_post = wrong_post
        self.bad_url = bad_url

    def readback(self, **params):
        group_id = str(uuid.uuid4()) if self.wrong_group else params['group_id']
        post_id = ('other-id' if self.wrong_post else params['external_post_id'])
        return IndependentReadback(
            job_id=params['job_id'], pipeline_id=params['pipeline_id'],
            group_id=group_id, external_post_id=post_id,
            group_key=f'proof{suffix}', visibility=self.visibility,
            permalink=(f'https://www.facebook.com/groups/proof{suffix}/posts/{post_id}/'
                       if not self.bad_url else 'https://evil.test/post'),
            observed_at=timezone.now(),
        )


with transaction.atomic():
    owner = User.objects.create_user(username=f'rbk_{suffix}', password='Sample-Pass-Not-Real123!')
    outsider = User.objects.create_user(username=f'rbk_x_{suffix}', password='Sample-Pass-Not-Real123!')
    pipeline = Pipeline.objects.create(name=f'Readback Test {suffix}', ctv=owner, status='active')
    foreign = Pipeline.objects.create(name=f'Readback Other {suffix}', ctv=outsider, status='active')
    account = FacebookAccount.objects.create(pipeline=pipeline, label='Mock Account', connection_status='connected')
    group = FacebookGroup.objects.create(pipeline=pipeline, name='Mock Group',
       group_url=f'https://www.facebook.com/groups/proof{suffix}/')
    allocation = MediaAllocation.objects.create(
        pipeline=pipeline, request_key=f'rbk-media-{suffix}',
        state='uncertain', images_requested=1,
        lease_expires_at=now + timedelta(hours=1),
        policy_snapshot={'image_selection': 'in_order'},
    )
    job = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group,
        media_allocation=allocation, request_key=f'rbk-{suffix}',
        state='uncertain', attempt_count=1, scheduled_at=now, next_run_at=now,
    )
    PublishingAttempt.objects.create(job=job, number=1, state='uncertain', media_allocation=allocation)
    assert account.pk in held_subject_ids(pipeline_id=pipeline.pk)[0]

    key = uuid.uuid4()
    with patch('socket.socket', side_effect=AssertionError('Unexpected network')):
        fail(lambda: register_trusted_submission(
            pipeline_id=pipeline.pk, job_id=job.pk, external_post_id=f'{suffix}post',
            source_id='mock-registered-submitter', submitted_at=now), ReadbackError)
        fail(lambda: run_authorized_readback(
            pipeline_id=pipeline.pk, job_id=job.pk,
            adapter=FakeAuthorizedProvider(), request_key=key), ReadbackError)
        assert not PostSubmissionReference.objects.filter(job=job).exists()
        print('DEFAULT OFF, NO SUBMISSION OR READBACK SIDE EFFECTS: PASS')

        with override_settings(TOOLNET_SUBMISSION_CAPTURE_ENABLED=True,
                               TOOLNET_SUBMISSION_CAPTURE_SOURCE_ID='mock-registered-submitter'):
            ref = register_trusted_submission(
                pipeline_id=pipeline.pk, job_id=job.pk, external_post_id=f'{suffix}post',
                source_id='mock-registered-submitter', submitted_at=now)
            repeat = register_trusted_submission(
                pipeline_id=pipeline.pk, job_id=job.pk, external_post_id=f'{suffix}post',
                source_id='mock-registered-submitter', submitted_at=now)
            assert ref['created'] and not repeat['created'] and repeat['id'] == ref['id']
            fail(lambda: register_trusted_submission(
                pipeline_id=pipeline.pk, job_id=job.pk, external_post_id='different-post',
                source_id='mock-registered-submitter', submitted_at=now), ReadbackConflict)
            assert job.state == 'uncertain'
            print('SUBMISSION LINK IMMUTABLE, IDENTITY-CORRELATED, NOT PUBLISHED: PASS')

        settings_override = dict(
            TOOLNET_PUBLICATION_VERIFIER_ENABLED=True,
            TOOLNET_PUBLICATION_VERIFIER_ID='mock-registered-independent-provider',
        )
        with override_settings(**settings_override):
            pending = run_authorized_readback(
                pipeline_id=pipeline.pk, job_id=job.pk,
                adapter=FakeAuthorizedProvider('pending'), request_key=key)
            assert pending['outcome'] == 'pending'
            assert job.state == 'uncertain'
            assert run_authorized_readback(
                pipeline_id=pipeline.pk, job_id=job.pk,
                adapter=FakeAuthorizedProvider('visible'), request_key=key)['id'] == pending['id']
            assert not TrustedPostVerification.objects.filter(job=job).exists()
            print('PENDING + SAME-KEY REPLAY CANNOT CONFIRM: PASS')

            for adapter in [
                FakeAuthorizedProvider('visible', wrong_group=True),
                FakeAuthorizedProvider('visible', wrong_post=True),
                FakeAuthorizedProvider('visible', bad_url=True),
            ]:
                result = run_authorized_readback(
                    pipeline_id=pipeline.pk, job_id=job.pk,
                    adapter=adapter, request_key=uuid.uuid4())
                assert result['outcome'] == 'mismatch'
                job.refresh_from_db()
                assert job.state == 'uncertain'
            print('WRONG GROUP / POST ID / PERMALINK: FAIL CLOSED: PASS')

            verified = run_authorized_readback(
                pipeline_id=pipeline.pk, job_id=job.pk,
                adapter=FakeAuthorizedProvider('visible'), request_key=uuid.uuid4())
            assert verified['outcome'] == 'verified'
            job.refresh_from_db()
            allocation.refresh_from_db()
            assert job.state == 'published' and job.external_post_id == f'{suffix}post'
            assert allocation.state == 'consumed'
            assert TrustedPostVerification.objects.filter(job=job).count() == 1
            assert account.pk not in held_subject_ids(pipeline_id=pipeline.pk)[0]
            fail(lambda: run_authorized_readback(
                pipeline_id=pipeline.pk, job_id=job.pk,
                adapter=FakeAuthorizedProvider('visible'), request_key=uuid.uuid4()), ReadbackConflict)
            print('MOCK INDEPENDENT VISIBLE READBACK -> JOB/MEDIA VERIFIED ATOMICALLY: PASS')

        snapshot = readback_snapshot(pipeline_id=pipeline.pk, job_id=job.pk)
        assert snapshot['trusted_publication_verified']
        assert snapshot['trusted_submission_linked']
        assert snapshot['last_readback']['outcome'] == 'verified'
        assert snapshot['pagination']['total'] == 5
        assert not any(word in str(snapshot).lower() for word in (
            'claim_token', 'cookie', 'fb_dtsg', 'authorization', 'raw_har',
        ))
        assert get_api(pipeline, job, owner).status_code == 200
        assert get_api(pipeline, job, outsider).status_code == 404
        assert get_api(pipeline, job).status_code in (401, 403)
        assert get_api(foreign, job, outsider).status_code == 404
        print('CTV READ-ONLY API + CROSS-PIPELINE BLOCK + NO SECRETS: PASS')

    assert PostSubmissionReference.objects.filter(pipeline=pipeline).count() == 1
    assert PostReadbackAudit.objects.filter(pipeline=pipeline).count() == 5
    transaction.set_rollback(True)

print('ALL AUTHORIZED READBACK TEST FIXTURES ROLLED BACK')
print('STEP 9.7.10 POST READBACK: PASSED')
