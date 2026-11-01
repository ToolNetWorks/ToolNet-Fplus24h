"""Publishing verification for the Facebook Publishing Worker.

NEVER transitions to PUBLISHED based on HTTP 200 or the mere presence of a post_id.
If visibility cannot be verified through the browser UI, the result is UNCERTAIN.
"""
import logging
import re
import time
from urllib.parse import urljoin, urlsplit
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    state: str
    external_post_id: Optional[str]
    detail: Optional[str]
    rules_prompt: Optional[object] = None


class PublishingVerification:
    """Verify that a post was actually published by inspecting the browser UI."""

    def __init__(self, page, settings, expected_caption: Optional[str] = None,
                 monitor_rules: bool = False):
        self._page = page
        self._settings = settings
        self._expected_caption = expected_caption
        self._monitor_rules = monitor_rules

    def _log(self, message):
        logger.info('Verification: %s', message)

    def verify_post_visibility(self) -> VerificationResult:
        """Inspect the browser to confirm the post is actually visible.

        Returns:
            state = 'PUBLISHED' only if a post is found in the Group feed
                    that contains the expected caption text (not just any article).
            state = 'PENDING_APPROVAL' if the post appears but is held
                    for admin approval.
            state = 'REJECTED' if the post was rejected.
            state = 'SUBMITTED_UNVERIFIED' if a post ID is found but content
                    cannot be confirmed.
            state = 'UNCERTAIN' if visibility cannot be confirmed.
        """
        try:
            self._log('Checking Group feed for published post')

            content_loaded = False
            try:
                selector = '[role="feed"], .groups_newsfeed, #pagelet-bluebar'
                if self._monitor_rules:
                    from .rules_confirmation import inspect_rules_prompt
                    deadline = time.monotonic() + int(self._settings.browser_timeout_seconds)
                    while time.monotonic() < deadline:
                        prompt = inspect_rules_prompt(self._page)
                        if prompt:
                            return VerificationResult('RULES_CONFIRMATION_REQUIRED', None,
                                                      'Participation prompt requires review.', prompt)
                        try:
                            self._page.wait_for_selector(selector, timeout=1000)
                            content_loaded = True
                            break
                        except Exception:
                            continue
                else:
                    self._page.wait_for_selector(
                        selector, timeout=int(self._settings.browser_timeout_seconds) * 1000,
                    )
                    content_loaded = True
            except Exception:
                self._page.wait_for_timeout(3000)

            if not content_loaded:
                return VerificationResult(
                    state='UNCERTAIN',
                    external_post_id=None,
                    detail='Could not load Group feed content.',
                )

            visible_text = self._page.inner_text('body') or ''
            text_lower = visible_text.lower()

            # Check for pending approval indicators
            pending_indicators = [
                'your post is pending admin approval',
                'your post is pending approval',
                'your post is awaiting approval',
                'bài viết của bạn đang chờ duyệt',
                'bài viết của bạn đang chờ phê duyệt',
                'bài viết của bạn đang chờ kiểm duyệt',
            ]
            is_pending = any(ind in text_lower for ind in pending_indicators)

            # Check for rejection indicators
            rejected_indicators = [
                'your post was rejected', 'your post has been rejected',
                'bài viết của bạn đã bị từ chối',
            ]
            is_rejected = any(ind in text_lower for ind in rejected_indicators)

            # Attempt to extract a post_id from the URL
            current_url = self._page.url or ''
            current_group = re.search(r'/groups/([^/]+)', urlsplit(current_url).path)
            post_id = None
            id_match = re.search(r'/posts/(\d+(?:_\d+)?)', current_url)
            if id_match:
                post_id = id_match.group(1)

            if is_rejected:
                return VerificationResult(
                    state='REJECTED',
                    external_post_id=post_id,
                    detail='Post appears to have been rejected by Group admin.',
                )

            if is_pending:
                return VerificationResult(
                    state='PENDING_APPROVAL',
                    external_post_id=post_id,
                    detail='Post appears to require admin approval.',
                )

            # Match the complete approved caption and a visible media preview in
            # the same article. A URL or a different feed item is not evidence.
            expected = re.sub(r'\s+', ' ', self._expected_caption or '').strip().lower()
            if expected:
                for article in self._page.query_selector_all('[role="article"]'):
                    try:
                        if not article.is_visible():
                            continue
                        actual = re.sub(r'\s+', ' ', article.inner_text() or '').strip().lower()
                        if expected not in actual:
                            continue
                        media = article.query_selector_all('img')
                        has_media = any(img.is_visible() and img.evaluate(
                            'e => { const r=e.getBoundingClientRect(); return e.complete && e.naturalWidth>0 && r.width>=100 && r.height>=100; }'
                        ) for img in media)
                        if not has_media:
                            return VerificationResult('SUBMITTED_UNVERIFIED', post_id,
                                'Matching caption found, but attached media was not verified.')
                        for link in article.query_selector_all('a[href]'):
                            href = link.get_attribute('href') or ''
                            candidate = urlsplit(urljoin(current_url, href))
                            match = re.search(r'/groups/([^/]+)/posts/(\d+(?:_\d+)?)', candidate.path)
                            if (match and current_group and match.group(1) == current_group.group(1)
                                    and candidate.hostname in ('facebook.com', 'www.facebook.com', 'm.facebook.com')):
                                post_id = match.group(2)
                                break
                        if not post_id:
                            return VerificationResult('SUBMITTED_UNVERIFIED', None,
                                'Matching caption and image visible, but post identity is unavailable.')
                        return VerificationResult('PUBLISHED', post_id,
                            'Matching caption and image are visible in the Group feed.')
                    except Exception:
                        continue

            # No matching post found — even if an article exists
            if post_id:
                return VerificationResult(
                    state='SUBMITTED_UNVERIFIED',
                    external_post_id=post_id,
                    detail='Post ID found but visibility/content not confirmed in feed.',
                )

            return VerificationResult(
                state='UNCERTAIN',
                external_post_id=None,
                detail='No post ID or visible post content found on page.',
            )

        except Exception as exc:
            self._log(f'Exception during verification: {type(exc).__name__}')
            return VerificationResult(
                state='UNCERTAIN',
                external_post_id=None,
                detail=f'Verification failed with exception: {type(exc).__name__}',
            )

    def check_captcha_or_checkpoint(self) -> Optional[str]:
        """Check if Facebook is showing a CAPTCHA or checkpoint challenge.

        Returns the checkpoint type string if detected, None otherwise.
        Never bypasses these challenges.
        """
        try:
            body_text = (self._page.inner_text('body') or '').lower()
            if 'captcha' in body_text or 'xác minh' in body_text:
                return 'CAPTCHA'
            if 'security check' in body_text or 'kiểm tra bảo mật' in body_text:
                return 'SECURITY_CHECKPOINT'
            if 'confirm your identity' in body_text or 'xác nhận danh tính' in body_text:
                return 'IDENTITY_CHECKPOINT'
            return None
        except Exception:
            return None
