import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.facebook_accounts.upload_views import FacebookCookieReplaceAPIView
from modules.facebook_accounts.models import FacebookCookieSecret
from modules.facebook_publishing.tests.test_worker import FacebookPublishingWorkerTestBase
from modules.publishing.models import PublishingJob


def cookie_file(uid='123'):
    payload = {'url': 'https://www.facebook.com/', 'cookies': [
        {'name': 'c_user', 'value': uid, 'domain': '.facebook.com', 'secure': True},
        {'name': 'xs', 'value': 'test-secret', 'domain': '.facebook.com', 'secure': True},
    ]}
    return SimpleUploadedFile('cookies.json', json.dumps(payload).encode(), content_type='application/json')


class CookieReplaceTests(FacebookPublishingWorkerTestBase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.secret = FacebookCookieSecret.objects.create(account=self.account,
            ciphertext='old-encrypted-value', cookie_count=2)

    def send(self, user, file):
        request = self.factory.post('/cookie/', {'file': file}, format='multipart')
        force_authenticate(request, user=user)
        return FacebookCookieReplaceAPIView.as_view()(request, pipeline_id=self.pipeline.pk,
                                                      account_id=self.account.pk)

    @patch('modules.api.v1.facebook_accounts.upload_views.encrypt_cookies', return_value='new-encrypted-value')
    def test_owner_updates_existing_account_and_clears_verified_status(self, _encrypt):
        self.account.facebook_user_id = '123'
        self.account.last_verified_at = timezone.now()
        self.account.save()
        response = self.send(self.ctv, cookie_file())
        self.assertEqual(response.status_code, 200)
        self.account.refresh_from_db(); self.secret.refresh_from_db()
        self.assertEqual(self.account.connection_status, 'not_connected')
        self.assertIsNone(self.account.last_verified_at)
        self.assertEqual(self.secret.ciphertext, 'new-encrypted-value')
        self.assertNotIn('test-secret', str(response.data))

    @patch('modules.api.v1.facebook_accounts.upload_views.encrypt_cookies', return_value='new-encrypted-value')
    def test_foreign_user_cannot_replace_cookie(self, _encrypt):
        response = self.send(self.other_ctv, cookie_file())
        self.assertEqual(response.status_code, 404)
        self.secret.refresh_from_db()
        self.assertEqual(self.secret.ciphertext, 'old-encrypted-value')

    @patch('modules.api.v1.facebook_accounts.upload_views.encrypt_cookies', return_value='new-encrypted-value')
    def test_unresolved_job_blocks_replacement(self, _encrypt):
        job = self._create_job()
        job.state = PublishingJob.State.UNCERTAIN
        job.save()
        response = self.send(self.ctv, cookie_file())
        self.assertEqual(response.status_code, 409)
        self.secret.refresh_from_db()
        self.assertEqual(self.secret.ciphertext, 'old-encrypted-value')

    @patch('modules.api.v1.facebook_accounts.upload_views.encrypt_cookies', return_value='new-encrypted-value')
    def test_cookie_for_different_verified_id_is_rejected(self, _encrypt):
        self.account.facebook_user_id = '123'
        self.account.save()
        response = self.send(self.ctv, cookie_file('456'))
        self.assertEqual(response.status_code, 400)
        self.secret.refresh_from_db()
        self.assertEqual(self.secret.ciphertext, 'old-encrypted-value')
