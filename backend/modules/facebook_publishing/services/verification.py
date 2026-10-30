"""Publishing verification for the Facebook Publishing Worker.

NEVER transitions to PUBLISHED based on HTTP 200 or the mere presence of a post_id.
If visibility cannot be verified through the browser UI, the result is UNCERTAIN.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    state: str
    external_post_id: Optional[str]
    detail: Optional[str]


class PublishingVerification:
    """Verify that a post was actually published by inspecting the browser UI."""

    def __init__(self, page, settings, expected_caption: Optional[str] = None):
        self._page = page
        self._settings = settings
        self._expected_caption = expected_caption

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
                self._page.wait_for_selector(
                    '[role="feed"], .groups_newsfeed, #pagelet-bluebar',
                    timeout=int(self._settings.browser_timeout_seconds) * 1000,
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
                'pending', 'chờ duyệt', 'awaiting approval',
                'đang chờ duyệt', 'chờ kiểm duyệt',
            ]
            is_pending = any(ind in text_lower for ind in pending_indicators)

            # Check for rejection indicators
            rejected_indicators = [
                'rejected', 'đã từ chối', 'bài viết bị từ chối',
                'removed by', 'xóa bởi', 'xóa tự động',
            ]
            is_rejected = any(ind in text_lower for ind in rejected_indicators)

            # Attempt to extract a post_id from the URL
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

            # Look for the specific post article in the feed
            # IMPORTANT: We must match the EXPECTED caption, not just any article
            article = None
            try:
                article = self._page.query_selector('[role="article"]')
            except Exception:
                pass

            if article is not None:
                try:
                    if article.is_visible():
                        post_text = article.inner_text() or ''

                        if self._expected_caption and post_text.strip():
                            # Verify the visible post contains the expected caption
                            # Use a substring match on a normalized fragment
                            expected_fragment = self._expected_caption.strip()[:200]
                            post_normalized = post_text.lower().replace('\n', ' ').strip()
                            if expected_fragment.lower() in post_normalized:
                                return VerificationResult(
                                    state='PUBLISHED',
                                    external_post_id=post_id,
                                    detail='Post confirmed visible in Group feed '
                                           'with matching caption content.',
                                )
                            else:
                                # A post article exists but content doesn't match
                                self._log(
                                    'Post article found but caption content does not match.'
                                )
                                return VerificationResult(
                                    state='UNCERTAIN',
                                    external_post_id=post_id,
                                    detail='Post container visible but content does not '
                                           'match expected caption.',
                                )
                        elif not self._expected_caption:
                            # Without a caption to match, we cannot be certain
                            # This branch should not be taken in production
                            return VerificationResult(
                                state='SUBMITTED_UNVERIFIED',
                                external_post_id=post_id,
                                detail='Post container found but no expected caption '
                                       'for verification.',
                            )
                except Exception:
                    pass

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
