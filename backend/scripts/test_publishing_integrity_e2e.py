"""Rollback-only end-to-end integration: Scheduler -> Worker -> Pending -> Readback.

No live Facebook, cookies, HAR, R2, authorized network provider or external post.
The only "visible" receipt is from a mocked provider inside this DB rollback.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.albums.models import Album, AlbumImage
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import (
    PublishingJob, PublishingAttempt, MediaAllocation,
    PipelineMediaPolicy, PipelineAlbumSource,
)
from modules.publishing.scheduler_models import (
    PipelineSchedule, AccountGroupEligibility, ScheduledBatch, AccountProxyPin,
)
from modules.publishing.review_models import PublishingReviewCase
from modules.publishing.services.scheduler import plan_schedule
from modules.publishing.services.scheduler_tick import tick_due_schedules
from modules.publishing.services.job_engine import (
    claim_due_job, prepare_job_media, begin_dispatch, flag_uncertain,
)
from modules.publishing.services.reconciliation import held_subject_ids
from modules.publishing.services.post_verification import record_observation
from modules.publishing.services.authorized_readback import (
    IndependentReadback, run_authorized_readback, register_trusted_submission,
)
from modules.publishing.services.review_cases import open_case, take_action, CaseConflict
from modules.publishing.services.reports import report_summary
from modules.publishing.services.integrity_audit import integrity_snapshot
from modules.api.v1.publishing.integrity_audit_views import PublishingIntegrityAuditAPIView

User = get_user_model()
now = timezone.now()
suffix = uuid.uuid4().hex[:10]
factory = APIRequestFactory()


class MockAuthorizedReadback:
    adapter_id = 'mock-integrity-authorized'

    def __init__(self, visibility):
        self.visibility = visibility

    def readback(self, **params):
        return IndependentReadback(
            pipeline_id=params['pipeline_id'], job_id=params['job_id'],
            group_id=params['group_id'], group_key=f'integrity{suffix}',
            external_post_id=params['external_post_id'], visibility=self.visibility,
            permalink=f'https://www.facebook.com/groups/integrity{suffix}/posts/{params["external_post_id"]}/',
            observed_at=timezone.now(),
        )


def check_request(pipeline, user=None, query=''):
    path = f'/api/v1/pipelines/{pipeline.pk}/integrity-audit/{query}'
    request = factory.get(path)
    if user is not None:
        force_authenticate(request, user=user)
    return PublishingIntegrityAuditAPIView.as_view()(request, pipeline_id=pipeline.pk)


with transaction.atomic():
    owner = User.objects.create_user(username=f'integrity_{suffix}', password='UnusedTestPwd123!')
    outsider = User.objects.create_user(username=f'integrity_out_{suffix}', password='UnusedTestPwd123!')
    pipe = Pipeline.objects.create(name=f'Integrity pipeline {suffix}', ctv=owner, status='active')
    foreign = Pipeline.objects.create(name=f'Integrity foreign {suffix}', ctv=outsider, status='active')
    account = FacebookAccount.objects.create(
        pipeline=pipe, label='Test Account', connection_status='connected',
    )
    proxy = ProxyEndpoint.objects.create(
        pipeline=pipe, account=account, host='8.8.8.8', port=19080,
        protocol='http', is_enabled=True, health_status='healthy',
        exit_ip='8.8.8.8', last_checked_at=now,
    )
    group = FacebookGroup.objects.create(
        pipeline=pipe, name='Test Group',
        group_url=f'https://www.facebook.com/groups/integrity{suffix}/',
    )
    AccountGroupEligibility.objects.create(
        pipeline=pipe, account=account, group=group, state='verified',
        can_post_anonymous=True, can_post_nonmember=True,
        verified_at=now - timedelta(minutes=3), expires_at=now + timedelta(days=7),
        evidence_note='Explicitly verified mock eligibility for isolated test.',
    )
    schedule = PipelineSchedule.objects.create(
        pipeline=pipe, name='Readback test schedule', enabled=True,
        start_at=now - timedelta(minutes=1), next_run_at=now - timedelta(minutes=1),
        interval_minutes=1440, max_groups_per_run=1,
        caption_template='Test {group_name}',
        require_anonymous=True, require_nonmember=True,
    )
    album = Album.objects.create(pipeline=pipe, name='Test album')
    img_id = uuid.uuid4()
    AlbumImage.objects.create(
        id=img_id, album=album, original_filename='sample.webp',
        storage_key=f'pipeline-albums/{pipe.pk}/{album.pk}/{img_id}.webp',
        mime_type='image/webp', file_size=1024, width=20, height=20,
        sha256='a' * 64, position=1, upload_status='ready',
    )
    PipelineMediaPolicy.objects.create(pipeline=pipe, is_enabled=True, images_per_post=1)
    PipelineAlbumSource.objects.create(pipeline=pipe, album=album, position=1)

    # Block ALL socket creation throughout the simulated E2E run; only mock
    # providers may provide a readback result. No real Facebook interaction.
    with patch('socket.socket', side_effect=AssertionError('Network access forbidden in E2E test')):
        preview = plan_schedule(schedule_id=schedule.pk, now=now)
        assert preview['assigned_count'] == 1 and preview['committed'] is False, preview
        assert not PublishingJob.objects.filter(pipeline=pipe).exists()
        assert not AccountProxyPin.objects.filter(pipeline=pipe).exists()
        tick = tick_due_schedules(
            enqueue=True, pipeline_id=pipe.pk, schedule_id=schedule.pk,
            worker_id='integration-test', now=now,
        )
        assert tick['queued_count'] == 1, tick
        assert PublishingJob.objects.filter(pipeline=pipe, state='queued').count() == 1
        assert ScheduledBatch.objects.filter(pipeline=pipe).count() == 1
        assert AccountProxyPin.objects.filter(pipeline=pipe).count() == 1
        repeated = tick_due_schedules(
            enqueue=True, pipeline_id=pipe.pk, schedule_id=schedule.pk,
            worker_id='integration-test', now=now,
        )
        assert repeated['queued_count'] == 0 and PublishingJob.objects.filter(pipeline=pipe).count() == 1
        print('SCHEDULER PREVIEW / ENQUEUE / IDEMPOTENCY: PASS')

        claimed = claim_due_job(pipeline_id=pipe.pk, worker_id='integration-test')
        assert claimed and claimed['job']['state'] == 'claimed'
        job_id = uuid.UUID(claimed['job']['id'])
        token = claimed['claim_token']
        assert claim_due_job(pipeline_id=pipe.pk, worker_id='integration-test') is None
        prepared = prepare_job_media(pipeline_id=pipe.pk, job_id=job_id, claim_token=token)
        assert prepared['state'] == 'ready'
        started = begin_dispatch(pipeline_id=pipe.pk, job_id=job_id, claim_token=token)
        assert started['state'] == 'dispatching'
        # NO external POST: purely simulation of the irreversible boundary.
        uncertain = flag_uncertain(pipeline_id=pipe.pk, job_id=job_id)
        assert uncertain['state'] == 'uncertain'
        allocation = MediaAllocation.objects.get(pk=prepared['media_allocation_id'])
        assert allocation.state == 'uncertain'
        assert account.pk in held_subject_ids(pipeline_id=pipe.pk)[0]
        print('JOB CLAIM / MEDIA / DISPATCH BOUNDARY / SAFE HOLD: PASS')

        observation, created = record_observation(
            pipeline_id=pipe.pk, job_id=job_id, actor=owner,
            idempotency_key=uuid.uuid4(), source='sanitized_har',
            outcome='pending_moderation',
            note='Mock sanitized submission observation; awaiting group moderation.',
        )
        assert created and observation['outcome'] == 'pending_moderation'
        case, _ = open_case(pipeline_id=pipe.pk, job_id=job_id, actor=owner)
        case = take_action(pipeline_id=pipe.pk, case_id=case['id'], actor=owner,
                           action='assign_me', expected_version=case['version'])
        case = take_action(pipeline_id=pipe.pk, case_id=case['id'], actor=owner,
                           action='add_evidence', expected_version=case['version'],
                           note='Checked pending moderation; no public publication confirmed.')
        case = take_action(pipeline_id=pipe.pk, case_id=case['id'], actor=owner,
                           action='request_verification', expected_version=case['version'])
        assert case['status'] == 'awaiting_verification'
        try:
            take_action(pipeline_id=pipe.pk, case_id=case['id'], actor=owner,
                        action='close', expected_version=case['version'])
        except CaseConflict:
            pass
        else:
            raise AssertionError('Closing pending review without proof was accepted')
        assert integrity_snapshot(pipeline_id=pipe.pk, now=now)['status'] == 'consistent'
        print('PENDING OBSERVATION / REVIEW CASE / NO FALSE SUCCESS: PASS')

        post_id = f'integrity_{suffix}'
        with override_settings(
            TOOLNET_SUBMISSION_CAPTURE_ENABLED=True,
            TOOLNET_SUBMISSION_CAPTURE_SOURCE_ID='mock-submitter',
        ):
            linked = register_trusted_submission(
                pipeline_id=pipe.pk, job_id=job_id, external_post_id=post_id,
                source_id='mock-submitter', submitted_at=timezone.now(),
            )
            assert linked['created'] is True
        with override_settings(
            TOOLNET_PUBLICATION_VERIFIER_ENABLED=True,
            TOOLNET_PUBLICATION_VERIFIER_ID='mock-integrity-authorized',
        ):
            pending = run_authorized_readback(
                pipeline_id=pipe.pk, job_id=job_id,
                adapter=MockAuthorizedReadback('pending'), request_key=uuid.uuid4(),
            )
            assert pending['outcome'] == 'pending'
            assert PublishingJob.objects.get(pk=job_id).state == 'uncertain'
            assert account.pk in held_subject_ids(pipeline_id=pipe.pk)[0]
            print('TRUSTED SUBMISSION / MODERATION PENDING KEEPS HOLD: PASS')

            verified = run_authorized_readback(
                pipeline_id=pipe.pk, job_id=job_id,
                adapter=MockAuthorizedReadback('visible'), request_key=uuid.uuid4(),
            )
            assert verified['outcome'] == 'verified'
            final_job = PublishingJob.objects.get(pk=job_id)
            allocation.refresh_from_db()
            attempt = PublishingAttempt.objects.get(job_id=job_id, number=1)
            assert final_job.state == 'published' and final_job.external_post_id == post_id
            assert allocation.state == 'consumed' and attempt.state == 'published'
            assert account.pk not in held_subject_ids(pipeline_id=pipe.pk)[0]
            print('MOCK INDEPENDENT VISIBLE / JOB + MEDIA + ATTEMPT ATOMIC: PASS')

        summary = report_summary(pipeline_id=pipe.pk, days=30)
        assert summary['jobs']['published_verified'] == 1, summary
        case = take_action(pipeline_id=pipe.pk, case_id=case['id'], actor=owner,
                           action='close', expected_version=case['version'])
        assert case['status'] == 'closed'
        valid = integrity_snapshot(pipeline_id=pipe.pk, now=now)
        assert valid['complete'] and valid['status'] == 'consistent', valid
        print('REPORT VERIFIED / CASE CLOSED / INTEGRITY CONSISTENT: PASS')

        # Public API is read-only and scoped to the CTV. Foreign/anonymous
        # users cannot inspect any data from this Pipeline.
        owner_response = check_request(pipe, owner)
        assert owner_response.status_code == 200, owner_response.data
        assert owner_response['Cache-Control'] == 'private, no-store'
        assert check_request(pipe, outsider).status_code == 404
        assert check_request(pipe).status_code in (401, 403)
        assert check_request(foreign, outsider).status_code == 200
        assert check_request(pipe, owner, '?limit=99999').status_code == 400
        assert 'claim_token' not in str(owner_response.data)
        assert 'mock-submitter' not in str(owner_response.data)
        print('CTV SCOPING / NO SECRETS / READ ONLY: PASS')

        # Tampered legacy/invalid published record should be detected but
        # NEVER corrected by the audit. This record lives ONLY in rollback.
        bad = PublishingJob.objects.create(
            pipeline=pipe, facebook_account=account, facebook_group=group,
            request_key=f'bad-{suffix}', state='published',
            scheduled_at=now, next_run_at=now, external_post_id='',
        )
        findings = integrity_snapshot(pipeline_id=pipe.pk, now=now)
        assert findings['status'] == 'attention_required'
        assert 'PUBLISHED_WITHOUT_POST_ID' in {x['code'] for x in findings['findings']}
        assert PublishingJob.objects.get(pk=bad.pk).state == 'published'
        partial = integrity_snapshot(pipeline_id=pipe.pk, sample_limit=1, now=now)
        assert not partial['complete'] and partial['status'] == 'incomplete'
        print('DETECT INVALID PUBLISHED / NO AUTO-REPAIR / PARTIAL NOT PASS: PASS')

    transaction.set_rollback(True)

print('ALL END-TO-END FIXTURES ROLLED BACK')
print('STEP 9.7.11 INTEGRITY E2E: PASSED')
