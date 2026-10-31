import io
import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from modules.system_config.models import AIProvider, AIProviderKey, AIModel, AIRoute, AIFallback, SystemConfigAuditLog
from modules.system_config.services import ai_router
from modules.system_config.services.adapters.protocol import Protocol, ProviderError
from modules.system_config.services.key_manager import select_key


def completion(text='Caption đúng Model', model='selected-model'):
    return {'success': True, 'text': text, 'model': model, 'usage': {'total_tokens': 10}, 'http_status': 200, 'latency_ms': 5}


class AIRegistryTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('ai-admin', 'ai@test.example', 'password')
        self.client.force_login(self.admin)
        self.provider = AIProvider.objects.create(name='ToolNet Test', provider_type='toolnet', base_url='https://api.example.test/v1', is_active=True)
        self.key = AIProviderKey(provider=self.provider, name='Primary Key')
        self.key.set_secret('unusual-secret-key-not-a-known-pattern'); self.key.save()
        self.model = AIModel.objects.create(provider=self.provider, model_id='selected-model', display_name='Selected', is_enabled=True)

    def url(self, name, **kwargs):
        return reverse(name, kwargs=kwargs or None)

    def model_url(self, name='ai-model', model=None):
        return self.url(name, provider_id=self.provider.pk, model_id=(model or self.model).pk)

    def write(self, url, data, method='post'):
        return getattr(self.client, method)(url, json.dumps(data), content_type='application/json')

    def test_provider_create_is_disabled_by_default_and_blank_key_preserved(self):
        response = self.write(self.url('ai-providers'), {'name': 'New', 'provider_type': 'openai', 'base_url': 'https://api.openai.com/v1', 'api_key': 'plain-secret', 'custom_headers': {'X-Title': 'private-header'}})
        self.assertEqual(response.status_code, 201, response.content)
        provider = AIProvider.objects.get(pk=response.json()['id'])
        self.assertFalse(provider.is_active)
        self.assertNotIn('private-header', response.content.decode())
        self.assertNotIn('plain-secret', response.content.decode())
        self.assertNotEqual(provider.keys.get().secret_encrypted, 'plain-secret')
        self.assertEqual(provider.keys.get().get_secret(), 'plain-secret')
        response = self.write(self.url('ai-provider', provider_id=provider.pk), {'name': 'Edited', 'api_key': ''}, 'patch')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.keys.get().get_secret(), 'plain-secret')
        for headers in [{'Authorization': 'secret'}, {'Host': 'localhost'}, {'X-Title': 'bad\r\nCookie: token'}, {'x-api-key': 'raw'}]:
            self.assertEqual(self.write(self.url('ai-provider', provider_id=provider.pk), {'custom_headers': headers}, 'patch').status_code, 400)

    def test_keys_crud_rotation_and_no_plaintext_api_or_audit(self):
        url = self.url('ai-keys', provider_id=self.provider.pk)
        response = self.write(url, {'name': 'Backup', 'secret': 'backup-key-secret', 'priority': 2})
        self.assertEqual(response.status_code, 201)
        key = AIProviderKey.objects.get(pk=response.json()['id'])
        detail = self.url('ai-key', provider_id=self.provider.pk, key_id=key.pk)
        self.assertEqual(self.write(detail, {'secret': '', 'is_active': False}, 'patch').status_code, 200)
        key.refresh_from_db(); self.assertEqual(key.get_secret(), 'backup-key-secret')
        self.assertEqual(self.write(detail, {'secret': 'rotated-key'}, 'patch').status_code, 200)
        key.refresh_from_db(); self.assertEqual(key.get_secret(), 'rotated-key')
        payload = self.client.get(url).content.decode()
        self.assertNotIn('rotated-key', payload); self.assertNotIn('secret_encrypted', payload)
        self.assertEqual(self.client.delete(detail).status_code, 200)
        for log in SystemConfigAuditLog.objects.all():
            self.assertNotIn('rotated-key', json.dumps(log.details))

    def test_revoked_keys_cannot_resurrect_legacy_shadow(self):
        self.provider.set_api_key('old-shadow'); self.provider.save()
        self.client.delete(self.url('ai-key', provider_id=self.provider.pk, key_id=self.key.pk))
        self.provider.refresh_from_db()
        with self.assertRaises(ProviderError):
            select_key(self.provider)

    def test_rotation_requires_authorization_and_never_changes_key_on_429(self):
        with self.assertRaises(ProviderError):
            select_key(self.provider, 'round_robin')
        self.provider.rotation_authorized = True; self.provider.save()
        extra = AIProviderKey(provider=self.provider, name='Second'); extra.set_secret('second-key'); extra.save()
        one = select_key(self.provider, 'round_robin')[1]
        two = select_key(self.provider, 'round_robin')[1]
        self.assertNotEqual(one, two)
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', side_effect=ProviderError('rate_or_quota_limited', 429)) as call:
            with self.assertRaises(ProviderError):
                ai_router.model_complete(self.model, 'prompt', retries=2)
            self.assertEqual(call.call_count, 1)

    def test_rate_limit_cooldown_blocks_all_keys_on_subsequent_requests(self):
        self.provider.rotation_authorized = True; self.provider.save()
        extra = AIProviderKey(provider=self.provider, name='Other'); extra.set_secret('other-secret'); extra.save()
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', side_effect=ProviderError('rate_or_quota_limited', 429, retry_after=120)) as call:
            with self.assertRaises(ProviderError):
                ai_router.model_complete(self.model, 'prompt', key_policy='round_robin')
            with self.assertRaises(ProviderError) as raised:
                ai_router.model_complete(self.model, 'prompt', key_policy='round_robin')
            self.assertEqual(raised.exception.code, 'provider_rate_limit_cooldown')
            self.assertEqual(call.call_count, 1)

    def test_sync_keeps_settings_and_handles_failure_without_deleting_models(self):
        url = self.url('ai-models-sync', provider_id=self.provider.pk)
        rows = [{'model_id': 'discovered-model', 'display_name': 'Discovered', 'output_token_limit': 4000}]
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.discover', return_value=rows):
            response = self.write(url, {})
        self.assertEqual(response.status_code, 200, response.content)
        model = AIModel.objects.get(model_id='discovered-model')
        self.assertFalse(model.is_enabled); self.assertEqual(model.availability, 'untested')
        self.assertEqual(model.output_token_limit, 4000)
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.discover', side_effect=ProviderError('network_error', fallback_allowed=True)):
            self.assertEqual(self.write(url, {}).status_code, 400)
        self.assertTrue(AIModel.objects.filter(pk=self.model.pk).exists())
        self.assertTrue(AIModel.objects.filter(pk=model.pk).exists())

    def test_manual_model_settings_validate_capabilities_and_token_limit(self):
        url = self.url('ai-models', provider_id=self.provider.pk)
        self.assertEqual(self.write(url, {'model_id': 'manual', 'temperature': 0.3}).status_code, 400)
        response = self.write(url, {'model_id': 'manual', 'supports_temperature': True, 'temperature': 0.3, 'max_output_tokens': 50})
        self.assertEqual(response.status_code, 201, response.content)
        self.model.output_token_limit = 100; self.model.save()
        self.assertEqual(self.write(self.model_url(), {'max_output_tokens': 101}, 'patch').status_code, 400)
        self.assertEqual(self.write(self.model_url(), {'retry_count': 10}, 'patch').status_code, 400)

    def test_model_test_returns_actual_result_usage_and_does_not_log_prompt_response(self):
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', return_value=completion('sensitive-response')):
            response = self.write(self.model_url('ai-model-test'), {'prompt': 'sensitive-prompt'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['text'], 'sensitive-response')
        self.assertEqual(response.json()['usage']['total_tokens'], 10)
        self.assertEqual(response.json()['provider_id'], str(self.provider.pk))
        self.model.refresh_from_db(); self.assertEqual(self.model.availability, 'available')
        logs = json.dumps(list(SystemConfigAuditLog.objects.values_list('details', flat=True)))
        self.assertNotIn('sensitive-prompt', logs); self.assertNotIn('sensitive-response', logs)

    def route_payload(self, **changes):
        return {'primary_model': str(self.model.pk), 'key_policy': 'priority', 'is_enabled': True, 'expected_version': 0, 'fallbacks': [], **changes}

    def test_route_save_runtime_caption_and_stale_version_guard(self):
        response = self.write(self.url('ai-route', task='caption_generation'), self.route_payload(), 'put')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.write(self.url('ai-route', task='caption_generation'), self.route_payload(), 'put').status_code, 409)
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', return_value=completion()) as call:
            from modules.publishing.services.caption_engine import _provider
            self.assertEqual(_provider('prompt', model='ignored-old-env-model'), ('Caption đúng Model', 'selected-model'))
            self.assertEqual(call.call_args.kwargs['model'], 'selected-model')
            self.assertEqual(call.call_args.kwargs['api_key'], self.key.get_secret())

    def test_set_default_model_updates_runtime_and_existing_caption_route(self):
        self.write(self.url('ai-route', task='caption_generation'), self.route_payload(), 'put')
        other = AIModel.objects.create(provider=self.provider, model_id='new-default', is_enabled=True)
        response = self.write(self.model_url('ai-model-default', other), {})
        self.assertEqual(response.status_code, 200, response.content)
        route = AIRoute.objects.get(); self.assertEqual(route.primary_model_id, other.pk)
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', return_value=completion(model='new-default')) as call:
            ai_router.route_text('prompt')
        self.assertEqual(call.call_args.kwargs['model'], 'new-default')

    def test_fallback_only_on_temporary_errors_and_never_on_auth_input_security_quota(self):
        backup = AIModel.objects.create(provider=self.provider, model_id='backup-model', is_enabled=True)
        route = AIRoute.objects.create(task='caption_generation', primary_model=self.model, is_enabled=True)
        AIFallback.objects.create(route=route, model=backup, priority=1)
        for error in [ProviderError('timeout', fallback_allowed=True), ProviderError('service_error', 503, True)]:
            with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', side_effect=[error, completion(model='backup-model')]) as call:
                self.assertEqual(ai_router.route_text('prompt')['model'], 'backup-model')
                self.assertEqual(call.call_count, 2)
        for code, status in [('invalid_input', 400), ('authentication_failed', 401), ('access_denied', 403), ('rate_or_quota_limited', 429), ('tls_security_error', None)]:
            AIProvider.objects.filter(pk=self.provider.pk).update(cooldown_until=None)
            with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', side_effect=ProviderError(code, status)) as call:
                with self.assertRaises(ProviderError):
                    ai_router.route_text('prompt')
                self.assertEqual(call.call_count, 1)

    def test_legacy_detect_import_does_not_activate_or_overwrite(self):
        env = {'AI_URL': 'https://api.toolnet.tech/v1', 'AI_KEY': 'env-production-key', 'AI_MODEL': 'agnes/agnes-3.0-flash', 'TOOLNET_CAPTION_API_URL': '', 'TOOLNET_CAPTION_API_KEY': '', 'TOOLNET_CAPTION_MODEL': ''}
        with patch.dict('os.environ', env):
            response = self.client.get(self.url('ai-registry'))
            self.assertNotIn('env-production-key', response.content.decode())
            first = self.write(self.url('ai-import-legacy'), {})
            second = self.write(self.url('ai-import-legacy'), {})
            self.assertEqual(first.json()['id'], second.json()['id'])
            imported = AIProvider.objects.get(pk=first.json()['id'])
            self.assertFalse(imported.is_active); self.assertFalse(imported.is_default)
            self.assertEqual(imported.keys.get().get_secret(), 'env-production-key')
            with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', return_value=completion()) as call:
                ai_router.route_text('prompt')
                self.assertEqual(call.call_args.kwargs['api_key'], 'env-production-key')

    def test_new_migration_preserves_existing_encrypted_credentials(self):
        import importlib
        from django.apps import apps
        old = AIProvider.objects.create(name='Legacy saved', provider_type='toolnet', base_url='https://api.example.test/v1', default_model='legacy-model', available_models=['other-legacy-model'], is_active=True)
        old.set_api_key('existing-encrypted-key'); old.save()
        original = old.api_key_encrypted
        migration = importlib.import_module('modules.system_config.migrations.0004_aiprovider_custom_headers_encrypted_and_more')
        migration.preserve_existing_ai(apps, None)
        migration.preserve_existing_ai(apps, None)
        self.assertEqual(old.keys.count(), 1)
        self.assertEqual(old.keys.get().secret_encrypted, original)
        self.assertEqual(old.keys.get().get_secret(), 'existing-encrypted-key')
        self.assertTrue(old.model_registry.get(model_id='legacy-model').is_enabled)
        self.assertFalse(old.model_registry.get(model_id='other-legacy-model').is_enabled)

    def test_all_new_api_permissions_and_csrf(self):
        urls = [self.url('ai-registry'), self.url('ai-providers'), self.url('ai-provider', provider_id=self.provider.pk), self.url('ai-keys', provider_id=self.provider.pk), self.url('ai-models', provider_id=self.provider.pk), self.url('ai-routes')]
        ctv = get_user_model().objects.create_user('ctv')
        self.client.force_login(ctv)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)
        for name, kwargs in [('ai-provider-test', {'provider_id': self.provider.pk}), ('ai-models-sync', {'provider_id': self.provider.pk}), ('ai-model-test', {'provider_id': self.provider.pk, 'model_id': self.model.pk}), ('ai-key-test', {'provider_id': self.provider.pk, 'key_id': self.key.pk}), ('ai-import-legacy', {})]:
            self.assertEqual(self.write(self.url(name, **kwargs), {}).status_code, 403)
        client = Client(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(self.url('ai-providers'), {}).status_code, 403)

    def test_audit_failure_rolls_back_provider_and_managed_key(self):
        before = AIProviderKey.objects.count()
        with patch('modules.api.v1.system_config.views.SystemConfigAuditLog.objects.create', side_effect=RuntimeError('sensitive')):
            response = self.write(self.url('ai-providers'), {'name': 'Rollback', 'provider_type': 'toolnet', 'base_url': 'https://api.toolnet.tech/v1', 'api_key': 'dont-log'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(AIProviderKey.objects.count(), before)
        self.assertFalse(AIProvider.objects.filter(name='Rollback').exists())


class ProtocolTests(TestCase):
    def response(self, data):
        response = MagicMock(); response.status = 200
        response.read.return_value = json.dumps(data).encode()
        response.__enter__.return_value = response
        return response

    def test_gemini_uses_header_key_and_native_model_parameters(self):
        opened = MagicMock(return_value=self.response({'candidates': [{'content': {'parts': [{'text': 'OK'}]}}], 'usageMetadata': {'totalTokenCount': 3}}))
        result = Protocol('gemini', opened).complete(base_url='https://generativelanguage.googleapis.com/v1beta', api_key='private', model='gemini-test', prompt='prompt', settings={'max_output_tokens': 10})
        request = opened.call_args.args[0]
        self.assertNotIn('private', request.full_url)
        self.assertEqual(request.get_header('X-goog-api-key'), 'private')
        payload = json.loads(request.data)
        self.assertEqual(payload['generationConfig'], {'maxOutputTokens': 10})
        self.assertEqual(result['usage']['totalTokenCount'], 3)

    def test_openai_does_not_assume_sampling_and_respects_token_parameter(self):
        opened = MagicMock(return_value=self.response({'choices': [{'message': {'content': 'OK private'}}], 'usage': {'private': 99, 'total_tokens': 3}}))
        result = Protocol('openai', opened).complete(base_url='https://api.example.test/v1', api_key='private', model='reasoning-model', prompt='prompt', settings={'max_output_tokens': 20, 'token_parameter': 'max_completion_tokens'})
        payload = json.loads(opened.call_args.args[0].data)
        self.assertNotIn('temperature', payload); self.assertNotIn('top_p', payload)
        self.assertEqual(payload['max_completion_tokens'], 20)
        self.assertNotIn('private', result['text'])
        self.assertNotIn('private', result['usage'])

    def test_discovery_follows_native_pagination_and_never_creates_fake_models(self):
        for kind, pages, cursor_field in [
            ('gemini', [{'models': [{'name': 'models/one'}], 'nextPageToken': 'next'}, {'models': [{'name': 'models/two'}]}], 'pageToken=next'),
            ('anthropic', [{'data': [{'id': 'one'}], 'has_more': True, 'last_id': 'one'}, {'data': [{'id': 'two'}], 'has_more': False}], 'after_id=one'),
            ('openai', [{'data': [{'id': 'one'}], 'has_more': True}, {'data': [{'id': 'two'}]}], 'after=one')]:
            opened = MagicMock(side_effect=[self.response(data) for data in pages])
            rows = Protocol(kind, opened).discover(base_url='https://api.example.test/v1' if kind != 'gemini' else 'https://api.example.test/v1beta', api_key='private')
            self.assertEqual([row['model_id'] for row in rows], ['one', 'two'])
            self.assertIn(cursor_field, opened.call_args.args[0].full_url)

        opened = MagicMock(return_value=self.response({'data': [{'id': 'one'}], 'has_more': True, 'last_id': 'private'}))
        with self.assertRaises(ProviderError):
            Protocol('openai', opened).discover(base_url='https://api.example.test/v1', api_key='private')
        self.assertEqual(opened.call_count, 1)

    def test_error_bodies_never_escape_and_http_status_controls_fallback(self):
        for status in [400, 401, 403, 404, 429, 500, 503]:
            error = HTTPError('https://example.test', status, 'ignored', {}, io.BytesIO(b'authorization=private-key'))
            with self.assertRaises(ProviderError) as raised:
                Protocol('openai', MagicMock(side_effect=error)).complete(base_url='https://example.test', api_key='private-key', model='m', prompt='prompt')
            self.assertNotIn('private-key', str(raised.exception))
            self.assertEqual(raised.exception.fallback_allowed, status in [500, 503])


class CaptionRouterIntegrationTests(TestCase):
    setUp = AIRegistryTests.setUp
    url = AIRegistryTests.url
    write = AIRegistryTests.write
    model_url = AIRegistryTests.model_url
    def test_full_caption_creation_keeps_destination_and_pipeline_isolation(self):
        from django.utils import timezone
        from modules.pipelines.models import Pipeline
        from modules.facebook_accounts.models import FacebookAccount
        from modules.facebook_groups.models import FacebookGroup
        from modules.publishing.models import PublishingJob
        from modules.publishing.caption_models import JobCaption, CaptionRevision, CaptionSample, PipelineCaptionSettings
        from modules.publishing.services.caption_engine import generate_job_caption, approve_job_caption, CaptionConflict
        ctv = get_user_model().objects.create_user('isolated-caption-owner')
        pipeline = Pipeline.objects.create(name='Isolated Caption Pipeline', ctv=ctv)
        account = FacebookAccount.objects.create(pipeline=pipeline, label='Isolated account')
        group = FacebookGroup.objects.create(pipeline=pipeline, name='Isolated Group', group_url='https://facebook.com/groups/isolated/')
        PipelineCaptionSettings.objects.create(pipeline=pipeline, destination='@hiu9h', enabled=True)
        CaptionSample.objects.create(pipeline=pipeline, text='Một mẫu caption tích cực và đủ dài để AI tham khảo.', created_by=ctv)
        def job(key):
            return PublishingJob.objects.create(pipeline=pipeline, facebook_account=account, facebook_group=group, request_key=key, state='queued', scheduled_at=timezone.now(), next_run_at=timezone.now())
        first = job('isolated-first')
        route = AIRoute.objects.create(task='caption_generation', primary_model=self.model, is_enabled=True)
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', return_value=completion('Ngày mới với nhiều niềm vui.')):
            payload = generate_job_caption(pipeline_id=pipeline.pk, job_id=first.pk, actor=ctv)
        self.assertEqual(payload['model'], 'selected-model')
        self.assertEqual(payload['text'].count('@hiu9h'), 1)
        row = JobCaption.objects.get(job=first)
        approve_job_caption(pipeline_id=pipeline.pk, job_id=first.pk, actor=ctv, expected_revision=row.revision)
        row.refresh_from_db(); approved = (row.text, row.state, row.revision, row.destination_snapshot)
        new_model = AIModel.objects.create(provider=self.provider, model_id='next-model', is_enabled=True)
        response = self.write(self.model_url('ai-model-default', new_model), {})
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db(); self.assertEqual((row.text, row.state, row.revision, row.destination_snapshot), approved)
        second = job('isolated-second')
        with patch('modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.complete', return_value=completion('Một nội dung mới khác biệt.', 'next-model')) as call:
            payload = generate_job_caption(pipeline_id=pipeline.pk, job_id=second.pk, actor=ctv)
        self.assertEqual(call.call_args.kwargs['model'], 'next-model')
        self.assertEqual(payload['model'], 'next-model')
        self.assertEqual(JobCaption.objects.filter(job=second).count(), 1)
        other = get_user_model().objects.create_user('different-caption-ctv')
        foreign = Pipeline.objects.create(name='Other isolated pipeline', ctv=other)
        with self.assertRaises(CaptionConflict):
            generate_job_caption(pipeline_id=foreign.pk, job_id=second.pk, actor=other)
        self.assertFalse(JobCaption.objects.filter(pipeline=foreign).exists())
