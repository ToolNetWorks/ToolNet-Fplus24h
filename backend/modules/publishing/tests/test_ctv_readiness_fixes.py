from datetime import timedelta
from django.utils import timezone
from modules.facebook_publishing.tests.test_worker import FacebookPublishingWorkerTestBase
from modules.publishing.models import PublishingAttempt, PublishingJob
from modules.publishing.worker_models import WorkerLeaseEvent
from modules.publishing.services.worker_reliability import quarantine_stale_leases
from modules.publishing.services.scheduler import _historical_constraints


class RecoveryAndSchedulerTests(FacebookPublishingWorkerTestBase):
    def test_existing_quarantine_event_does_not_abort_recovery(self):
        job = self._create_job()
        job.state = PublishingJob.State.DISPATCHING
        job.attempt_count = 1
        job.lease_expires_at = timezone.now() - timedelta(minutes=1)
        job.save()
        attempt = PublishingAttempt.objects.create(job=job, number=1,
            state=PublishingAttempt.State.DISPATCHING)
        event = WorkerLeaseEvent.objects.create(pipeline=self.pipeline, job=job,
            attempt_number=1, previous_state=job.state, reason_code='WORKER_LEASE_EXPIRED')
        result = quarantine_stale_leases(pipeline_id=self.pipeline.pk)
        job.refresh_from_db(); attempt.refresh_from_db()
        self.assertEqual(job.state, PublishingJob.State.UNCERTAIN)
        self.assertEqual(attempt.state, PublishingAttempt.State.UNCERTAIN)
        self.assertEqual(result['quarantined_count'], 1)
        self.assertEqual(result['quarantined'][0]['event_id'], str(event.pk))
        self.assertEqual(WorkerLeaseEvent.objects.filter(job=job).count(), 1)
        self.assertEqual(quarantine_stale_leases(pipeline_id=self.pipeline.pk)['quarantined_count'], 0)

    def test_submitted_click_counts_for_cooldown_and_daily_limit(self):
        now = timezone.now()
        job = self._create_job()
        job.state = PublishingJob.State.SUBMITTED
        job.finalized_at = now - timedelta(minutes=3)
        job.save()
        blocked, groups, times, counts = _historical_constraints(self.pipeline.pk, now, now)
        self.assertNotIn(self.group.pk, blocked)
        self.assertEqual(groups[self.group.pk], job.finalized_at)
        self.assertEqual(times[self.account.pk], [job.finalized_at])
        self.assertEqual(counts[self.account.pk], 1)

    def test_submitted_without_finalization_blocks_group(self):
        now = timezone.now()
        job = self._create_job()
        job.state = PublishingJob.State.SUBMITTED
        job.finalized_at = None
        job.save()
        blocked, _, _, _ = _historical_constraints(self.pipeline.pk, now, now)
        self.assertIn(self.group.pk, blocked)
