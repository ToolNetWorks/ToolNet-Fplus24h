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


class DirectSchedulerTests(FacebookPublishingWorkerTestBase):
    def setUp(self):
        super().setUp()
        from modules.publishing.scheduler_models import PipelineSchedule
        self._create_eligibility()
        now = timezone.now()
        self.schedule = PipelineSchedule.objects.create(pipeline=self.pipeline,
            name='Direct schedule', enabled=True, interval_minutes=60, max_groups_per_run=1,
            start_at=now, next_run_at=now, caption_template='Sample caption for group')

    def test_direct_assigns_without_proxy_and_preserves_existing_pin(self):
        from modules.facebook_accounts.credentials import FacebookCookieSecret
        from modules.facebook_publishing.models import ConnectionMode
        from modules.publishing.scheduler_models import ScheduledAssignment, AccountProxyPin
        from modules.publishing.services.scheduler import plan_schedule
        self.config.connection_mode = ConnectionMode.DIRECT
        self.config.save()
        FacebookCookieSecret.objects.create(account=self.account, ciphertext='encrypted', cookie_count=2)
        preview = plan_schedule(schedule_id=self.schedule.pk, commit=False)
        self.assertEqual(preview['assigned_count'], 1)
        self.assertIsNone(preview['assignments'][0]['proxy_id'])
        self.assertIsNone(preview['assignments'][0]['exit_ip'])
        self.assertFalse(preview['assignments'][0]['will_pin_proxy'])
        result = plan_schedule(schedule_id=self.schedule.pk, commit=True)
        assignment = ScheduledAssignment.objects.get(batch_id=result['batch_id'])
        self.assertIsNone(assignment.proxy_id)
        self.assertIsNone(assignment.exit_ip_snapshot)
        self.assertTrue(AccountProxyPin.objects.filter(pk=self.pin.pk, proxy=self.proxy).exists())
        from modules.publishing.services.integrity_audit import integrity_snapshot
        audit = integrity_snapshot(pipeline_id=self.pipeline.pk)
        self.assertEqual(audit['scanned']['assignments'], 1)
        self.assertNotIn('ASSIGNMENT_FOREIGN_RESOURCE', [f['code'] for f in audit['findings']])
        self.assertEqual(plan_schedule(schedule_id=self.schedule.pk, commit=True)['status'], 'not_due')

    def test_direct_missing_cookie_does_not_schedule(self):
        from modules.facebook_publishing.models import ConnectionMode
        from modules.publishing.services.scheduler import plan_schedule
        self.config.connection_mode = ConnectionMode.DIRECT
        self.config.save()
        result = plan_schedule(schedule_id=self.schedule.pk, commit=False)
        self.assertEqual(result['assigned_count'], 0)
        self.assertEqual(result['skipped'][0]['code'], 'ACCOUNT_DIRECT_NOT_READY')

    def test_proxy_mode_still_requires_and_records_proxy(self):
        from modules.publishing.scheduler_models import ScheduledAssignment
        from modules.publishing.services.scheduler import plan_schedule
        result = plan_schedule(schedule_id=self.schedule.pk, commit=True)
        assignment = ScheduledAssignment.objects.get(batch_id=result['batch_id'])
        self.assertEqual(assignment.proxy_id, self.proxy.pk)
        self.assertEqual(assignment.exit_ip_snapshot, self.proxy.exit_ip)
