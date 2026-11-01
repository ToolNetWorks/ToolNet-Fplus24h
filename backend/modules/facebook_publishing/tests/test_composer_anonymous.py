from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from modules.facebook_publishing.services.composer import AnonymousComposer


class AnonymousIdentityTests(SimpleTestCase):
    def setUp(self):
        self.page = MagicMock()
        self.composer = AnonymousComposer(self.page, SimpleNamespace(dry_run=True), 'Hanh Bui')

    def test_finds_unlabelled_switch_only_when_row_is_anonymous(self):
        switches = self.page.get_by_role.return_value
        switches.count.return_value = 1
        switches.first.is_visible.return_value = True
        switches.first.evaluate.return_value = 'Post as an anonymous member'
        self.assertTrue(self.composer.check_anonymous_posting_available())
        switches.first.evaluate.return_value = 'Allow notifications'
        self.assertFalse(self.composer.check_anonymous_posting_available())

    def test_unknown_switch_state_fails_closed_without_click(self):
        switch = MagicMock()
        switch.get_attribute.return_value = None
        with patch.object(self.composer, '_anonymous_switch', return_value=switch):
            result = self.composer.activate_anonymous()
        self.assertFalse(result.success)
        switch.click.assert_not_called()

    def test_checked_switch_requires_composer_identity(self):
        switch = MagicMock()
        switch.get_attribute.return_value = 'false'
        with patch.object(self.composer, '_anonymous_switch', side_effect=[switch, None]), \
                patch.object(self.composer, 'is_anonymous_enabled', return_value=False):
            result = self.composer.activate_anonymous()
        switch.click.assert_called_once()
        self.assertFalse(result.success)
        self.assertEqual(result.detail, 'ANONYMOUS_AUTHOR_UNCONFIRMED')

    def test_checked_switch_and_anonymous_author_succeed(self):
        switch = MagicMock()
        switch.get_attribute.return_value = 'false'
        self.page.get_by_role.return_value.filter.return_value.count.return_value = 0
        with patch.object(self.composer, '_anonymous_switch', side_effect=[switch, None]), \
                patch.object(self.composer, 'is_anonymous_enabled', return_value=True):
            result = self.composer.activate_anonymous()
        switch.click.assert_called_once()
        self.assertTrue(result.success)
