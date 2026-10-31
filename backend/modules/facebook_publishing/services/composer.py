"""Anonymous composer adapter for the Facebook Publishing Worker.

Interacts with the Facebook Groups composer through the browser UI:
- Navigate to the group
- Open the composer (create-post button)
- Activate the anonymous posting toggle inside the composer
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
        self._page.wait_for_timeout(2000)
        self._log('Navigated to group')
        return ComposerActionResult('navigate_to_group', True)

    def open_composer(self) -> ComposerActionResult:
        """Open the create-post composer on the Group page.

        Locates and clicks the create-post button, then waits for the composer
        dialog to actually appear. Does NOT click Post.
        """
        self._log('Opening composer')

        # Selectors for the create-post button on Facebook Group page
        create_post_selectors = [
            # Vietnamese
            'div[role="button"][aria-label*="Viết bài"]',
            'div[role="button"][aria-label*="Đăng bài"]',
            'div[role="button"][aria-label*="Tạo bài"]',
            'div[role="button"][aria-label*="Bài viết"]',
            # English
            'div[role="button"][aria-label*="Write post"]',
            'div[role="button"][aria-label*="Post"]',
            'div[role="button"][aria-label*="Create post"]',
            'div[role="button"][aria-label*="Write something"]',
            # Generic data-testid
            'button[data-testid="composer_post_button"]',
            'div[data-testid="composer_post_button"]',
            # Fallback: any button-like with common create post labels
            'div[role="button"]',
        ]

        # First try specific selectors
        clicked = False
        for sel in create_post_selectors[:-1]:  # Skip the broad fallback
            els = self._page.query_selector_all(sel)
            for el in els:
                try:
                    if el.is_visible():
                        el.click()
                        self._page.wait_for_timeout(3000)
                        clicked = True
                        self._log('Create-post button clicked')
                        break
                except Exception:
                    continue
            if clicked:
                break

        if not clicked:
            # Last resort: broad search for visible role=button elements
            try:
                els = self._page.query_selector_all('div[role="button"]')
                for el in els:
                    try:
                        if not el.is_visible():
                            continue
                        label = el.get_attribute('aria-label') or ''
                        text = el.inner_text() or ''
                        combined = (label + ' ' + text).lower()
                        if any(kw in combined for kw in ['viết bài', 'write post', 'create post', 'đăng bài', 'post']):
                            el.click()
                            self._page.wait_for_timeout(3000)
                            clicked = True
                            self._log('Create-post button clicked (fallback)')
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if not clicked:
            raise AnonymousComposerError(
                'Could not find or click the create-post button on Group page.'
            )

        # Wait for composer to appear
        try:
            self._page.wait_for_selector(
                'div[role="dialog"]', timeout=15000,
            )
        except Exception:
            # Fallback: wait for composer text area
            try:
                self._page.wait_for_selector(
                    'div[role="textbox"]', timeout=15000,
                )
            except Exception:
                raise AnonymousComposerError(
                    'Composer dialog did not appear after clicking create-post.'
                ) from None

        self._log('Composer opened')
        return ComposerActionResult('open_composer', True)

    def check_anonymous_posting_available(self) -> bool:
        """Check if the anonymous posting option is available inside the composer.

        Only looks inside the open composer dialog, not the whole page.
        """
        try:
            self._log('Checking anonymous posting toggle inside composer')

            # Scope to the composer dialog if present
            composer_scope = self._page.query_selector('div[role="dialog"]')
            search_root = composer_scope if composer_scope else self._page

            selectors = [
                # Anonymous toggle switch inside composer
                'div[role="switch"][aria-label*="ẩn danh"]',
                'div[role="switch"][aria-label*="anonymous"]',
                'input[name*="anonymous"]',
                # Anonymous toggle button variants
                'button[aria-label*="ẩn danh"]',
                'button[aria-label*="anonymous"]',
                # Text-based labels
                'div[aria-label*="ẩn danh"]',
                'div[aria-label*="anonymous"]',
            ]

            for sel in selectors:
                try:
                    els = search_root.query_selector_all(sel)
                    for el in els:
                        if el.is_visible():
                            self._log(
                                'Anonymous posting toggle found inside composer'
                            )
                            return True
                except Exception:
                    continue

            self._log('No anonymous posting toggle found inside composer')
            return False
        except Exception:
            self._log('Error checking anonymous toggle inside composer')
            return False

    def is_anonymous_enabled(self) -> bool:
        """Check whether anonymous mode is currently ON in the composer.

        Inspects the toggle switch state (aria-pressed or checked attribute).
        """
        try:
            composer_scope = self._page.query_selector('div[role="dialog"]')
            search_root = composer_scope if composer_scope else self._page

            selectors = [
                'div[role="switch"][aria-label*="ẩn danh"]',
                'div[role="switch"][aria-label*="anonymous"]',
                'input[name*="anonymous"]',
            ]

            for sel in selectors:
                els = search_root.query_selector_all(sel)
                for el in els:
                    if not el.is_visible():
                        continue
                    # Check aria-pressed for switch role
                    pressed = el.get_attribute('aria-pressed')
                    if pressed == 'true':
                        return True
                    # Check checked for input
                    checked = el.get_attribute('checked')
                    if checked == 'true' or checked is True:
                        return True
                    # Check data-checked or similar
                    data_checked = el.get_attribute('data-checked')
                    if data_checked == 'true':
                        return True
            return False
        except Exception:
            self._log('Error checking anonymous mode state')
            return False

    def activate_anonymous(self) -> ComposerActionResult:
        """Activate the anonymous posting toggle in the composer.

        Checks current state first, only clicks if not already enabled.
        Verifies the state changed after clicking.
        """
        try:
            # Check if already enabled
            if self.is_anonymous_enabled():
                self._log('Anonymous mode already enabled')
                return ComposerActionResult('activate_anonymous', True, 'already_enabled')

            self._log('Activating anonymous posting toggle')

            composer_scope = self._page.query_selector('div[role="dialog"]')
            search_root = composer_scope if composer_scope else self._page

            selectors = [
                'div[role="switch"][aria-label*="ẩn danh"]',
                'div[role="switch"][aria-label*="anonymous"]',
                'input[name*="anonymous"]',
                'button[aria-label*="ẩn danh"]',
                'button[aria-label*="anonymous"]',
                'div[aria-label*="ẩn danh"]',
                'div[aria-label*="anonymous"]',
            ]

            clicked = False
            for sel in selectors:
                els = search_root.query_selector_all(sel)
                for el in els:
                    try:
                        if el.is_visible():
                            el.click()
                            self._page.wait_for_timeout(1000)
                            clicked = True
                            break
                    except Exception:
                        continue
                if clicked:
                    break

            if not clicked:
                return ComposerActionResult(
                    'activate_anonymous',
                    False,
                    'ANONYMOUS_UI_UNCONFIRMED',
                )

            # Verify the state changed
            self._page.wait_for_timeout(500)
            if self.is_anonymous_enabled():
                self._log('Anonymous toggle activated successfully')
                return ComposerActionResult('activate_anonymous', True)
            else:
                # Clicked but state didn't change
                return ComposerActionResult(
                    'activate_anonymous',
                    False,
                    'ANONYMOUS_UI_UNCONFIRMED',
                )

        except AnonymousComposerError:
            raise
        except Exception as exc:
            return ComposerActionResult(
                'activate_anonymous',
                False,
                f'ANONYMOUS_UI_UNCONFIRMED: {type(exc).__name__}',
            )

    def fill_caption(self, caption: str):
        """Fill the caption text into the composer."""
        if not caption or len(caption.strip()) < 8:
            raise AnonymousComposerError('Caption must be at least 8 characters.')
        if len(caption) > 5000:
            raise AnonymousComposerError('Caption exceeds 5000 characters.')
        self._log('Filling caption')
        try:
            # Scope to composer dialog
            composer_scope = self._page.query_selector('div[role="dialog"]')
            search_root = composer_scope if composer_scope else self._page

            textboxes = search_root.query_selector_all('div[role="textbox"]')
            if not textboxes:
                raise AnonymousComposerError('Caption textbox not found in composer.')

            # Use the first visible textbox
            textbox = None
            for tb in textboxes:
                try:
                    if tb.is_visible():
                        textbox = tb
                        break
                except Exception:
                    continue

            if textbox is None:
                raise AnonymousComposerError('Caption textbox not visible.')

            textbox.fill(caption, timeout=30000)
            self._page.wait_for_timeout(500)
            return ComposerActionResult('fill_caption', True)
        except Exception as exc:
            raise AnonymousComposerError(f'Failed to fill caption: {exc}') from exc

    def attach_image(self, image_path: str):
        """Attach a staged image file to the composer via native file input."""
        self._log('Attaching image')
        try:
            # Scope to composer dialog
            composer_scope = self._page.query_selector('div[role="dialog"]')
            search_root = composer_scope if composer_scope else self._page

            file_input = None
            selectors = [
                'input[type="file"][accept*="image"]',
                'input[type="file"].composer_image_input',
                'input[type="file"][name*="file"]',
                'input[type="file"]',
            ]
            for sel in selectors:
                try:
                    els = search_root.query_selector_all(sel)
                    for el in els:
                        if el.is_visible():
                            file_input = el
                            break
                except Exception:
                    continue
                if file_input:
                    break

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
            # Scope to composer dialog
            composer_scope = self._page.query_selector('div[role="dialog"]')
            search_root = composer_scope if composer_scope else self._page

            post_buttons = [
                'button[type="submit"][value*="Đăng"]',
                'button[type="submit"][value*="Post"]',
                'div[role="button"][aria-label*="Đăng"]',
                'div[role="button"][aria-label*="Post"]',
                'button[data-testid="composer_post_button"]',
            ]
            for sel in post_buttons:
                try:
                    els = search_root.query_selector_all(sel)
                    for btn in els:
                        if btn.is_visible():
                            btn.click()
                            self._page.wait_for_timeout(1000)
                            return ComposerActionResult('submit_post', True)
                except Exception:
                    continue
            raise AnonymousComposerError('Post button not found in composer.')
        except Exception as exc:
            raise AnonymousComposerError(f'Failed to submit post: {exc}') from exc

    def capture_composer_state(self) -> dict:
        """Capture relevant UI state for verification (no sensitive data)."""
        try:
            composer_scope = self._page.query_selector('div[role="dialog"]')
            search_root = composer_scope if composer_scope else self._page

            visible_text = ''
            try:
                visible_text = search_root.inner_text() or ''
            except Exception:
                visible_text = self._page.inner_text('body') or ''

            has_pending = 'pending' in visible_text.lower() or 'chờ duyệt' in visible_text.lower()
            has_error = 'lỗi' in visible_text.lower() or 'error' in visible_text.lower()

            return {
                'has_pending_approval': has_pending,
                'has_error': has_error,
                'page_title': self._page.title(),
                'anonymous_enabled': self.is_anonymous_enabled(),
                'composer_open': composer_scope is not None,
            }
        except Exception:
            return {
                'has_pending_approval': False,
                'has_error': False,
                'page_title': '',
                'anonymous_enabled': False,
                'composer_open': False,
            }
