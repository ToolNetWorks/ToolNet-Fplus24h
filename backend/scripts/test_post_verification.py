"""Transactional rollback-only Step 9.7.9 verification tests; no Facebook access."""
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob, PublishingAttempt, MediaAllocation
from modules.publishing.verification_models import (
    PostVerificationObservation, TrustedPostVerification,
)
from modules.publishing.services.reconciliation import held_subject_ids
from modules.publishing.services.post_verification import (
    record_observation, job_verification_snapshot, VisibilityReadback,
    verify_with_authorized_adapter, VerificationError, VerificationConflict,
)
from modules.api.v1.publishing.post_verification_views import PublishingJobVerificationAPIView

User = get_user_model()
suffix = uuid.uuid4().hex[:10]
now = timezone.now()
factory = APIRequestFactory()


def setup_pipeline(label):
    user = User.objects.create_user(username=f'verify_{label}_{suffix}', password='UnrelatedTestPassword123!')
    pipe = Pipeline.objects.create(name=f'Verification {label} {suffix}', ctv=user, status='active')
    acc = FacebookAccount.objects.create(pipeline=pipe, label=f'Account {label}', connection_status='connected')
    group = FacebookGroup.objects.create(pipeline=pipe, name=f'Group {label}',
        group_url=f'https://www.facebook.com/groups/verification{suffix}{label}/')
    return user, pipe, acc, group


def invoke(method, pipe, job_id, user=None, data=None):
    url = f'/api/v1/pipelines/{pipe.pk}/publishing-jobs/{job_id}/verification/'
    req = factory.post(url, data, format='json') if method == 'POST' else factory.get(url)
    if user is not None:
        force_authenticate(req, user=user)
    return PublishingJobVerificationAPIView.as_view()(req, pipeline_id=pipe.pk, job_id=job_id)


def must_fail(action, *types):
    try:
        action()
    except types:
        return
    raise AssertionError('Expected rejection')


with transaction.atomic():
    ctv, pipeline, account, group = setup_pipeline('owned')
    outsider, other_pipe, other_account, other_group = setup_pipeline('foreign')
    job = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group,
        request_key=f'har-check-{suffix}', caption='Test observation',
        scheduled_at=now, next_run_at=now,
        state=PublishingJob.State.UNCERTAIN,
        error_code='UNVERIFIED_RESULT',
    )
    foreign = PublishingJob.objects.create(
        pipeline=other_pipe, facebook_account=other_account, facebook_group=other_group,
        request_key=f'har-foreign-{suffix}', scheduled_at=now, next_run_at=now,
        state=PublishingJob.State.UNCERTAIN,
    )
    queued = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group,
        request_key=f'har-queued-{suffix}', scheduled_at=now, next_run_at=now,
        state=PublishingJob.State.QUEUED,
    )
    key = uuid.uuid4()
    data = dict(
        pipeline_id=pipeline.pk, job_id=job.pk, actor=ctv,
        idempotency_key=key, source='sanitized_har',
        outcome='pending_moderation',
        note='Sanitized HAR: anonymous story acknowledged; Group review pending.',
    )
    with patch('socket.socket', side_effect=AssertionError('Unexpected socket operation')):
        created, is_new = record_observation(**data)
        assert is_new and created['outcome'] == 'pending_moderation'
        again, is_new = record_observation(**data)
        assert not is_new and again['id'] == created['id']
        must_fail(lambda: record_observation(**{**data, 'note': 'A different observation'}), VerificationConflict)
        must_fail(lambda: record_observation(**{**data, 'idempotency_key': uuid.uuid4(),
                    'outcome': 'visible_reported', 'note': 'Cookie: sensitive-value'}), VerificationError)
        must_fail(lambda: record_observation(**{**data, 'idempotency_key': uuid.uuid4(),
                    'evidence_url': 'https://www.facebook.com/groups/123/?access_token=abc'}), VerificationError)
        must_fail(lambda: record_observation(**{**data, 'idempotency_key': uuid.uuid4(),
                    'evidence_url': 'https://www.facebook.com.evil.example/groups/123/'}), VerificationError)
        print('REDACTED OBSERVATIONS / IDEMPOTENCY / SECRET & URL GUARDS: PASS')

        snap = job_verification_snapshot(pipeline_id=pipeline.pk, job_id=job.pk)
        assert snap['most_recent_observation'] == 'pending_moderation'
        assert snap['verified_published'] is False
        assert snap['verified_post_id'] is None
        job.refresh_from_db()
        assert job.state == 'uncertain'
        assert account.pk in held_subject_ids(pipeline_id=pipeline.pk)[0]
        print('HAR PENDING MODERATION DOES NOT RELEASE HOLDS OR VERIFY POST: PASS')

        must_fail(lambda: record_observation(**{**data, 'idempotency_key': uuid.uuid4(), 'job_id': queued.pk}), VerificationConflict)
        must_fail(lambda: record_observation(**{**data, 'idempotency_key': uuid.uuid4(), 'job_id': foreign.pk}), VerificationError)
        must_fail(lambda: record_observation(**{**data, 'idempotency_key': uuid.uuid4(), 'actor': outsider}), VerificationError)
        must_fail(lambda: job_verification_snapshot(pipeline_id=other_pipe.pk, job_id=job.pk), VerificationError)
        print('TENANT / ACTOR / PRE-DISPATCH GUARDS: PASS')

        response = invoke('GET', pipeline, job.pk, ctv)
        assert response.status_code == 200 and response.data['data']['verified_published'] is False
        assert response['Cache-Control'] == 'private, no-store'
        assert invoke('GET', pipeline, job.pk, outsider).status_code == 404
        assert invoke('GET', pipeline, job.pk).status_code in (401, 403)
        bad = invoke('POST', pipeline, job.pk, ctv, {
            'idempotency_key': str(uuid.uuid4()), 'source': 'manual_review',
            'outcome': 'visible_reported', 'note': 'Should not force Facebook status',
            'force_published': True,
        })
        assert bad.status_code == 400
        payload = {
            'idempotency_key': str(uuid.uuid4()), 'source': 'manual_review',
            'outcome': 'visible_reported',
            'note': 'A human saw a screenshot; independent verification unavailable.',
        }
        posted = invoke('POST', pipeline, job.pk, ctv, payload)
        assert posted.status_code == 201, posted.data
        assert job_verification_snapshot(pipeline_id=pipeline.pk, job_id=job.pk)['verified_published'] is False
        print('CTV API AUTH + REJECTS FORCE_PUBLISHED + MANUAL IS NOT PROOF: PASS')

        class FakeAdapter:
            adapter_id = 'test-authorized-readback'
            def __init__(self, visible=True, bad_group=False):
                self.visible = visible
                self.bad_group = bad_group
            def readback(self, **kwargs):
                return VisibilityReadback(
                    visibility='visible' if self.visible else 'pending_moderation',
                    external_post_id=f'post-{suffix}',
                    pipeline_id=kwargs['pipeline_id'],
                    account_id=kwargs['account_id'],
                    group_id=str(other_group.pk) if self.bad_group else kwargs['group_id'],
                    observed_at=timezone.now(),
                )
        must_fail(lambda: verify_with_authorized_adapter(
            pipeline_id=pipeline.pk, job_id=job.pk, adapter=FakeAdapter()), VerificationError)
        with override_settings(TOOLNET_PUBLICATION_VERIFIER_ENABLED=True,
                               TOOLNET_PUBLICATION_VERIFIER_ID='test-authorized-readback'):
            must_fail(lambda: verify_with_authorized_adapter(
                pipeline_id=pipeline.pk, job_id=job.pk, adapter=FakeAdapter(visible=False)), VerificationConflict)
            must_fail(lambda: verify_with_authorized_adapter(
                pipeline_id=pipeline.pk, job_id=job.pk, adapter=FakeAdapter(bad_group=True)), VerificationConflict)
            assert job_verification_snapshot(pipeline_id=pipeline.pk, job_id=job.pk)['verified_published'] is False
            print('VERIFIER FAIL-CLOSED / PENDING & WRONG GROUP REJECTED: PASS')

            allocation = MediaAllocation.objects.create(
                pipeline=pipeline, request_key=f'verify-media-{suffix}',
                state=MediaAllocation.State.UNCERTAIN, images_requested=1,
                lease_expires_at=now + timedelta(hours=1),
                policy_snapshot={'image_selection': 'in_order'},
            )
            job.media_allocation = allocation
            job.attempt_count = 1
            job.save()
            attempt = PublishingAttempt.objects.create(
                job=job, number=1, media_allocation=allocation,
                state=PublishingAttempt.State.UNCERTAIN,
            )
            trusted = verify_with_authorized_adapter(
                pipeline_id=pipeline.pk, job_id=job.pk, adapter=FakeAdapter())
            assert trusted['state'] == 'published'
            job.refresh_from_db()
            allocation.refresh_from_db()
            attempt.refresh_from_db()
            assert job.external_post_id == f'post-{suffix}'
            assert allocation.state == MediaAllocation.State.CONSUMED
            assert attempt.state == PublishingAttempt.State.PUBLISHED
            assert TrustedPostVerification.objects.filter(job=job).count() == 1
            assert account.pk not in held_subject_ids(pipeline_id=pipeline.pk)[0]
            assert job_verification_snapshot(pipeline_id=pipeline.pk, job_id=job.pk)['verified_published'] is True
            print('SIMULATED AUTHORIZED READBACK -> ATOMIC JOB/MEDIA/RECEIPT: PASS')

    assert PostVerificationObservation.objects.filter(pipeline=pipeline).count() == 2
    assert not PostVerificationObservation.objects.filter(pipeline=other_pipe).exists()
    assert not TrustedPostVerification.objects.filter(pipeline=other_pipe).exists()
    transaction.set_rollback(True)

print('ALL VERIFICATION TEST DATA ROLLED BACK')
print('STEP 9.7.9 POST VERIFICATION: PASSED')
