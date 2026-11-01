from datetime import timedelta

from django.utils import timezone

from modules.facebook_publishing.models import RulesReview, WorkerPublishJob, WorkerResultState
from modules.facebook_publishing.services.worker import _record_submit_click
from modules.facebook_publishing.tests.test_worker import FacebookPublishingWorkerTestBase
from modules.publishing.models import MediaAllocation, PublishingAttempt, PublishingJob
from modules.publishing.services.job_engine import JobConflict, flag_uncertain
from modules.publishing.services.reconciliation import held_subject_ids


class SubmittedStateTests(FacebookPublishingWorkerTestBase):
    def setUp(self):
        super().setUp()
        self.job = self._create_job()
        self.allocation = MediaAllocation.objects.create(
            pipeline=self.pipeline, request_key='submit-click-test',
            state=MediaAllocation.State.UNCERTAIN, images_requested=1, policy_snapshot={'reuse': 'cycle'},
            lease_expires_at=timezone.now() + timedelta(minutes=10))
        self.job.media_allocation = self.allocation
        self.job.state = PublishingJob.State.DISPATCHING
        self.job.attempt_count = 1
        self.job.claim_token = 'claim-secret'
        self.job.lease_expires_at = timezone.now() + timedelta(minutes=10)
        self.job.save()
        self.attempt = PublishingAttempt.objects.create(
            job=self.job, number=1, media_allocation=self.allocation,
            state=PublishingAttempt.State.DISPATCHING)
        self.worker = WorkerPublishJob.objects.create(
            job=self.job, pipeline=self.pipeline, account=self.account,
            group=self.group, worker_id='worker-test', attempt_number=1,
            state=WorkerResultState.SUBMITTING, dry_run=False)

    def record(self, token='claim-secret'):
        return _record_submit_click(pipeline_id=self.pipeline.pk, job_id=self.job.pk,
                                    claim_token=token, worker_job_id=self.worker.pk)

    def test_click_finishes_job_without_asserting_published_or_retrying(self):
        self.record()
        self.job.refresh_from_db(); self.worker.refresh_from_db()
        self.allocation.refresh_from_db(); self.attempt.refresh_from_db()
        self.assertEqual(self.job.state, PublishingJob.State.SUBMITTED)
        self.assertEqual(self.worker.state, WorkerResultState.SUBMITTED)
        self.assertEqual(self.attempt.state, PublishingAttempt.State.SUBMITTED)
        self.assertEqual(self.allocation.state, MediaAllocation.State.CONSUMED)
        self.assertEqual(self.job.external_post_id, '')
        self.assertNotIn(self.account.pk, held_subject_ids(pipeline_id=self.pipeline.pk)[0])
        with self.assertRaises(JobConflict):
            self.record()

    def test_invalid_claim_never_finalizes_job(self):
        with self.assertRaises(JobConflict):
            self.record(token='wrong')
        self.job.refresh_from_db(); self.allocation.refresh_from_db()
        self.assertEqual(self.job.state, PublishingJob.State.DISPATCHING)
        self.assertEqual(self.allocation.state, MediaAllocation.State.UNCERTAIN)

    def test_rules_approved_and_submitted_can_finish_same_job(self):
        flag_uncertain(pipeline_id=self.pipeline.pk, job_id=self.job.pk,
                       code='RULES_CONFIRMATION_REQUIRED')
        RulesReview.objects.create(worker_job=self.worker, digest='a' * 64,
            display_text='Group rules', state=RulesReview.State.SUBMITTED,
            decided_by=self.ctv, decided_at=timezone.now(), submit_started_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=1))
        self.record()
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, PublishingJob.State.SUBMITTED)
        self.assertEqual(self.job.error_code, '')

    def test_uncertain_without_submitted_rules_stays_held(self):
        flag_uncertain(pipeline_id=self.pipeline.pk, job_id=self.job.pk,
                       code='RULES_CONFIRMATION_REQUIRED')
        with self.assertRaises(JobConflict):
            self.record()
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, PublishingJob.State.UNCERTAIN)


from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase
from modules.facebook_publishing.services.worker import run_publish


class SubmittedWorkerFlowTests(SimpleTestCase):
    def test_click_once_without_searching_facebook(self):
        page = MagicMock()
        page.locator.return_value.inner_text.return_value = ''
        publish_job = MagicMock(job_id='job', pipeline_id='pipeline', pk=1)
        publish_job.group.group_url = 'https://www.facebook.com/groups/123/'
        session = SimpleNamespace(publish_job=publish_job, worker_id='worker',
            page=page, bundle=SimpleNamespace(account=SimpleNamespace(label='Account')),
            image_ids=['image'], context=MagicMock())
        settings = SimpleNamespace(browser_timeout_seconds=30)
        composer = MagicMock()
        composer.check_anonymous_posting_available.return_value = True
        composer.activate_anonymous.return_value.success = True
        composer.activate_anonymous.return_value.detail = None
        composer.is_anonymous_enabled.return_value = True
        composer.verify_caption.return_value = True
        verifier = MagicMock()
        verifier.check_captcha_or_checkpoint.return_value = None
        stager = MagicMock()
        stager.stage_all.return_value = [SimpleNamespace(temp_path='/tmp/image')]
        prefix = 'modules.facebook_publishing.services.worker.'
        with patch(prefix + '_can_publish', return_value=True), \
             patch(prefix + 'launch_browser'), \
             patch(prefix + 'AnonymousComposer', return_value=composer), \
             patch(prefix + 'PublishingVerification', return_value=verifier), \
             patch(prefix + 'MediaStager', return_value=stager), \
             patch(prefix + '_safe_save'), \
             patch(prefix + 'begin_dispatch'), \
             patch(prefix + 'inspect_rules_prompt', return_value=None), \
             patch(prefix + '_record_submit_click') as record:
            result = run_publish(session, settings, MagicMock(), 'caption', 'claim', MagicMock())
        self.assertEqual(result['result'], 'submitted')
        composer.submit_post.assert_called_once()
        verifier.verify_post_visibility.assert_not_called()
        record.assert_called_once()
