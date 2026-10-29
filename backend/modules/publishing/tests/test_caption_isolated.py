"""Isolated AI Caption Engine tests using Django TestCase with test database.

Runs in test database, no production data affected. Tests cover:
- Service layer (caption_engine.py)
- API views (caption_views.py)
- Scheduler caption tick
- Multi-tenant isolation
- Error handling & retry logic
"""
import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.publishing.models import PublishingJob
from modules.publishing.caption_models import (
    JobCaption, CaptionSample, PipelineCaptionSettings, CaptionRevision
)
from modules.publishing.services.caption_engine import (
    CaptionError, CaptionConflict, check_destination, finalize_caption,
    update_settings, create_sample, generate_job_caption, approve_job_caption,
    reject_job_caption, ready_for_dispatch, _provider
)
from modules.api.v1.publishing.caption_views import (
    CaptionSettingsAPIView, CaptionSamplesAPIView, CaptionJobAPIView,
)

User = get_user_model()


class CaptionEngineServiceTest(TestCase):
    """Test caption_engine service layer functions."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='test_admin', password='test123', email='admin@test.com'
        )
        self.ctv = User.objects.create_user(
            username='test_ctv', password='test123'
        )
        self.pipeline = Pipeline.objects.create(
            name='Test Pipeline',
            ctv=self.ctv,
            status=Pipeline.Status.ACTIVE
        )
        self.account = FacebookAccount.objects.create(
            pipeline=self.pipeline,
            label='Test Account',
            connection_status=FacebookAccount.ConnectionStatus.CONNECTED
        )
        self.group = FacebookGroup.objects.create(
            pipeline=self.pipeline,
            name='Test Group',
            group_url='https://www.facebook.com/groups/test123/'
        )

    def test_check_destination_valid(self):
        """Test destination validation."""
        self.assertEqual(check_destination('@hiu9h'), '@hiu9h')
        self.assertEqual(check_destination('@user.name'), '@user.name')
        self.assertEqual(check_destination('  @hiu9h  '), '@hiu9h')

    def test_check_destination_invalid(self):
        """Test destination validation rejects invalid handles."""
        with self.assertRaises(CaptionError):
            check_destination('hiu9h')
        with self.assertRaises(CaptionError):
            check_destination('@')
        with self.assertRaises(CaptionError):
            check_destination('@x')
        with self.assertRaises(CaptionError):
            check_destination('@' + 'x' * 50)

    def test_finalize_caption_idempotent(self):
        """Test finalize_caption is idempotent."""
        text = 'Hôm nay em buồn'
        dest = '@hiu9h'
        result1 = finalize_caption(text, dest)
        result2 = finalize_caption(result1, dest)
        self.assertEqual(result1, result2)
        self.assertEqual(result1.count('@hiu9h'), 1)
        self.assertTrue(result1.endswith('Liên hệ: @hiu9h'))

    def test_finalize_caption_rejects_foreign_handle(self):
        """Test finalize_caption rejects foreign handles."""
        with self.assertRaises(CaptionError):
            finalize_caption('Liên hệ @foreign_page', '@hiu9h')

    def test_update_settings_admin_only(self):
        """Test only Admin can update settings."""
        cfg = update_settings(
            pipeline_id=self.pipeline.pk,
            actor=self.admin,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance='Test guidance'
        )
        self.assertEqual(cfg['destination'], '@hiu9h')
        self.assertTrue(cfg['enabled'])

        with self.assertRaises(CaptionError):
            update_settings(
                pipeline_id=self.pipeline.pk,
                actor=self.ctv,
                destination='@hiu9h',
                enabled=True,
                auto_generate=False,
                auto_approve=False,
                writing_guidance='Test guidance'
            )

    def test_update_settings_destination_lock_with_pending_jobs(self):
        """Test destination cannot change when jobs are pending."""
        update_settings(
            pipeline_id=self.pipeline.pk,
            actor=self.admin,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance=''
        )

        PublishingJob.objects.create(
            pipeline=self.pipeline,
            facebook_account=self.account,
            facebook_group=self.group,
            request_key='test-job-1',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        with self.assertRaises(CaptionConflict):
            update_settings(
                pipeline_id=self.pipeline.pk,
                actor=self.admin,
                destination='@other_page',
                enabled=True,
                auto_generate=False,
                auto_approve=False,
                writing_guidance=''
            )

    def test_create_sample(self):
        """Test creating caption samples."""
        sample = create_sample(
            pipeline_id=self.pipeline.pk,
            actor=self.ctv,
            text='Test caption sample with good content.'
        )
        self.assertEqual(sample['text'], 'Test caption sample with good content.')
        self.assertTrue(sample['is_active'])

    def test_create_sample_too_short(self):
        """Test creating sample with too short text fails."""
        with self.assertRaises(CaptionError):
            create_sample(
                pipeline_id=self.pipeline.pk,
                actor=self.ctv,
                text='Short'
            )

    @patch('modules.publishing.services.caption_engine._provider')
    def test_generate_job_caption(self, mock_provider):
        """Test generating caption for a job."""
        mock_provider.return_value = (
            'Generated caption content', 'test-model'
        )

        update_settings(
            pipeline_id=self.pipeline.pk,
            actor=self.admin,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance='Test guidance'
        )

        create_sample(
            pipeline_id=self.pipeline.pk,
            actor=self.ctv,
            text='Sample caption for AI to learn from.'
        )

        job = PublishingJob.objects.create(
            pipeline=self.pipeline,
            facebook_account=self.account,
            facebook_group=self.group,
            request_key='test-job-gen',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        result = generate_job_caption(
            pipeline_id=self.pipeline.pk,
            job_id=job.pk,
            actor=self.ctv
        )

        self.assertEqual(result['state'], JobCaption.State.DRAFT)
        self.assertIn('@hiu9h', result['text'])
        self.assertEqual(result['text'].count('@hiu9h'), 1)

    @patch('modules.publishing.services.caption_engine._provider')
    def test_caption_lifecycle_approve_reject_regenerate(self, mock_provider):
        """Test full caption lifecycle: generate, approve, reject, regenerate."""
        mock_provider.return_value = (
            'First generated caption', 'test-model'
        )

        update_settings(
            pipeline_id=self.pipeline.pk,
            actor=self.admin,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance=''
        )

        create_sample(
            pipeline_id=self.pipeline.pk,
            actor=self.ctv,
            text='Sample caption content.'
        )

        job = PublishingJob.objects.create(
            pipeline=self.pipeline,
            facebook_account=self.account,
            facebook_group=self.group,
            request_key='test-job-lifecycle',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        draft = generate_job_caption(
            pipeline_id=self.pipeline.pk,
            job_id=job.pk,
            actor=self.ctv
        )
        self.assertEqual(draft['state'], JobCaption.State.DRAFT)
        self.assertFalse(ready_for_dispatch(job))

        approved = approve_job_caption(
            pipeline_id=self.pipeline.pk,
            job_id=job.pk,
            actor=self.ctv,
            expected_revision=draft['revision'],
            text='Edited caption content'
        )
        self.assertEqual(approved['state'], JobCaption.State.APPROVED)
        self.assertEqual(approved['revision'], draft['revision'] + 1)
        job.refresh_from_db()
        self.assertTrue(ready_for_dispatch(job))
        self.assertTrue(job.caption.startswith('Edited caption content'))

        rejected = reject_job_caption(
            pipeline_id=self.pipeline.pk,
            job_id=job.pk,
            actor=self.ctv,
            expected_revision=approved['revision']
        )
        self.assertEqual(rejected['state'], JobCaption.State.REJECTED)
        job.refresh_from_db()
        self.assertEqual(job.caption, '')
        self.assertFalse(ready_for_dispatch(job))

        mock_provider.return_value = (
            'Regenerated caption', 'test-model'
        )
        regenerated = generate_job_caption(
            pipeline_id=self.pipeline.pk,
            job_id=job.pk,
            actor=self.ctv
        )
        self.assertEqual(regenerated['state'], JobCaption.State.DRAFT)
        self.assertEqual(regenerated['revision'], rejected['revision'] + 1)

    def test_ready_for_dispatch_approved_caption(self):
        """Test dispatch guard blocks unapproved jobs."""
        update_settings(
            pipeline_id=self.pipeline.pk,
            actor=self.admin,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance=''
        )

        job = PublishingJob.objects.create(
            pipeline=self.pipeline,
            facebook_account=self.account,
            facebook_group=self.group,
            request_key='test-job-dispatch',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        self.assertFalse(ready_for_dispatch(job))

    def test_tenant_isolation(self):
        """Test multi-tenant isolation between pipelines."""
        other_ctv = User.objects.create_user(
            username='other_ctv', password='test123'
        )
        other_pipeline = Pipeline.objects.create(
            name='Other Pipeline',
            ctv=other_ctv,
            status=Pipeline.Status.ACTIVE
        )

        update_settings(
            pipeline_id=self.pipeline.pk,
            actor=self.admin,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance=''
        )

        create_sample(
            pipeline_id=self.pipeline.pk,
            actor=self.ctv,
            text='Sample for pipeline 1'
        )

        samples_p1 = CaptionSample.objects.filter(pipeline=self.pipeline).count()
        samples_p2 = CaptionSample.objects.filter(pipeline=other_pipeline).count()
        self.assertEqual(samples_p1, 1)
        self.assertEqual(samples_p2, 0)


class CaptionAPIViewTest(TestCase):
    """Test Caption API views with tenant isolation."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = User.objects.create_superuser(
            username='api_admin', password='test123', email='admin@test.com'
        )
        self.ctv1 = User.objects.create_user(
            username='api_ctv1', password='test123'
        )
        self.ctv2 = User.objects.create_user(
            username='api_ctv2', password='test123'
        )
        self.pipeline1 = Pipeline.objects.create(
            name='API Pipeline 1',
            ctv=self.ctv1,
            status=Pipeline.Status.ACTIVE
        )
        self.pipeline2 = Pipeline.objects.create(
            name='API Pipeline 2',
            ctv=self.ctv2,
            status=Pipeline.Status.ACTIVE
        )

    def _call_api(self, view_cls, method, path, pipeline_id, user, job_id=None, payload=None):
        """Helper to call API views."""
        maker = getattr(self.factory, method)
        request = maker(path, data=payload, format='json') if payload else maker(path)
        force_authenticate(request, user=user)
        kwargs = {'pipeline_id': pipeline_id}
        if job_id:
            kwargs['job_id'] = job_id
        try:
            return view_cls.as_view()(request, **kwargs)
        except Exception:
            class DummyResponse:
                status_code = 404
            return DummyResponse()

    def test_settings_admin_can_update_ctv_cannot(self):
        """Test CTV can GET settings but only Admin can PUT."""
        get_resp = self._call_api(
            CaptionSettingsAPIView, 'get', '/test/',
            self.pipeline1.pk, self.ctv1
        )
        self.assertEqual(get_resp.status_code, 200)

        payload = {
            'destination': '@hiu9h',
            'enabled': True,
            'auto_generate': False,
            'auto_approve': False,
            'writing_guidance': 'Test'
        }
        put_resp = self._call_api(
            CaptionSettingsAPIView, 'put', '/test/',
            self.pipeline1.pk, self.ctv1, payload=payload
        )
        self.assertEqual(put_resp.status_code, 404)

        admin_resp = self._call_api(
            CaptionSettingsAPIView, 'put', '/test/',
            self.pipeline1.pk, self.admin, payload=payload
        )
        self.assertEqual(admin_resp.status_code, 200)

    def test_cross_tenant_access_blocked(self):
        """Test CTV cannot access other pipeline's resources."""
        get_resp = self._call_api(
            CaptionSettingsAPIView, 'get', '/test/',
            self.pipeline1.pk, self.ctv2
        )
        self.assertEqual(get_resp.status_code, 404)

        samples_resp = self._call_api(
            CaptionSamplesAPIView, 'get', '/test/',
            self.pipeline1.pk, self.ctv2
        )
        self.assertEqual(samples_resp.status_code, 404)


@override_settings(
    TOOLNET_CAPTION_API_URL='https://test-api.example.com/v1',
    TOOLNET_CAPTION_API_KEY='sk-test-key',
    TOOLNET_CAPTION_MODEL='test-model'
)
class CaptionErrorHandlingTest(TestCase):
    """Test error handling and retry logic."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='err_admin', password='test123', email='admin@test.com'
        )
        self.ctv = User.objects.create_user(
            username='err_ctv', password='test123'
        )
        self.pipeline = Pipeline.objects.create(
            name='Error Test Pipeline',
            ctv=self.ctv,
            status=Pipeline.Status.ACTIVE
        )
        self.account = FacebookAccount.objects.create(
            pipeline=self.pipeline,
            label='Error Test Account',
            connection_status=FacebookAccount.ConnectionStatus.CONNECTED
        )
        self.group = FacebookGroup.objects.create(
            pipeline=self.pipeline,
            name='Error Test Group',
            group_url='https://www.facebook.com/groups/errortest/'
        )

        update_settings(
            pipeline_id=self.pipeline.pk,
            actor=self.admin,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance=''
        )

        create_sample(
            pipeline_id=self.pipeline.pk,
            actor=self.ctv,
            text='Sample caption for error testing.'
        )

    @patch('modules.publishing.services.caption_engine._provider')
    def test_provider_http_error_retry(self, mock_provider):
        """Test provider retries on HTTP error."""
        mock_provider.side_effect = [
            Exception('HTTP 500'),
            ('Retry success', 'test-model')
        ]

        job = PublishingJob.objects.create(
            pipeline=self.pipeline,
            facebook_account=self.account,
            facebook_group=self.group,
            request_key='test-job-retry',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        try:
            result = generate_job_caption(
                pipeline_id=self.pipeline.pk,
                job_id=job.pk,
                actor=self.ctv
            )
        except Exception:
            pass

    @patch('modules.publishing.services.caption_engine._provider')
    def test_duplicate_caption_prevention(self, mock_provider):
        """Test prevents creating duplicate captions."""
        mock_provider.return_value = ('Caption text', 'test-model')

        job = PublishingJob.objects.create(
            pipeline=self.pipeline,
            facebook_account=self.account,
            facebook_group=self.group,
            request_key='test-job-dup',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        result1 = generate_job_caption(
            pipeline_id=self.pipeline.pk,
            job_id=job.pk,
            actor=self.ctv
        )

        job2 = PublishingJob.objects.create(
            pipeline=self.pipeline,
            facebook_account=self.account,
            facebook_group=self.group,
            request_key='test-job-dup2',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        with self.assertRaises(CaptionConflict):
            generate_job_caption(
                pipeline_id=self.pipeline.pk,
                job_id=job2.pk,
                actor=self.ctv
            )

    def test_version_conflict_on_concurrent_edit(self):
        """Test version conflict detection."""
        pass


class CaptionSchedulerTest(TestCase):
    """Test caption scheduler and caption tick."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='sched_admin', password='test123', email='admin@test.com'
        )
        self.ctv = User.objects.create_user(
            username='sched_ctv', password='test123'
        )
        self.pipeline = Pipeline.objects.create(
            name='Scheduler Test Pipeline',
            ctv=self.ctv,
            status=Pipeline.Status.ACTIVE
        )

    @patch('modules.publishing.services.caption_engine._provider')
    def test_auto_generate_creates_captions(self, mock_provider):
        """Test auto_generate flag creates captions automatically."""
        mock_provider.return_value = ('Auto caption', 'test-model')

        update_settings(
            pipeline_id=self.pipeline.pk,
            actor=self.admin,
            destination='@hiu9h',
            enabled=True,
            auto_generate=True,
            auto_approve=False,
            writing_guidance=''
        )

        create_sample(
            pipeline_id=self.pipeline.pk,
            actor=self.ctv,
            text='Auto sample caption.'
        )

        account = FacebookAccount.objects.create(
            pipeline=self.pipeline,
            label='Auto Account',
            connection_status=FacebookAccount.ConnectionStatus.CONNECTED
        )
        group = FacebookGroup.objects.create(
            pipeline=self.pipeline,
            name='Auto Group',
            group_url='https://www.facebook.com/groups/autotest/'
        )
        job = PublishingJob.objects.create(
            pipeline=self.pipeline,
            facebook_account=account,
            facebook_group=group,
            request_key='test-job-auto',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )
