"""Publishing verification for the Facebook Publishing Worker.

NEVER transitions to PUBLISHED based on HTTP 200 or the mere presence of a post_id.
If visibility cannot be verified through the browser UI, the result is UNCERTAIN.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

POST_ID_RE = re.compile(r'\b\d+_\d+\b')


@dataclass
class VerificationResult:
    state: str
    external_post_id: Optional[str]
    detail: Optional[str]


class PublishingVerification:
    """Verify that a post was actually published by inspecting the browser UI."""

    def __init__(self, page, settings):
        self._page = page
        self._settings = settings

    def _log(self, message):
        logger.info('Verification: %s', message)

    def verify_post_visibility(self) -> VerificationResult:
        """Inspect the browser to confirm the post is actually visible.

        Returns:
            state = 'PUBLISHED' only if the post appears in the Group feed
                    with visible content (not just a post_id acknowledgment).
            state = 'PENDING_APPROVAL' if the post appears but is held
                    for admin approval.
            state = 'UNCERTAIN' if visibility cannot be confirmed.
        """
        try:
            self._log('Checking Group feed for published post')

            content_loaded = False
            try:
                self._page.wait_for_selector(
                    '[role="feed"], .groups_newsfeed, #pagelet-bluebar',
                    timeout=self._settings.browser_timeout_seconds * 1000,
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

            # Check for pending approval indicators
            pending_indicators = [
                'pending', 'chờ duyệt', 'awaiting approval',
                'đang chờ duyệt', 'chờ kiểm duyệt',
            ]
            text_lower = visible_text.lower()
            is_pending = any(ind in text_lower for ind in pending_indicators)

            # Check for rejection indicators
            rejected_indicators = [
                'rejected', 'đã từ chối', 'bài viết bị từ chối',
                'removed by', 'xóa bởi', 'xóa tự động',
            ]
            is_rejected = any(ind in text_lower for ind in rejected_indicators)

            # Check for visible post content — look for the post body in the feed
            post_body_selectors = [
                '[role="article"]',
                '[data-testid="post_container"]',
                '.userContent', 'div[role="article"]',
            ]
            has_visible_post = False
            for sel in post_body_selectors:
                try:
                    el = self._page.query_selector(sel)
                    if el is not None and el.is_visible():
                        has_visible_post = True
                        break
                except Exception:
                    continue

            # Attempt to extract a post_id from the URL or page content
            current_url = self._page.url or ''
            post_id = None
            id_match = re.search(r'/posts/(\d+_\d+)', current_url)
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

            if has_visible_post:
                # Confirm the post actually has visible content, not just a container
                post_text = ''
                try:
                    article = self._page.query_selector('[role="article"]')
                    if article:
                        post_text = article.inner_text() or ''
                except Exception:
                    pass

                if post_text.strip():
                    return VerificationResult(
                        state='PUBLISHED',
                        external_post_id=post_id,
                        detail='Post confirmed visible in Group feed.',
                    )
                else:
                    return VerificationResult(
                        state='UNCERTAIN',
                        external_post_id=post_id,
                        detail='Post container found but content not verifiable.',
                    )

            if post_id:
                return VerificationResult(
                    state='SUBMITTED_UNVERIFIED',
                    external_post_id=post_id,
                    detail='Post ID found but visibility not confirmed in feed.',
                )

            return VerificationResult(
                state='SUBMITTED_UNVERIFIED',
                external_post_id=None,
                detail='Post submitted but no post ID or content found in page.',
            )

        except Exception as exc:
            self._log(f'Exception during verification: {exc}')
            return VerificationResult(
                state='UNCERTAIN',
                external_post_id=None,
                detail=f'Verification failed with exception: {type(exc).__name__}',
            )

    def check_captcha_or_checkpoint(self) -> Optional[str]:
        """Check if Facebook is showing a CAPTCHA or checkpoint challenge.

        Returns the checkpoint type string if detected, None otherwise.
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
