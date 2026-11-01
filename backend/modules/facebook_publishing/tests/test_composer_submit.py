from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from modules.facebook_publishing.services.composer import (
    AnonymousComposer, AnonymousComposerError,
)


class ComposerSubmitTests(SimpleTestCase):
    def test_click_failure_never_attempts_another_button(self):
        page = MagicMock()
        dialog = MagicMock()
        buttons = dialog.get_by_role.return_value
        buttons.count.return_value = 1
        first = MagicMock()
        first.is_visible.return_value = True
        first.is_enabled.return_value = True
        first.click.side_effect = TimeoutError('ambiguous click result')
        buttons.first = first

        from unittest.mock import patch
        with patch.object(AnonymousComposer, '_composer_dialog', return_value=dialog), self.assertRaises(AnonymousComposerError):
            AnonymousComposer(page, SimpleNamespace(dry_run=False)).submit_post()

        first.click.assert_called_once()
        self.assertEqual(dialog.get_by_role.call_count, 1)
