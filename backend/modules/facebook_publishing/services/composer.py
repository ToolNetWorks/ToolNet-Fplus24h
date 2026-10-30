"""Anonymous composer adapter for the Facebook Publishing Worker.

Interacts with the Facebook Groups UI via Playwright to:
- Navigate to the group
- Activate the anonymous posting toggle
- Fill the caption text
- Attach the staged image
- (In non-dry-run mode) Submit the post

Never replays private GraphQL requests from the HAR.
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ComposerActionResult:
    action: str
    success: bool
    detail: Optional[str] = None


class AnonymousComposerError(Exception):
    pass


class AnonymousComposer:
    """Adapter that drives the Facebook Groups composer through the browser UI."""

    def __init__(self, page, settings):
        self._page = page
        self._settings = settings

    def _log(self, message):
        """Log without exposing any sensitive values."""
        logger.info('Composer: %s', message)

    def navigate_to_group(self, group_url: str):
        """Navigate to the Facebook Group page."""
        if not group_url.startswith('https://www.facebook.com/groups/'):
            raise AnonymousComposerError('Invalid group URL format.')
        self._page.goto(group_url, timeout=self._settings.browser_timeout_seconds * 1000)
        self._page.wait_for_timeout(1000)
        self._log('Navigated to group')
        return ComposerActionResult('navigate_to_group', True)

    def check_anonymous_posting_available(self) -> bool:
        """Check if the anonymous posting option is available on this Group."""
        try:
            selectors = [
                '[aria-label*="ẩn danh"]',
                '[aria-label*="anonymous"]',
                'input[name*="anonymous"]',
                '.composer-anonymous-toggle',
                'button[data-testid="composer_anonymously_toggle"]',
                'div[role="switch"][aria-label*="ẩn danh"]',
            ]
            for sel in selectors:
                el = self._page.query_selector(sel)
                if el is not None:
                    self._log('Anonymous posting toggle found')
                    return True
            self._log('No anonymous posting toggle selector matched')
            return False
        except Exception:
            self._log('Error checking anonymous toggle, assuming unavailable')
            return False

    def activate_anonymous(self) -> ComposerActionResult:
        """Activate the anonymous posting toggle in the composer."""
        if not self.check_anonymous_posting_available():
            raise AnonymousComposerError(
                'Anonymous posting toggle not found. Account may lack permission.'
            )
        try:
            selectors = [
                '[aria-label*="ẩn danh"]',
                '[aria-label*="anonymous"]',
                'button[data-testid="composer_anonymously_toggle"]',
                'div[role="switch"][aria-label*="ẩn danh"]',
            ]
            for sel in selectors:
                el = self._page.query_selector(sel)
                if el is not None:
                    el.click()
                    self._page.wait_for_timeout(500)
                    self._log('Anonymous toggle activated')
                    return ComposerActionResult('activate_anonymous', True)
            raise AnonymousComposerError('Anonymous toggle element not clickable.')
        except Exception as exc:
            raise AnonymousComposerError(
                f'Failed to activate anonymous posting: {exc}'
            ) from exc

    def fill_caption(self, caption: str):
        """Fill the caption text into the composer."""
        if not caption or len(caption.strip()) < 8:
            raise AnonymousComposerError('Caption must be at least 8 characters.')
        if len(caption) > 5000:
            raise AnonymousComposerError('Caption exceeds 5000 characters.')
        self._log('Filling caption')
        try:
            self._page.fill('div[role="textbox"]', caption, timeout=30000)
            self._page.wait_for_timeout(500)
            return ComposerActionResult('fill_caption', True)
        except Exception as exc:
            raise AnonymousComposerError(f'Failed to fill caption: {exc}') from exc

    def attach_image(self, image_path: str):
        """Attach a staged image file to the composer via native file input."""
        self._log('Attaching image')
        try:
            file_input = self._page.query_selector(
                'input[type="file"][accept*="image"], '
                'input[type="file"].composer_image_input, '
                'input[type="file"][name*="file"]'
            )
            if file_input is None:
                file_input = self._page.wait_for_selector(
                    'input[type="file"]', timeout=10000,
                )
            file_input.set_input_files(image_path, timeout=30000)
            self._page.wait_for_timeout(2000)
            return ComposerActionResult('attach_image', True)
        except Exception as exc:
            raise AnonymousComposerError(f'Failed to attach image: {exc}') from exc

    def submit_post(self) -> ComposerActionResult:
        """Submit the post by clicking the Post button.

        Called ONLY when dry_run is False. In dry_run mode, this must NOT be called.
        """
        if self._settings.dry_run:
            raise AnonymousComposerError(
                'Cannot submit post in DRY_RUN mode.'
            )
        self._log('Submitting post')
        try:
            post_buttons = [
                'button[type="submit"][value*="Đăng"]',
                'button[type="submit"][value*="Post"]',
                'div[role="button"][aria-label*="Đăng"]',
                'div[role="button"][aria-label*="Post"]',
                'button[data-testid="composer_post_button"]',
            ]
            for sel in post_buttons:
                btn = self._page.query_selector(sel)
                if btn is not None:
                    btn.click()
                    self._page.wait_for_timeout(1000)
                    return ComposerActionResult('submit_post', True)
            raise AnonymousComposerError('Post button not found.')
        except Exception as exc:
            raise AnonymousComposerError(f'Failed to submit post: {exc}') from exc

    def capture_composer_state(self) -> dict:
        """Capture relevant UI state for verification (no sensitive data)."""
        try:
            visible_text = self._page.inner_text('body') or ''
            has_pending = 'pending' in visible_text.lower() or 'chờ duyệt' in visible_text.lower()
            has_error = 'lỗi' in visible_text.lower() or 'error' in visible_text.lower()
            return {
                'has_pending_approval': has_pending,
                'has_error': has_error,
                'page_title': self._page.title(),
            }
        except Exception:
            return {'has_pending_approval': False, 'has_error': False, 'page_title': ''}
