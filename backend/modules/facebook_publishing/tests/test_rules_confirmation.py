from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from django.test import SimpleTestCase

from modules.facebook_publishing.services.rules_confirmation import inspect_rules_prompt
from modules.facebook_publishing.services.verification import PublishingVerification


def mock_page(dialog_text=None):
    page = MagicMock()
    dialogs = MagicMock()
    dialogs.count.return_value = 0 if dialog_text is None else 1
    headings = MagicMock()
    headings.count.return_value = 0
    page.get_by_role.side_effect = lambda role, **kwargs: headings if role == 'heading' else dialogs
    dialog = dialogs.nth.return_value
    dialog.is_visible.return_value = True
    dialog.inner_text.return_value = dialog_text
    boxes = dialog.get_by_role.return_value
    boxes.count.return_value = 2
    boxes.nth.side_effect = [MagicMock(is_checked=lambda: True), MagicMock(is_checked=lambda: False)]
    fields = dialog.locator.return_value
    fields.count.return_value = 1
    fields.nth.return_value.is_visible.return_value = True
    return page


class RulesPromptTests(SimpleTestCase):
    def test_no_dialog_returns_immediately_without_waiting_or_clicking(self):
        page = mock_page()
        self.assertIsNone(inspect_rules_prompt(page))
        page.wait_for_timeout.assert_not_called()
        page.get_by_role('dialog').nth.return_value.click.assert_not_called()

    def test_unrelated_dialog_is_not_a_rules_prompt(self):
        page = mock_page('Do you want to send this message?')
        self.assertIsNone(inspect_rules_prompt(page))

    @patch('modules.facebook_publishing.services.rules_confirmation.tempfile.mkdtemp', side_effect=OSError)
    def test_vietnamese_prompt_is_inspected_without_accepting(self, _):
        page = mock_page('Câu hỏi dành cho người tham gia\nĐồng ý với các quy tắc nhóm\nGửi')
        result = inspect_rules_prompt(page)
        self.assertEqual((result.checkbox_count, result.checked_count, result.response_field_count), (2, 1, 1))
        self.assertEqual(len(result.digest), 64)
        page.get_by_role('dialog').nth.return_value.click.assert_not_called()

    @patch('modules.facebook_publishing.services.rules_confirmation.tempfile.mkdtemp', side_effect=OSError)
    def test_english_prompt_detected(self, _):
        result = inspect_rules_prompt(mock_page('Membership questions\nAgree to group rules\nSubmit'))
        self.assertIsNotNone(result)

    @patch('modules.facebook_publishing.services.rules_confirmation.inspect_rules_prompt')
    def test_prompt_appearing_while_feed_loads_is_returned(self, inspect):
        prompt = object()
        inspect.side_effect = [None, prompt]
        page = MagicMock()
        page.wait_for_selector.side_effect = TimeoutError()
        result = PublishingVerification(page, SimpleNamespace(browser_timeout_seconds=10),
                                        monitor_rules=True).verify_post_visibility()
        self.assertEqual(result.state, 'RULES_CONFIRMATION_REQUIRED')
        self.assertIs(result.rules_prompt, prompt)
        page.wait_for_selector.assert_called_once()

    def test_matching_post_requires_visible_media_and_matching_group_link(self):
        page = MagicMock()
        page.url = 'https://www.facebook.com/groups/123/'
        page.inner_text.return_value = ''
        article, image, link = MagicMock(), MagicMock(), MagicMock()
        article.is_visible.return_value = True
        article.inner_text.return_value = 'Approved caption with exact text'
        image.is_visible.return_value = True
        image.evaluate.return_value = True
        link.get_attribute.return_value = '/groups/123/posts/456/'
        article.query_selector_all.side_effect = lambda selector: [image] if selector == 'img' else [link]
        page.query_selector_all.return_value = [article]
        result = PublishingVerification(page, SimpleNamespace(browser_timeout_seconds=1),
            expected_caption='Approved caption with exact text').verify_post_visibility()
        self.assertEqual((result.state, result.external_post_id), ('PUBLISHED', '456'))
        image.is_visible.return_value = False
        result = PublishingVerification(page, SimpleNamespace(browser_timeout_seconds=1),
            expected_caption='Approved caption with exact text').verify_post_visibility()
        self.assertEqual(result.state, 'SUBMITTED_UNVERIFIED')

    def test_matching_caption_does_not_accept_other_group_link(self):
        page = MagicMock()
        page.url = 'https://www.facebook.com/groups/123/'
        page.inner_text.return_value = ''
        article, image, link = MagicMock(), MagicMock(), MagicMock()
        article.is_visible.return_value = True
        article.inner_text.return_value = 'Exact caption'
        image.is_visible.return_value = True
        image.evaluate.return_value = True
        link.get_attribute.return_value = '/groups/other/posts/456/'
        article.query_selector_all.side_effect = lambda selector: [image] if selector == 'img' else [link]
        page.query_selector_all.return_value = [article]
        result = PublishingVerification(page, SimpleNamespace(browser_timeout_seconds=1),
            expected_caption='Exact caption').verify_post_visibility()
        self.assertEqual(result.state, 'SUBMITTED_UNVERIFIED')
