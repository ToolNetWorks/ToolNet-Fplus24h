"""Automation tick tests: retry, stale recovery, all-pipeline scan, leases.

Isolated Django TestCase on the test database. The AI provider is mocked; no
network calls and no Facebook posting occur.
"""
import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.caption_models import (
    JobCaption, CaptionRevision, CaptionSample, PipelineCaptionSettings,
)
from modules.publishing.models import PublishingAttempt, PublishingJob
from modules.publishing.worker_models import WorkerLeaseEvent

User = get_user_model()


class BaseTickTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='tick_admin', password='test123', email='a@test.com')
        self.ctv = User.objects.create_user(username='tick_ctv', password='test123')
        self.pipeline = Pipeline.objects.create(
            name='Tick Pipeline', ctv=self.ctv, status=Pipeline.Status.ACTIVE)
        self.account = FacebookAccount.objects.create(
            pipeline=self.pipeline, label='Acc',
            connection_status=FacebookAccount.ConnectionStatus.CONNECTED)
        self.group = FacebookGroup.objects.create(
            pipeline=self.pipeline, name='Group',
            group_url='https://www.facebook.com/groups/tick_test/')
        PipelineCaptionSettings.objects.create(
            pipeline=self.pipeline, destination='@tick_dest', enabled=True,
            auto_generate=True, auto_approve=True, writing_guidance='')
        CaptionSample.objects.create(
            pipeline=self.pipeline, text='Mẫu caption tích cực mỗi ngày!',
            created_by=self.ctv)

    def make_job(self, *, state=PublishingJob.State.QUEUED, attempt_count=0,
                 key=None):
        return PublishingJob.objects.create(
            pipeline=self.pipeline, facebook_account=self.account,
            facebook_group=self.group,
            request_key=key or 'job-' + uuid.uuid4().hex,
            state=state, attempt_count=attempt_count,
            scheduled_at=timezone.now(), next_run_at=timezone.now())

    def call_tick(self, **kwargs):
        out = StringIO()
        call_command('publishing_caption_tick', stdout=out, **kwargs)
        return json.loads(out.getvalue())

    def call_recovery(self, **kwargs):
        out = StringIO()
        call_command('publishing_recovery_tick', stdout=out, **kwargs)
        return json.loads(out.getvalue())


class CaptionTickRetryTest(BaseTickTest):
    def test_failed_caption_retried_then_auto_approved(self):
        job = self.make_job()
        row = JobCaption.objects.create(
            pipeline=self.pipeline, job=job, state=JobCaption.State.FAILED,
            revision=2)
        CaptionRevision.objects.create(
            job_caption=row, revision=1, action='generation_failed', text='',
            destination='')
        JobCaption.objects.filter(pk=row.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30))

        with patch('modules.publishing.services.caption_engine._provider',
                   return_value=('Caption hợp lệ cho lần thử lại tự động.', 'mock')):
            result = self.call_tick(pipeline_id=self.pipeline.pk, generate=True)

        row.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(row.state, JobCaption.State.APPROVED)
        self.assertEqual(job.caption, row.text)
        self.assertTrue(job.caption.endswith('Liên hệ: @tick_dest'))
        self.assertEqual(result['items'][0]['status'], 'approved')
        self.assertFalse(result['facebook_posting'])

    def test_failed_caption_respects_max_retries(self):
        job = self.make_job()
        row = JobCaption.objects.create(
            pipeline=self.pipeline, job=job, state=JobCaption.State.FAILED,
            revision=4)
        for revision in (1, 2, 3):
            CaptionRevision.objects.create(
                job_caption=row, revision=revision,
                action='generation_failed', text='', destination='')
        JobCaption.objects.filter(pk=row.pk).update(
            updated_at=timezone.now() - timedelta(hours=2))

        with patch('modules.publishing.services.caption_engine._provider') as ai:
            result = self.call_tick(pipeline_id=self.pipeline.pk, generate=True)
            ai.assert_not_called()

        row.refresh_from_db()
        self.assertEqual(row.state, JobCaption.State.FAILED)
        self.assertEqual(result['candidate_count'], 0)

    def test_stale_generating_caption_retried(self):
        job = self.make_job()
        row = JobCaption.objects.create(
            pipeline=self.pipeline, job=job, state=JobCaption.State.GENERATING,
            generation_started_at=timezone.now() - timedelta(minutes=20))
        JobCaption.objects.filter(pk=row.pk).update(
            generation_started_at=timezone.now() - timedelta(minutes=20))

        with patch('modules.publishing.services.caption_engine._provider',
                   return_value=('Caption mới thay thế tiến trình bị kẹt.', 'mock')):
            result = self.call_tick(pipeline_id=self.pipeline.pk, generate=True,
                                    stale_minutes=10)

        row.refresh_from_db()
        self.assertEqual(row.state, JobCaption.State.APPROVED)
        self.assertEqual(len(result['items']), 1)

    def test_preview_scans_all_eligible_pipelines(self):
        other_ctv = User.objects.create_user(username='tick_ctv2', password='test123')
        other = Pipeline.objects.create(
            name='Tick Pipeline 2', ctv=other_ctv, status=Pipeline.Status.ACTIVE)
        PipelineCaptionSettings.objects.create(
            pipeline=other, destination='@tick_dest2', enabled=True,
            auto_generate=True, auto_approve=True)
        CaptionSample.objects.create(
            pipeline=other, text='Mẫu caption thứ hai đủ dài.', created_by=other_ctv)
        self.make_job()

        result = self.call_tick()
        self.assertEqual(result['mode'], 'preview')
        self.assertIn(str(self.pipeline.pk), result['pipeline_ids'])
        self.assertIn(str(other.pk), result['pipeline_ids'])
        self.assertEqual(result['candidate_count'], 1)
        self.assertEqual(result['items'][0]['status'], 'pending')


class RecoveryTickTest(BaseTickTest):
    def test_stale_generating_caption_reset(self):
        job = self.make_job()
        row = JobCaption.objects.create(
            pipeline=self.pipeline, job=job, state=JobCaption.State.GENERATING,
            generation_started_at=timezone.now() - timedelta(hours=1))
        JobCaption.objects.filter(pk=row.pk).update(
            generation_started_at=timezone.now() - timedelta(hours=1))

        result = self.call_recovery(pipeline_id=self.pipeline.pk, apply=True,
                                    stale_caption_minutes=30)
        row.refresh_from_db()
        self.assertEqual(row.state, JobCaption.State.FAILED)
        self.assertIsNone(row.generation_token)
        self.assertTrue(CaptionRevision.objects.filter(
            job_caption=row, action='generation_stale_reset').exists())
        self.assertEqual(len(result['stale_captions']), 1)
        self.assertFalse(result['facebook_posting'])

    def test_expired_lease_quarantined_not_retried(self):
        job = self.make_job(state=PublishingJob.State.CLAIMED, attempt_count=1)
        PublishingJob.objects.filter(pk=job.pk).update(
            worker_id='dead-worker', claim_token='secret',
            lease_expires_at=timezone.now() - timedelta(minutes=5))
        PublishingAttempt.objects.create(
            job=job, number=1, state=PublishingAttempt.State.CLAIMED)

        result = self.call_recovery(pipeline_id=self.pipeline.pk, apply=True)
        job.refresh_from_db()
        self.assertEqual(job.state, PublishingJob.State.UNCERTAIN)
        self.assertEqual(job.error_code, 'WORKER_LEASE_EXPIRED')
        self.assertEqual(job.claim_token, '')
        self.assertTrue(WorkerLeaseEvent.objects.filter(job=job).exists())
        self.assertEqual(result['pipelines'][0]['quarantined_count'], 1)
        self.assertFalse(result['facebook_posting'])

    def test_preview_makes_no_writes(self):
        job = self.make_job(state=PublishingJob.State.CLAIMED, attempt_count=1)
        PublishingJob.objects.filter(pk=job.pk).update(
            lease_expires_at=timezone.now() - timedelta(minutes=5))
        PublishingAttempt.objects.create(
            job=job, number=1, state=PublishingAttempt.State.CLAIMED)

        result = self.call_recovery(pipeline_id=self.pipeline.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, PublishingJob.State.CLAIMED)
        self.assertFalse(WorkerLeaseEvent.objects.filter(job=job).exists())
        self.assertEqual(result['mode'], 'preview')
