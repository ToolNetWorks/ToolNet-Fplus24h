from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework.test import APIClient

from modules.facebook_accounts.models import FacebookAccount, FacebookCookieSecret
from modules.facebook_publishing.models import ConnectionMode
from modules.facebook_publishing.tests.test_worker import FacebookPublishingWorkerTestBase


class FacebookSessionVerifyTests(FacebookPublishingWorkerTestBase):
    def setUp(self):
        super().setUp()
        self.config.connection_mode = ConnectionMode.DIRECT
        self.config.save()
        self.account.connection_status = FacebookAccount.ConnectionStatus.NOT_CONNECTED
        self.account.save()
        FacebookCookieSecret.objects.create(account=self.account, ciphertext='encrypted-value', cookie_count=2)
        self.client = APIClient()
        self.client.force_authenticate(self.ctv)
        self.url = reverse('facebook-session-verify', kwargs={'pipeline_id': self.pipeline.pk, 'account_id': self.account.pk})

    @patch('modules.api.v1.facebook_accounts.verify_views.inspect_session', return_value='verified')
    def test_verified_session_updates_connection(self, inspect):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['result'], 'verified')
        self.account.refresh_from_db()
        self.assertEqual(self.account.connection_status, FacebookAccount.ConnectionStatus.CONNECTED)
        self.assertIsNotNone(self.account.last_verified_at)
        self.assertNotIn('encrypted-value', str(response.data))
        inspect.assert_called_once()

    @patch('modules.api.v1.facebook_accounts.verify_views.inspect_session', return_value='identity_unverified')
    def test_unverified_name_does_not_connect(self, inspect):
        response = self.client.post(self.url)
        self.assertEqual(response.data['result'], 'identity_unverified')
        self.account.refresh_from_db()
        self.assertEqual(self.account.connection_status, FacebookAccount.ConnectionStatus.NOT_CONNECTED)

    @patch('modules.api.v1.facebook_accounts.verify_views.inspect_session', return_value='expired')
    def test_expired_session_marks_expired(self, inspect):
        response = self.client.post(self.url)
        self.assertEqual(response.data['result'], 'expired')
        self.account.refresh_from_db()
        self.assertEqual(self.account.connection_status, FacebookAccount.ConnectionStatus.EXPIRED)

    @patch('modules.api.v1.facebook_accounts.verify_views.inspect_session')
    def test_other_ctv_cannot_test_account(self, inspect):
        self.client.force_authenticate(self.other_ctv)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 404)
        inspect.assert_not_called()

    @patch('modules.api.v1.facebook_accounts.verify_views.inspect_session')
    def test_cookie_changed_during_check_does_not_connect(self, inspect):
        def replace(*args):
            FacebookCookieSecret.objects.filter(account=self.account).update(ciphertext='new-value')
            return 'verified'
        inspect.side_effect = replace
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 409)
        self.account.refresh_from_db()
        self.assertEqual(self.account.connection_status, FacebookAccount.ConnectionStatus.NOT_CONNECTED)

    @patch('modules.api.v1.facebook_accounts.verify_views.BrowserManager')
    def test_session_inspection_loads_cookie_relation_before_browser(self, manager_class):
        from modules.api.v1.facebook_accounts.verify_views import inspect_session
        from modules.facebook_publishing.services.config import WorkerSettings
        account = FacebookAccount.objects.get(pk=self.account.pk)
        manager = manager_class.return_value
        context = MagicMock()
        manager.launch_context.side_effect = lambda **kwargs: (
            self.assertIn('cookie_secret', account._state.fields_cache) or context
        )
        manager.load_account_cookies.return_value = (True, 2)
        manager.verify_account_identity.return_value = True
        page = context.new_page.return_value
        page.url = 'https://www.facebook.com/'
        page.get_by_text.return_value.count.return_value = 0
        page.locator.return_value.count.return_value = 0
        menu = page.get_by_role.return_value
        menu.count.return_value = 1
        menu.first.is_visible.return_value = True
        self.assertEqual(inspect_session(account, WorkerSettings(enabled=True), None), 'verified')
        manager.close_context.assert_called_once_with(context)
        manager.shutdown.assert_called_once()
