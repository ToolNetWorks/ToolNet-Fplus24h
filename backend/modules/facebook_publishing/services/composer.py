"""Anonymous composer adapter for the Facebook Publishing Worker.

Interacts with the Facebook Groups composer through the browser UI:
- Navigate to the group
- Open the composer (create-post button)
- Activate the anonymous posting toggle inside the composer
- Fill the caption text
- Attach the staged image
- Submit the post

Never replays private GraphQL requests from the HAR.
"""
import logging
import json
import os
import re
import tempfile
import time
from pathlib import Path
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

    def __init__(self, page, settings, account_label=None):
        self._page = page
        self._settings = settings
        self._account_label = account_label

    def _log(self, message):
        """Log without exposing any sensitive values."""
        logger.info('Composer: %s', message)

    def _save_safe_diagnostics(self, reason):
        """Save structural counts only and mask all page content in screenshots."""
        try:
            directory = Path(tempfile.mkdtemp(prefix='fb-composer-diagnostic-'))
            counts = {'reason': reason}
            for role in ('dialog', 'switch', 'textbox'):
                counts[f'{role}_count'] = self._page.get_by_role(role).count()
            (directory / 'dom-summary.json').write_text(json.dumps(counts), encoding='utf-8')
            self._page.screenshot(path=str(directory / 'masked.png'),
                                  mask=[self._page.locator('body')])
            self._log(f'Safe diagnostics saved to {directory}')
        except Exception:
            self._log('Safe diagnostics unavailable')

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

        # Match the Group's visible prompt before considering older selectors.
        prompt = self._page.get_by_text(re.compile(r'Bạn viết gì đi|Write something', re.I)).first
        if prompt.count() and prompt.is_visible():
            prompt.click(timeout=10000)
            self._page.get_by_role('dialog').filter(
                has=self._page.get_by_role('textbox')
            ).first.wait_for(state='visible', timeout=15000)
            return ComposerActionResult('open_composer', True)

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

    _ANONYMOUS_ROW = re.compile(
        r"đăng dưới vai trò thành viên ẩn danh|post as an anonymous member", re.I,
    )
    _ANONYMOUS_IDENTITY = re.compile(
        r"thành viên ẩn danh|anonymous member|anonymous participant", re.I,
    )

    def _composer_dialog(self):
        return self._page.get_by_role('dialog').filter(
            has=self._page.get_by_role('textbox')
        ).first

    def open_author_menu(self):
        """Open the author identity chooser inside the actual composer."""
        if not self._account_label:
            raise AnonymousComposerError('Expected account label is required.')
        # Wait until the composer transition has settled before opening a popover.
        self._page.wait_for_timeout(2000)
        author = self._page.get_by_role('button', name=self._account_label, exact=True)
        if author.count() != 1 or not author.is_visible():
            self._save_safe_diagnostics('author_identity_unavailable')
            raise AnonymousComposerError('Author identity menu not found.')
        author.click(timeout=10000)
        try:
            self._page.get_by_role('switch').first.wait_for(state='visible', timeout=10000)
            if self._anonymous_switch() is None:
                raise AnonymousComposerError('Anonymous identity switch not found.')
        except Exception:
            self._save_safe_diagnostics('anonymous_switch_unavailable')
            raise
        return ComposerActionResult('open_author_menu', True)

    def _anonymous_switch(self):
        switch = self._page.get_by_role('switch')
        if switch.count() != 1 or not switch.first.is_visible():
            return None
        # Facebook splits the row label into nested spans; accessible name may
        # be empty, so inspect the rendered text of the switch's containing row.
        row_text = switch.first.evaluate(
            "e => { let p=e; for(let i=0;i<3 && p;i++) p=p.parentElement; return p?.innerText || ''; }"
        )
        if not self._ANONYMOUS_ROW.search(row_text):
            return None
        return switch.first

    def check_anonymous_posting_available(self) -> bool:
        try:
            return self._anonymous_switch() is not None
        except Exception:
            return False

    def is_anonymous_enabled(self) -> bool:
        """Require the composer's author to identify as anonymous."""
        try:
            dialog = self._composer_dialog()
            author = dialog.get_by_role('button', name=self._ANONYMOUS_IDENTITY)
            return author.count() == 1 and author.first.is_visible()
        except Exception:
            return False

    def activate_anonymous(self) -> ComposerActionResult:
        """Turn on the identified switch and verify the composer author."""
        try:
            switch = self._anonymous_switch()
            if switch is None:
                return ComposerActionResult('activate_anonymous', False, 'ANONYMOUS_TOGGLE_NOT_FOUND')
            state = switch.get_attribute('aria-checked')
            if state not in ('true', 'false'):
                return ComposerActionResult('activate_anonymous', False, 'ANONYMOUS_STATE_UNKNOWN')
            if state == 'false':
                switch.click(timeout=10000)
            # Facebook may close the menu immediately when the switch changes.
            # A switch that remains visible must explicitly report checked.
            self._page.wait_for_timeout(1000)
            remaining = self._anonymous_switch()
            if remaining is not None:
                if remaining.get_attribute('aria-checked') != 'true':
                    return ComposerActionResult('activate_anonymous', False, 'ANONYMOUS_STATE_UNCONFIRMED')
                self._page.keyboard.press('Escape')
            # Handle Facebook's explicit anonymous-post confirmation, if shown.
            confirmation = self._page.get_by_role('dialog').filter(
                has_text=re.compile(r'đăng bài ẩn danh|post anonymously', re.I)
            )
            if confirmation.count() == 1 and confirmation.first.is_visible():
                confirm = confirmation.first.get_by_role(
                    'button', name=re.compile(r'^(tiếp tục|xong|continue|done)$', re.I)
                )
                if confirm.count() == 1:
                    confirm.first.click(timeout=10000)
            self._page.wait_for_timeout(500)
            if not self.is_anonymous_enabled():
                return ComposerActionResult('activate_anonymous', False, 'ANONYMOUS_AUTHOR_UNCONFIRMED')
            return ComposerActionResult('activate_anonymous', True)
        except Exception as exc:
            self._save_safe_diagnostics('anonymous_activation_failed')
            return ComposerActionResult('activate_anonymous', False, type(exc).__name__)

    def fill_caption(self, caption: str):
        """Fill the caption text into the composer."""
        if not caption or len(caption.strip()) < 8:
            raise AnonymousComposerError('Caption must be at least 8 characters.')
        if len(caption) > 5000:
            raise AnonymousComposerError('Caption exceeds 5000 characters.')
        self._log('Filling caption')
        try:
            # Scope to composer dialog
            textbox = self._composer_dialog().get_by_role('textbox').first
            textbox.fill(caption, timeout=30000)
            self._page.wait_for_timeout(500)
            if not self.verify_caption(caption):
                raise AnonymousComposerError('Caption could not be verified in composer.')
            return ComposerActionResult('fill_caption', True)
        except Exception as exc:
            raise AnonymousComposerError(f'Failed to fill caption: {exc}') from exc

    def verify_caption(self, caption: str) -> bool:
        try:
            return self._composer_dialog().get_by_role('textbox').first.inner_text().strip() == caption.strip()
        except Exception:
            return False

    def attach_image(self, image_path: str):
        """Attach a staged image file to the composer via native file input."""
        self._log('Attaching image')
        try:
            dialog = self._composer_dialog()
            file_input = dialog.locator('input[type="file"]').first
            file_input.set_input_files(image_path, timeout=30000)
            preview = dialog.get_by_role('img', name=os.path.basename(image_path), exact=True)
            preview.first.wait_for(state='visible', timeout=30000)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if preview.first.evaluate('e => e.complete && e.naturalWidth > 0'):
                    break
                self._page.wait_for_timeout(250)
            else:
                raise AnonymousComposerError('Image preview did not load.')
            return ComposerActionResult('attach_image', True)
        except Exception as exc:
            raise AnonymousComposerError(f'Failed to attach image: {exc}') from exc

    def submit_post(self) -> ComposerActionResult:
        """Submit the post by clicking the Post button once."""
        self._log('Submitting post')
        try:
            button = self._composer_dialog().get_by_role(
                'button', name=re.compile(r'^(đăng|post)$', re.I)
            )
            if button.count() != 1 or not button.first.is_visible() or not button.first.is_enabled():
                raise AnonymousComposerError('An enabled Post button was not found in composer.')
            # A click can reach Facebook even if Playwright reports a timeout.
            # Never try another selector after attempting the click.
            button.first.click(timeout=10000)
            self._page.wait_for_timeout(1000)
            return ComposerActionResult('submit_post', True)
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
