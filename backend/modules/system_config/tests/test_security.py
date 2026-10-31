import json
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from modules.system_config.models import AIProvider, StorageConfig, SystemConfigAuditLog
from modules.system_config.services.ai_unified_service import generate_ai_text
from modules.system_config.services.r2_service import test_r2_connection
from modules.system_config.serializers import AIProviderSerializer


class ConfigurationSecurityTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('config-admin', 'admin@example.test', 'test-password')
        self.client.force_login(self.admin)
        self.list_url = reverse('admin-config-ai-providers')
        self.payload = dict(name='Provider', provider_type='openai', base_url='https://api.example.test/v1', default_model='new-model', api_key='arbitrary-private-key-value', is_default=True)

    def create_provider(self):
        response = self.client.post(self.list_url, self.payload)
        self.assertEqual(response.status_code, 201, response.content)
        return AIProvider.objects.get(pk=response.json()['id'])

    def test_secret_fields_never_returned_or_audited(self):
        p = self.create_provider()
        self.assertEqual(p.get_api_key(), self.payload['api_key'])
        self.assertNotIn(self.payload['api_key'], p.api_key_encrypted)
        body = self.client.get(self.list_url).content.decode()
        self.assertNotIn(self.payload['api_key'], body)
        self.assertNotIn(p.api_key_encrypted, body)
        for log in SystemConfigAuditLog.objects.all():
            self.assertNotIn(self.payload['api_key'], json.dumps(log.details))

    def test_invalid_input_is_400(self):
        for change in ({'priority': 'invalid'}, {'timeout_seconds': 0}, {'base_url': 'http://insecure.test'}, {'base_url': 'https://user:secret@host.test'}, {'provider_type': 'invalid'}, {'is_active': False}):
            response = self.client.post(self.list_url, {**self.payload, **change})
            self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(AIProvider.objects.exists())

    def test_raw_ciphertext_fields_cannot_bypass_encryption(self):
        serializer = AIProviderSerializer(data={**self.payload, 'api_keys_encrypted': 'plaintext-secret'})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        p = serializer.save()
        self.assertEqual(p.api_keys_encrypted, '')

    def test_audit_failure_rolls_back_mutation(self):
        with patch('modules.api.v1.system_config.views.SystemConfigAuditLog.objects.create', side_effect=RuntimeError('secret-value')):
            response = self.client.post(self.list_url, self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret-value', response.content.decode())
        self.assertFalse(AIProvider.objects.exists())

    def test_default_priority_and_caption_engine_integration(self):
        p = self.create_provider()
        p.priority = 90
        p.save()
        AIProvider.objects.create(name='fallback', base_url='https://fallback.test', default_model='fallback', priority=1)
        with patch('modules.system_config.services.ai_unified_service.OpenAICompatibleAdapter.generate_completion', return_value=('caption', 'new-model')) as generate:
            from modules.publishing.services.caption_engine import _provider
            self.assertEqual(_provider('prompt', model='old-production-model'), ('caption', 'new-model'))
            self.assertEqual(generate.call_args.kwargs['model'], 'new-model')
            self.assertEqual(generate.call_args.kwargs['base_url'], p.base_url)

    def test_revoked_key_is_not_replaced_with_environment_key(self):
        p = self.create_provider()
        p.api_key_encrypted = ''
        p.save()
        with patch('modules.system_config.services.ai_unified_service.OpenAICompatibleAdapter.generate_completion', return_value=('caption', 'env-model')) as generate, patch.dict('os.environ', {'AI_URL': 'https://environment.test', 'AI_KEY': 'env-private', 'AI_MODEL': 'env-model', 'TOOLNET_CAPTION_API_URL': '', 'TOOLNET_CAPTION_API_KEY': '', 'TOOLNET_CAPTION_MODEL': ''}):
            generate_ai_text('prompt')
            self.assertEqual(generate.call_args.kwargs['base_url'], 'https://environment.test')

    def test_staff_only_and_superuser_only_denied_all_mutations(self):
        p = self.create_provider()
        for flags in ({'is_staff': True}, {'is_superuser': True}, {}):
            user = get_user_model().objects.create_user(username=f'user-{len(get_user_model().objects.all())}', **flags)
            self.client.force_login(user)
            for url in (self.list_url, reverse('admin-config-r2'), reverse('admin-config-database'), reverse('admin-config-ai-provider-test', kwargs={'provider_id': p.id}), reverse('admin-config-ai-provider-set-default', kwargs={'provider_id': p.id})):
                self.assertEqual(self.client.post(url, {}).status_code, 403)
            self.assertEqual(self.client.delete(reverse('admin-config-ai-provider-detail', kwargs={'provider_id': p.id})).status_code, 403)

    def test_r2_encryption_and_probe_cleanup(self):
        cfg = StorageConfig(bucket_name='isolated-test')
        cfg.set_access_key('private-access-id')
        cfg.set_secret_key('private-secret-key')
        cfg.save()
        self.assertNotIn('private-access-id', cfg.access_key_id)
        self.assertEqual(cfg.get_access_key(), 'private-access-id')
        client = MagicMock()
        client.get_object.return_value = {'Body': MagicMock(read=MagicMock(return_value=b'TOOLNET_R2_PROBE_OK'))}
        with patch('modules.system_config.services.r2_service.boto3.client', return_value=client):
            result = test_r2_connection({'endpoint_url': 'https://r2.example.test', 'access_key_id': 'id', 'secret_access_key': 'secret', 'bucket_name': 'isolated-test'}, True)
        self.assertTrue(result['success'])
        written = client.put_object.call_args.kwargs['Key']
        self.assertTrue(written.startswith('.probe/'))
        client.delete_object.assert_called_once_with(Bucket='isolated-test', Key=written)

    def test_environment_remains_primary_until_default_selected(self):
        p = self.create_provider()
        p.is_default = False
        p.save()
        with patch.dict('os.environ', {'AI_URL': 'https://environment.test', 'AI_KEY': 'environment-key', 'AI_MODEL': 'environment-model', 'TOOLNET_CAPTION_API_URL': '', 'TOOLNET_CAPTION_API_KEY': '', 'TOOLNET_CAPTION_MODEL': ''}), patch('modules.system_config.services.ai_unified_service.OpenAICompatibleAdapter.generate_completion', return_value=('caption', 'environment-model')) as generate:
            generate_ai_text('prompt')
            self.assertEqual(generate.call_args.kwargs['base_url'], 'https://environment.test')
            self.assertEqual(generate.call_count, 1)

    def test_r2_save_toggle_and_reset_audited(self):
        payload = {'endpoint_url': 'https://account.r2.cloudflarestorage.com', 'bucket_name': 'isolated', 'access_key_id': 'private-access', 'secret_access_key': 'private-secret'}
        url = reverse('admin-config-r2')
        with patch('modules.api.v1.system_config.views.test_r2_connection', return_value={'success': True, 'latency_ms': 1}):
            response = self.client.post(url, payload)
            self.assertEqual(response.status_code, 200, response.content)
        cfg = StorageConfig.objects.get()
        self.assertEqual(cfg.get_access_key(), payload['access_key_id'])
        self.assertNotIn('private-access', response.content.decode())
        self.assertNotIn('private-secret', response.content.decode())
        response = self.client.patch(url, json.dumps({'is_active': False}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        cfg.refresh_from_db()
        self.assertFalse(cfg.is_active)
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertFalse(StorageConfig.objects.exists())
        self.assertEqual(SystemConfigAuditLog.objects.filter(section='r2').count(), 3)

    def test_csrf_required_for_mutation(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.list_url, self.payload).status_code, 403)

    def test_adapter_errors_never_reflect_upstream_secrets(self):
        import io
        from urllib.error import HTTPError
        from modules.system_config.services.ai_unified_service import test_provider_connection
        secret = 'random-key-cookie-token-not-matching-any-pattern'
        for adapter_name, provider_type in [('openai_adapter', 'openai'), ('anthropic_adapter', 'anthropic'), ('gemini_adapter', 'gemini')]:
            failure = HTTPError('https://example.test', 401, 'Unauthorized', {}, io.BytesIO(json.dumps({'error': {'message': secret}}).encode()))
            with patch(f'modules.system_config.services.adapters.{adapter_name}.urlopen', side_effect=failure):
                result = test_provider_connection(provider_type, 'https://example.test', secret, 'model')
            self.assertFalse(result['success'])
            self.assertNotIn(secret, json.dumps(result))
