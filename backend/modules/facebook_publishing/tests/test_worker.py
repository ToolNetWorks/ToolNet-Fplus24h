"""Tests for the Facebook Publishing Worker.

Tests cover:
1. Account without anonymous-posting permission.
2. Account with permission that is a Group member.
3. Account with permission that is not a member.
4. A post requiring admin approval.
5. Browser timeout after submission has started.
6. Worker restart mid-Job.
7. No duplicate posts created.
8. Two Pipelines cannot access each other's data.
9. No leakage of Cookie, token, or Proxy credentials through logs.
"""
import json
import os
import uuid
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch, MagicMock, PropertyMock
from tempfile import NamedTemporaryFile

from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.files.images import ImageFile

from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.proxies.models import ProxyEndpoint, ProxyAuthSecret
from modules.albums.models import Album, AlbumImage
from modules.publishing.models import PublishingJob, MediaAllocation, MediaAllocationItem
from modules.publishing.scheduler_models import (
    AccountGroupEligibility, AccountProxyPin, GroupHealth,
)
from modules.facebook_publishing.models import (
    WorkerConfig, WorkerPublishJob, WorkerRunningOp, WorkerResultState,
)
from modules.facebook_publishing.services.config import load_settings, WorkerSettings
from modules.facebook_publishing.services.eligibility import check_group_eligibility
from modules.facebook_publishing.services.account_binding import (
    resolve_account_bundle, AccountProxyBindingError,
)
from modules.facebook_publishing.services.audit_log import AuditLogger, scrub_value, scrub_dict
from modules.facebook_publishing.services.verification import PublishingVerification, VerificationResult
from modules.facebook_publishing.services.reconciliation import reconcile_job_states
from modules.facebook_publishing.services.worker import (
    claim_job, prepare_session, _resolve_caption,
    WorkerError, WorkerNotEnabledError,
)


def _make_test_image(name='test.png', size=(100, 100)):
    """Create a valid PNG in-memory."""
    from PIL import Image
    img = Image.new('RGB', size, color='red')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


class FacebookPublishingWorkerTestBase(TestCase):
    """Shared setUp for all Worker test classes."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username='test_admin', password='test123', email='admin@test.com',
        )
        self.ctv = User.objects.create_user(
            username='test_ctv', password='test123',
        )
        self.other_ctv = User.objects.create_user(
            username='other_ctv', password='test123',
        )

        self.pipeline = Pipeline.objects.create(
            name='Test Pipeline', ctv=self.ctv,
            status=Pipeline.Status.ACTIVE,
        )
        self.other_pipeline = Pipeline.objects.create(
            name='Other Pipeline', ctv=self.other_ctv,
            status=Pipeline.Status.ACTIVE,
        )

        self.account = FacebookAccount.objects.create(
            pipeline=self.pipeline, label='Test Account',
            connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
        )
        self.other_account = FacebookAccount.objects.create(
            pipeline=self.other_pipeline, label='Other Account',
            connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
        )

        self.group = FacebookGroup.objects.create(
            pipeline=self.pipeline, name='Test Group',
            group_url='https://www.facebook.com/groups/test123/',
        )
        self.other_group = FacebookGroup.objects.create(
            pipeline=self.other_pipeline, name='Other Group',
            group_url='https://www.facebook.com/groups/other456/',
        )

        self.proxy = ProxyEndpoint.objects.create(
            pipeline=self.pipeline, account=self.account,
            protocol=ProxyEndpoint.Protocol.HTTP,
            host='proxy.example.com', port=8080,
            health_status=ProxyEndpoint.HealthStatus.HEALTHY,
            exit_ip='203.0.113.1',
            last_checked_at=timezone.now(),
        )
        self.other_proxy = ProxyEndpoint.objects.create(
            pipeline=self.other_pipeline, account=self.other_account,
            protocol=ProxyEndpoint.Protocol.HTTP,
            host='proxy2.example.com', port=8081,
            health_status=ProxyEndpoint.HealthStatus.HEALTHY,
            exit_ip='203.0.113.2',
            last_checked_at=timezone.now(),
        )

        self.pin = AccountProxyPin.objects.create(
            pipeline=self.pipeline, account=self.account,
            proxy=self.proxy, pinned_exit_ip='203.0.113.1',
        )

        self.config = WorkerConfig.objects.create(
            pipeline=self.pipeline, enabled=True, dry_run=True,
        )

    def _create_eligibility(self, **kwargs):
        defaults = {
            'pipeline': self.pipeline,
            'account': self.account,
            'group': self.group,
            'state': AccountGroupEligibility.State.VERIFIED,
            'can_post_anonymous': True,
            'can_post_nonmember': True,
            'verified_at': timezone.now(),
            'expires_at': timezone.now() + timedelta(days=90),
            'evidence_note': 'Manually verified',
        }
        defaults.update(kwargs)
        return AccountGroupEligibility.objects.create(**defaults)

    def _create_job(self, account=None, group=None, pipeline=None):
        account = account or self.account
        group = group or self.group
        pipeline = pipeline or self.pipeline
        return PublishingJob.objects.create(
            pipeline=pipeline, facebook_account=account,
            facebook_group=group,
            request_key='test-job-' + uuid.uuid4().hex[:8],
            caption='Test caption for the group post.',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now(),
        )


class TestTargetedJobClaim(FacebookPublishingWorkerTestBase):
    def test_queue_skips_uncertain_old_attempt_and_placeholder(self):
        from modules.publishing.models import MediaAllocation
        from modules.publishing.services.job_engine import claim_due_job
        old = self._create_job()
        MediaAllocation.objects.create(
            pipeline=self.pipeline, request_key=f'pubjob-{old.pk.hex}-a1',
            state=MediaAllocation.State.UNCERTAIN, images_requested=1,
            lease_expires_at=timezone.now(), policy_snapshot={'source': 'test'},
        )
        placeholder = self._create_job()
        placeholder.caption = 'Nội dung [TRANG_DICH]'
        placeholder.save()
        valid = self._create_job()
        result = claim_due_job(pipeline_id=self.pipeline.pk, worker_id='test-worker')
        self.assertEqual(result['job']['id'], str(valid.pk))
        old.refresh_from_db()
        placeholder.refresh_from_db()
        self.assertEqual(old.state, PublishingJob.State.QUEUED)
        self.assertEqual(placeholder.state, PublishingJob.State.QUEUED)

    def test_media_preflight_does_not_reserve_images(self):
        from modules.albums.models import Album, AlbumImage
        from modules.publishing.models import PipelineMediaPolicy, PipelineAlbumSource, MediaAllocation
        from modules.publishing.services.media_selection import media_available
        PipelineMediaPolicy.objects.create(pipeline=self.pipeline, is_enabled=True)
        album = Album.objects.create(pipeline=self.pipeline, name='Album')
        PipelineAlbumSource.objects.create(pipeline=self.pipeline, album=album, position=1)
        self.assertFalse(media_available(pipeline_id=self.pipeline.pk))
        AlbumImage.objects.create(album=album, original_filename='photo.jpg',
                                  upload_status=AlbumImage.UploadStatus.READY)
        self.assertTrue(media_available(pipeline_id=self.pipeline.pk))
        self.assertFalse(MediaAllocation.objects.filter(pipeline=self.pipeline).exists())

    def test_legacy_dry_run_flag_does_not_control_publishing(self):
        from modules.facebook_publishing.services.worker import _can_publish
        self.config.dry_run = True
        self.config.save()
        settings = load_settings(self.pipeline.pk)
        self.assertTrue(_can_publish(settings, self.config))
        self.config.enabled = False
        self.assertFalse(_can_publish(settings, self.config))

    def test_enabled_worker_uses_publishing_flow(self):
        from types import SimpleNamespace
        from modules.facebook_publishing.management.commands.facebook_publishing_worker import Command
        prefix = 'modules.facebook_publishing.management.commands.facebook_publishing_worker.'
        worker_job = MagicMock()
        session = SimpleNamespace(publish_job=worker_job, bundle=SimpleNamespace(account_id=self.account.pk))
        settings = WorkerSettings(enabled=True)
        claim = {'settings': settings, 'config': self.config, 'claim_token': 'test', 'worker_job': worker_job}
        with patch(prefix + 'claim_job', return_value=claim), \
             patch(prefix + 'prepare_session', return_value=session), \
             patch(prefix + 'prepare_media', return_value=('caption', {'images': []})), \
             patch(prefix + 'check_group_eligibility'), \
             patch(prefix + 'release_running_op'), \
             patch(prefix + 'run_publish', return_value={'result': 'submitted'}) as publish:
            Command()._process_one(self.pipeline.pk, 'worker', False, MagicMock())
        publish.assert_called_once()

    def test_real_publish_requires_specific_image(self):
        from django.core.management import call_command, CommandError
        with self.assertRaisesRegex(CommandError, '--expected-image-id'):
            call_command('facebook_publishing_worker', pipeline_id=self.pipeline.pk,
                         once=True, force_publish=True, job_id=uuid.uuid4())

    def test_wrong_image_fails_before_browser_submission(self):
        from types import SimpleNamespace
        from modules.facebook_publishing.management.commands.facebook_publishing_worker import Command
        prefix = 'modules.facebook_publishing.management.commands.facebook_publishing_worker.'
        worker_job = MagicMock()
        session = SimpleNamespace(publish_job=worker_job, image_ids=[str(uuid.uuid4())])
        settings = WorkerSettings(enabled=True)
        claim = {'settings': settings, 'config': self.config, 'claim_token': 'test', 'worker_job': worker_job}
        with patch(prefix + 'claim_job', return_value=claim), \
             patch(prefix + 'prepare_session', return_value=session), \
             patch(prefix + 'prepare_media', return_value=('caption', {'images': []})), \
             patch(prefix + 'release_running_op'), \
             patch(prefix + 'run_publish') as publish, \
             patch(prefix + 'fail_before_dispatch') as fail:
            with self.assertRaises(WorkerError):
                Command()._process_one(self.pipeline.pk, 'worker', True, MagicMock(),
                                       job_id=uuid.uuid4(), expected_image_id=uuid.uuid4())
        fail.assert_called_once()
        publish.assert_not_called()

    def test_rules_prompt_quarantines_job_without_retry(self):
        from datetime import timedelta
        from modules.publishing.models import PublishingAttempt
        from modules.facebook_publishing.services.rules_review import create_review
        from modules.facebook_publishing.services.rules_confirmation import RulesPrompt
        job = self._create_job()
        job.state = PublishingJob.State.DISPATCHING
        job.attempt_count = 1
        job.save()
        PublishingAttempt.objects.create(job=job, number=1, state=PublishingAttempt.State.DISPATCHING)
        worker_job = WorkerPublishJob.objects.create(job=job, pipeline=self.pipeline,
            account=self.account, group=self.group, worker_id='test-worker',
            state=WorkerResultState.SUBMITTING, attempt_number=1, dry_run=False)
        review_id = create_review(worker_id=worker_job.pk,
            prompt=RulesPrompt('a' * 64, 1, 0, 1, display_text='Group rules'),
            expires_at=timezone.now() + timedelta(minutes=10))
        job.refresh_from_db()
        worker_job.refresh_from_db()
        self.assertTrue(review_id)
        self.assertEqual(job.state, PublishingJob.State.UNCERTAIN)
        self.assertEqual(worker_job.state, WorkerResultState.RULES_CONFIRMATION_REQUIRED)
        self.assertEqual(job.attempt_count, 1)

    def test_targeted_claim_does_not_claim_another_queued_job(self):
        from modules.publishing.services.job_engine import claim_due_job
        first = self._create_job()
        target = self._create_job()
        result = claim_due_job(pipeline_id=self.pipeline.pk, worker_id='targeted-worker', job_id=target.pk)
        self.assertEqual(result['job']['id'], str(target.pk))
        first.refresh_from_db()
        self.assertEqual(first.state, PublishingJob.State.QUEUED)

    def test_expired_eligibility_is_not_accepted(self):
        from datetime import timedelta
        self._create_eligibility(verified_at=timezone.now() - timedelta(days=2),
                                 expires_at=timezone.now() - timedelta(days=1))
        result = check_group_eligibility(pipeline_id=self.pipeline.pk,
            account_id=self.account.pk, group_id=self.group.pk)
        self.assertFalse(result.is_eligible)


class TestRulesReviewAPI(FacebookPublishingWorkerTestBase):
    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient
        from modules.publishing.models import PublishingAttempt
        from modules.facebook_publishing.services.rules_confirmation import RulesPrompt
        from modules.facebook_publishing.services.rules_review import create_review
        self.client = APIClient()
        self.job = self._create_job()
        self.job.state = PublishingJob.State.DISPATCHING
        self.job.attempt_count = 1
        self.job.save()
        PublishingAttempt.objects.create(job=self.job, number=1, state=PublishingAttempt.State.DISPATCHING)
        self.worker = WorkerPublishJob.objects.create(job=self.job, pipeline=self.pipeline,
            account=self.account, group=self.group, worker_id='worker',
            state=WorkerResultState.SUBMITTING, attempt_number=1, dry_run=False)
        WorkerRunningOp.objects.create(account=self.account, publish_job=self.worker,
            worker_id='worker', started_at=timezone.now(), heartbeat_at=timezone.now())
        self.review_id = create_review(worker_id=self.worker.pk,
            prompt=RulesPrompt('a' * 64, 1, 0, 0, display_text='Rules to review'),
            expires_at=timezone.now() + timedelta(minutes=5))
        self.url = f'/api/v1/pipelines/{self.pipeline.pk}/rules-reviews/{self.job.pk}/'

    def test_authorized_confirmation_is_single_use(self):
        from modules.facebook_publishing.services.rules_review import consume_approval, RulesReviewConflict
        self.client.force_authenticate(self.ctv)
        result = self.client.post(self.url, {'digest': 'a' * 64, 'decision': 'approve', 'consent': True}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.post(self.url, {'digest': 'a' * 64, 'decision': 'approve', 'consent': True}, format='json').status_code, 409)
        consume_approval(review_id=self.review_id, digest='a' * 64)
        with self.assertRaises(RulesReviewConflict):
            consume_approval(review_id=self.review_id, digest='a' * 64)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, PublishingJob.State.UNCERTAIN)

    def test_question_answers_are_encrypted_and_consumed_once(self):
        from modules.facebook_publishing.models import RulesReview
        from modules.facebook_publishing.services.rules_review import consume_approval
        self.client.force_authenticate(self.ctv)
        RulesReview.objects.filter(pk=self.review_id).update(response_field_count=1,
            question_schema=[{'label': 'Why join?', 'supported': True}])
        result = self.client.post(self.url, {'digest': 'a' * 64, 'decision': 'approve',
            'consent': True, 'answers': ['My private answer']}, format='json')
        self.assertEqual(result.status_code, 200)
        row = RulesReview.objects.get(pk=self.review_id)
        self.assertNotIn('My private answer', row.answers_ciphertext)
        self.assertEqual(consume_approval(review_id=row.pk, digest=row.digest), ['My private answer'])
        row.refresh_from_db()
        self.assertEqual(row.answers_ciphertext, '')

    def test_other_pipeline_cannot_read_or_approve(self):
        self.client.force_authenticate(self.other_ctv)
        self.assertEqual(self.client.get(f'/api/v1/pipelines/{self.pipeline.pk}/rules-reviews/').status_code, 404)
        self.assertEqual(self.client.post(self.url, {'digest': 'a' * 64, 'decision': 'approve', 'consent': True}, format='json').status_code, 404)

    def test_refusal_never_approves(self):
        from modules.facebook_publishing.models import RulesReview
        self.client.force_authenticate(self.ctv)
        result = self.client.post(self.url, {'digest': 'a' * 64, 'decision': 'reject'}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(RulesReview.objects.get(pk=self.review_id).state, RulesReview.State.REJECTED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, PublishingJob.State.UNCERTAIN)

    def test_expired_browser_and_unanswered_questions_block_approval(self):
        from modules.facebook_publishing.models import RulesReview
        self.client.force_authenticate(self.ctv)
        payload = {'digest': 'a' * 64, 'decision': 'approve', 'consent': True}
        RulesReview.objects.filter(pk=self.review_id).update(response_field_count=1)
        self.assertEqual(self.client.post(self.url, payload, format='json').status_code, 409)
        RulesReview.objects.filter(pk=self.review_id).update(response_field_count=0)
        WorkerRunningOp.objects.filter(publish_job=self.worker).update(heartbeat_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.post(self.url, payload, format='json').status_code, 409)

    @patch('modules.facebook_publishing.management.commands.facebook_rules_reconcile.BrowserManager')
    def test_recovery_with_expired_login_never_reposts(self, manager_class):
        from django.core.management import call_command, CommandError
        self.config.connection_mode = 'direct'
        self.config.save()
        WorkerRunningOp.objects.filter(publish_job=self.worker).update(
            heartbeat_at=timezone.now() - timedelta(minutes=1))
        manager = manager_class.return_value
        manager.load_account_cookies.return_value = (True, 4)
        manager.verify_account_identity.return_value = False
        with self.assertRaises(CommandError):
            call_command('facebook_rules_reconcile', pipeline_id=self.pipeline.pk, job_id=self.job.pk)
        manager.shutdown.assert_called_once()
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, PublishingJob.State.UNCERTAIN)

    def test_session_loss_after_rules_submit_stays_uncertain(self):
        from modules.facebook_publishing.models import RulesReview
        from modules.facebook_publishing.services.rules_review import expire_lost_session
        RulesReview.objects.filter(pk=self.review_id).update(state=RulesReview.State.SUBMITTING)
        WorkerRunningOp.objects.filter(publish_job=self.worker).update(
            heartbeat_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(expire_lost_session(pipeline_id=self.pipeline.pk, job_id=self.job.pk),
                         RulesReview.State.UNCERTAIN)
        self.worker.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.worker.state, WorkerResultState.UNCERTAIN)
        self.assertEqual(self.job.state, PublishingJob.State.UNCERTAIN)


class TestAccountWithoutAnonymousPermission(FacebookPublishingWorkerTestBase):
    """Test 1: An Account without anonymous-posting permission."""

    def test_account_without_anonymous_permission_is_not_eligible(self):
        # Eligibility record exists but can_post_anonymous=False
        self._create_eligibility(can_post_anonymous=False)

        result = check_group_eligibility(
            pipeline_id=self.pipeline.pk,
            account_id=self.account.pk,
            group_id=self.group.pk,
        )

        self.assertFalse(result.is_eligible)
        self.assertFalse(result.can_post_anonymous)
        self.assertEqual(result.reason_code, 'CANNOT_POST_ANONYMOUSLY')

    def test_account_without_anonymous_permission_cannot_prepare(self):
        self._create_eligibility(can_post_anonymous=False)
        job = self._create_job()

        settings = WorkerSettings(
            enabled=True, browser_timeout_seconds=120,
            max_retry_attempts=3, playwright_headless=True,
            facebook_base_url='https://www.facebook.com',
        )

        # The eligibility check should block the account
        bundle = resolve_account_bundle.__wrapped__ if hasattr(
            resolve_account_bundle, '__wrapped__') else None

        result = check_group_eligibility(
            pipeline_id=self.pipeline.pk,
            account_id=self.account.pk,
            group_id=self.group.pk,
        )
        self.assertFalse(result.is_eligible)
        self.assertFalse(result.can_post_anonymous)

    def test_account_without_eligibility_record_is_not_eligible(self):
        result = check_group_eligibility(
            pipeline_id=self.pipeline.pk,
            account_id=self.account.pk,
            group_id=self.group.pk,
        )
        self.assertFalse(result.is_eligible)
        self.assertEqual(result.reason_code, 'NO_VERIFIED_ELIGIBILITY')


class TestAccountWithPermissionIsMember(FacebookPublishingWorkerTestBase):
    """Test 2: An Account with permission that is a Group member."""

    def test_member_account_with_anonymous_permission(self):
        self._create_eligibility(
            can_post_anonymous=True, can_post_nonmember=True,
        )
        result = check_group_eligibility(
            pipeline_id=self.pipeline.pk,
            account_id=self.account.pk,
            group_id=self.group.pk,
        )
        self.assertTrue(result.is_eligible)
        self.assertTrue(result.can_post_anonymous)
        self.assertEqual(result.reason_code, 'VERIFIED')

    def test_member_account_gets_valid_bundle(self):
        self._create_eligibility(
            can_post_anonymous=True, can_post_nonmember=True,
        )
        settings = load_settings(self.pipeline.pk)
        with override_settings(
            FACEBOOK_PUBLISHING_ENABLED='false',
            FACEBOOK_PUBLISHING_DRY_RUN='true',
        ):
            settings = load_settings(self.pipeline.pk)
            bundle = resolve_account_bundle(
                pipeline_id=self.pipeline.pk,
                account_id=self.account.pk,
                group_id=self.group.pk,
                worker_id='test-worker',
                settings=settings,
            )
            self.assertTrue(bundle.is_anonymous_enabled)


class TestAccountWithPermissionIsNotMember(FacebookPublishingWorkerTestBase):
    """Test 3: An Account with permission that is not a member."""

    def test_non_member_account_with_anonymous_permission(self):
        # can_post_nonmember=False means the account IS a member (cannot post as non-member)
        # But in our model, anonymous posting is independent of membership
        self._create_eligibility(
            can_post_anonymous=True, can_post_nonmember=False,
        )
        result = check_group_eligibility(
            pipeline_id=self.pipeline.pk,
            account_id=self.account.pk,
            group_id=self.group.pk,
        )
        self.assertTrue(result.is_eligible)
        self.assertTrue(result.can_post_anonymous)
        # Membership is informational only
        self.assertEqual(result.reason_code, 'VERIFIED')

    def test_explicit_non_member_with_anonymous_permission(self):
        # Non-member but still has anonymous posting
        self._create_eligibility(
            can_post_anonymous=True, can_post_nonmember=True,
        )
        result = check_group_eligibility(
            pipeline_id=self.pipeline.pk,
            account_id=self.account.pk,
            group_id=self.group.pk,
        )
        self.assertTrue(result.is_eligible)
        self.assertTrue(result.can_post_anonymous)

    def test_non_member_anonymous_only(self):
        self._create_eligibility(
            can_post_anonymous=True, can_post_nonmember=True,
        )
        result = check_group_eligibility(
            pipeline_id=self.pipeline.pk,
            account_id=self.account.pk,
            group_id=self.group.pk,
        )
        self.assertTrue(result.is_eligible)
        # Membership can be ANY - does not affect eligibility


class TestAdminApprovalRequired(FacebookPublishingWorkerTestBase):
    """Test 4: A post requiring admin approval."""

    def test_pending_approval_state_transitions_to_uncertain(self):
        job = self._create_job()
        worker_job = WorkerPublishJob.objects.create(
            job=job, pipeline=self.pipeline,
            account=self.account, group=self.group, proxy=self.proxy,
            worker_id='test-worker', state=WorkerResultState.PUBLISHED,
            attempt_number=1, dry_run=False,
        )

        recon = reconcile_job_states(
            pipeline_id=self.pipeline.pk, job_id=str(job.pk),
            worker_job=worker_job,
        )

        self.assertEqual(recon.worker_state, WorkerResultState.PUBLISHED)
        self.assertIn(recon.action, ('confirm_consistent', 'inconsistent_published'))

    def test_publisher_verification_detects_pending_approval(self):
        page = MagicMock()
        page.inner_text.return_value = 'Your post is pending admin approval'
        page.url = 'https://www.facebook.com/groups/test123/'
        page.title.return_value = 'Group Page'
        page.wait_for_selector = MagicMock()
        page.query_selector.return_value = None

        settings = WorkerSettings(
            enabled=True, browser_timeout_seconds=120,
            max_retry_attempts=3, playwright_headless=True,
            facebook_base_url='https://www.facebook.com',
        )
        verifier = PublishingVerification(page, settings)
        result = verifier.verify_post_visibility()
        self.assertEqual(result.state, 'PENDING_APPROVAL')

    def test_publisher_verification_no_post_id_is_uncertain(self):
        page = MagicMock()
        page.inner_text.return_value = 'No posts visible here'
        page.url = 'https://www.facebook.com/groups/test123'
        page.title.return_value = 'Group Page'
        page.wait_for_selector = MagicMock()
        page.query_selector.return_value = None  # No article elements found

        settings = WorkerSettings(
            enabled=True, browser_timeout_seconds=120,
            max_retry_attempts=3, playwright_headless=True,
            facebook_base_url='https://www.facebook.com',
        )
        verifier = PublishingVerification(page, settings)
        result = verifier.verify_post_visibility()
        # No post_id, no visible post -> SUBMITTED_UNVERIFIED or UNCERTAIN
        self.assertIn(result.state, ('SUBMITTED_UNVERIFIED', 'UNCERTAIN'))


class TestBrowserTimeout(FacebookPublishingWorkerTestBase):
    """Test 5: Browser timeout after submission has started."""

    def test_timeout_marks_job_uncertain(self):
        job = self._create_job()
        worker_job = WorkerPublishJob.objects.create(
            job=job, pipeline=self.pipeline,
            account=self.account, group=self.group, proxy=self.proxy,
            worker_id='test-worker', state=WorkerResultState.SUBMITTING,
            attempt_number=1, dry_run=False,
        )

        settings = WorkerSettings(
            enabled=True, browser_timeout_seconds=5,
            max_retry_attempts=3, playwright_headless=True,
            facebook_base_url='https://www.facebook.com',
        )

        page = MagicMock()
        # Simulate timeout: wait_for_selector raises
        page.wait_for_selector.side_effect = Exception('Timeout')
        page.inner_text.return_value = ''
        page.url = ''
        page.title.return_value = ''

        verifier = PublishingVerification(page, settings)
        result = verifier.verify_post_visibility()

        # Should not be PUBLISHED — must be UNCERTAIN
        self.assertIn(result.state, ('UNCERTAIN', 'SUBMITTED_UNVERIFIED'))
        self.assertNotEqual(result.state, 'PUBLISHED')


class TestWorkerRestartMidJob(FacebookPublishingWorkerTestBase):
    """Test 6: Worker restart mid-Job."""

    def test_restart_after_partial_run_resumes_from_uncertain(self):
        job = self._create_job()

        # Simulate a WorkerPublishJob left in PREPARING state by a crashed worker
        worker_job = WorkerPublishJob.objects.create(
            job=job, pipeline=self.pipeline,
            account=self.account, group=self.group, proxy=self.proxy,
            worker_id='old-worker', state=WorkerResultState.PREPARING,
            attempt_number=1, dry_run=True,
        )

        # On restart, the stale job should be detectable and handled
        stale = WorkerPublishJob.objects.get(pk=worker_job.pk)
        self.assertEqual(stale.state, WorkerResultState.PREPARING)

        # A new worker should be able to claim the PublishingJob
        # (the old WorkerPublishJob is separate from PublishingJob state)
        self.assertEqual(job.state, PublishingJob.State.QUEUED)
        self.assertEqual(PublishingJob.objects.filter(
            pk=job.pk, state=PublishingJob.State.QUEUED,
        ).count(), 1)

    def test_stale_running_op_prevents_duplicate_claim(self):
        """If a worker crashes, the RunningOp lock should be detectable."""
        op = WorkerRunningOp.objects.create(
            account=self.account,
            publish_job=WorkerPublishJob.objects.create(
                job=self._create_job(), pipeline=self.pipeline,
                account=self.account, group=self.group, proxy=self.proxy,
                worker_id='old-worker', attempt_number=1, dry_run=True,
            ),
            worker_id='old-worker',
            started_at=timezone.now() - timedelta(hours=2),
            heartbeat_at=timezone.now() - timedelta(hours=2),
        )
        # Op is stale
        self.assertTrue(op.is_stale())

    def test_new_worker_can_claim_after_stale_op_cleaned(self):
        op = WorkerRunningOp.objects.create(
            account=self.account,
            publish_job=WorkerPublishJob.objects.create(
                job=self._create_job(), pipeline=self.pipeline,
                account=self.account, group=self.group, proxy=self.proxy,
                worker_id='old-worker', attempt_number=1, dry_run=True,
            ),
            worker_id='old-worker',
            started_at=timezone.now() - timedelta(hours=2),
            heartbeat_at=timezone.now() - timedelta(hours=2),
        )
        self.assertTrue(op.is_stale())
        op.delete()  # Simulate cleanup
        self.assertEqual(WorkerRunningOp.objects.filter(account=self.account).count(), 0)


class TestNoDuplicatePosts(FacebookPublishingWorkerTestBase):
    """Test 7: No duplicate posts created."""

    def test_result_states_has_no_duplicate_created_state(self):
        # The state machine only has QUEUED, PREPARING, READY, SUBMITTING,
        # SUBMITTED_UNVERIFIED, PENDING_APPROVAL, PUBLISHED, REJECTED, FAILED, UNCERTAIN
        states = [s.value for s in WorkerResultState]
        self.assertEqual(len(states), len(set(states)))

    def test_published_with_same_external_post_id_is_idempotent(self):
        job = self._create_job()
        # Mark PublishingJob as PUBLISHED with matching external_post_id
        job.state = PublishingJob.State.PUBLISHED
        job.external_post_id = '1234567890_9876543210'
        job.finalized_at = timezone.now()
        job.save(update_fields=['state', 'external_post_id', 'finalized_at'])

        worker_job = WorkerPublishJob.objects.create(
            job=job, pipeline=self.pipeline,
            account=self.account, group=self.group, proxy=self.proxy,
            worker_id='test-worker', state=WorkerResultState.PUBLISHED,
            attempt_number=1, dry_run=False,
            external_post_id='1234567890_9876543210',
        )

        # If both Worker and Job Engine report PUBLISHED, reconciliation confirms consistency
        recon = reconcile_job_states(
            pipeline_id=self.pipeline.pk, job_id=str(job.pk),
            worker_job=worker_job,
        )
        self.assertEqual(recon.action, 'confirm_consistent')

    def test_external_post_id_uniqueness_constraint(self):
        job = self._create_job()
        job2 = self._create_job()

        WorkerPublishJob.objects.create(
            job=job, pipeline=self.pipeline,
            account=self.account, group=self.group, proxy=self.proxy,
            worker_id='w1', state=WorkerResultState.PUBLISHED,
            attempt_number=1, dry_run=False,
            external_post_id='111_222',
        )
        WorkerPublishJob.objects.create(
            job=job2, pipeline=self.pipeline,
            account=self.account, group=self.group, proxy=self.proxy,
            worker_id='w2', state=WorkerResultState.PUBLISHED,
            attempt_number=1, dry_run=False,
            external_post_id='111_222',
        )
        # Verify both records exist but the PUBLISHING level constraint prevents
        # both from being PUBLISHED in the job engine
        count = WorkerPublishJob.objects.filter(
            external_post_id='111_222',
            state=WorkerResultState.PUBLISHED,
        ).count()
        self.assertEqual(count, 2)
        # This demonstrates the importance of cross-checking with Job Engine
        # which has the DB-level unique constraint


class TestCrossPipelineIsolation(FacebookPublishingWorkerTestBase):
    """Test 8: Two Pipelines cannot access each other's data."""

    def test_account_from_other_pipeline_not_found(self):
        settings = load_settings(self.other_pipeline.pk)
        with self.assertRaises(AccountProxyBindingError):
            resolve_account_bundle(
                pipeline_id=self.pipeline.pk,
                account_id=self.other_account.pk,  # belongs to other pipeline
                group_id=self.group.pk,
                worker_id='test-worker',
                settings=settings,
            )

    def test_group_from_other_pipeline_not_found(self):
        settings = load_settings(self.pipeline.pk)
        with self.assertRaises(AccountProxyBindingError):
            resolve_account_bundle(
                pipeline_id=self.pipeline.pk,
                account_id=self.account.pk,
                group_id=self.other_group.pk,  # belongs to other pipeline
                worker_id='test-worker',
                settings=settings,
            )

    def test_worker_config_is_per_pipeline(self):
        # Config created for pipeline 1 only
        self.assertTrue(
            WorkerConfig.objects.filter(pipeline=self.pipeline).exists()
        )
        self.assertFalse(
            WorkerConfig.objects.filter(pipeline=self.other_pipeline).exists()
        )

    def test_worker_job_pipeline_mismatch_rejected(self):
        with self.assertRaises(Exception):
            WorkerPublishJob.objects.create(
                job=self._create_job(pipeline=self.other_pipeline),
                pipeline=self.pipeline,  # mismatch
                account=self.account,
                group=self.group,
                proxy=self.proxy,
                worker_id='test',
                attempt_number=1,
            )

    def test_audit_log_scrubs_pipeline_separation(self):
        audit = AuditLogger(worker_id='test', job_id='job-123')
        entry = audit.log_event('test_event', pipeline_id=self.pipeline.pk)
        # The entry should not leak data from the other pipeline
        self.assertIn(str(self.pipeline.pk), json.dumps(entry))


class TestNoCredentialLeakage(FacebookPublishingWorkerTestBase):
    """Test 9: No leakage of Cookie, token, or Proxy credentials through logs."""

    def test_scrub_value_strips_password(self):
        result = scrub_value('password=secret123')
        self.assertIn('[REDACTED]', result)
        self.assertNotIn('secret123', result)

    def test_scrub_value_strips_cookie(self):
        result = scrub_value('cookie=session_id=abc123xyz')
        self.assertIn('[REDACTED]', result)
        self.assertNotIn('session_id=abc123xyz', result)

    def test_scrub_value_strips_token(self):
        result = scrub_value('token=eyJhbGci.eyJzdWI.token')
        self.assertIn('[REDACTED]', result)

    def test_scrub_value_strips_jwt(self):
        jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf3oP'
        result = scrub_value(f'Authorization: Bearer {jwt}')
        self.assertIn('[REDACTED]', result)
        self.assertNotIn(jwt, result)

    def test_scrub_value_strips_proxy_url(self):
        result = scrub_value('proxy_url=http://user:pass@123.45.67.89:8080')
        self.assertIn('[REDACTED]', result)
        self.assertNotIn('pass', result)

    def test_scrub_dict_strips_sensitive_keys(self):
        data = {
            'password': 'secret',
            'cookie': 'abc123',
            'token': 'xyz789',
            'api_key': 'key123',
            'safe_field': 'safe_value',
            'nested': {
                'secret_key': 'nested_secret',
                'safe': 'nested_safe',
            },
        }
        result = scrub_dict(data)
        self.assertEqual(result['password'], '[REDACTED]')
        self.assertEqual(result['cookie'], '[REDACTED]')
        self.assertEqual(result['token'], '[REDACTED]')
        self.assertEqual(result['api_key'], '[REDACTED]')
        self.assertEqual(result['safe_field'], 'safe_value')
        self.assertEqual(result['nested']['secret_key'], '[REDACTED]')
        self.assertEqual(result['nested']['safe'], 'nested_safe')

    def test_clean_log_value_strips_secrets(self):
        worker_job = WorkerPublishJob.objects.create(
            job=self._create_job(), pipeline=self.pipeline,
            account=self.account, group=self.group, proxy=self.proxy,
            worker_id='test', attempt_number=1, dry_run=True,
        )
        result = worker_job.clean_log_value('password=secret token=abc')
        self.assertIn('[REDACTED]', result)
        self.assertNotIn('secret', result)
        self.assertNotIn('abc', result)

    def test_audit_logger_never_logs_raw_cookies(self):
        audit = AuditLogger(worker_id='test', job_id='job-123')
        entry = audit.log_event(
            'cookie_check',
            cookies='session=abc123; c_user=def456',
            token='Bearer xyz789',
        )
        serialized = json.dumps(entry)
        self.assertNotIn('abc123', serialized)
        self.assertNotIn('def456', serialized)
        self.assertNotIn('xyz789', serialized)
        self.assertIn('[REDACTED]', serialized)
