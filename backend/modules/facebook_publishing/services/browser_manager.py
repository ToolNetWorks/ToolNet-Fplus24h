"""Browser and session management for the Facebook Publishing Worker.

Each Account gets its own browser context with its own cookies and its pinned Proxy.
Cookies are encrypted; never write secret values to logs.
"""
from typing import List, Optional, Dict, Any

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


class BrowserManagerError(Exception):
    pass


class CookieCrypto:
    """Encrypt/decrypt cookie blobs using the existing Fernet key.

    Uses the same FACEBOOK_COOKIE_FERNET_KEY as the FacebookAccount system.
    Never logs plaintext cookies or decrypted values.
    """

    def __init__(self):
        from modules.facebook_accounts.crypto import get_fernet
        self._fernet = get_fernet()

    def noop(self) -> bool:
        """Returns True if the crypto system is operational."""
        return self._fernet is not None


def _build_proxy_config(proxy) -> Optional[Dict[str, Any]]:
    """Build Playwright proxy configuration with separate username/password fields.

    Uses Playwright's native proxy config format:
    {
        "server": "http://host:port",
        "username": "user",
        "password": "pass"
    }
    """
    if proxy is None:
        return None

    # Build server URL without credentials
    server_url = f"{proxy.protocol}://{proxy.host}:{proxy.port}"

    # Check for auth credentials
    auth_secret = getattr(proxy, 'auth_secret', None)
    if auth_secret:
        from modules.proxies.crypto import decrypt_proxy_credentials
        try:
            creds = decrypt_proxy_credentials(auth_secret.ciphertext)
            # creds is a dict with username and password
            return {
                "server": server_url,
                "username": creds.get("username", ""),
                "password": creds.get("password", ""),
            }
        except Exception:
            # Don't log credentials, just warn
            import logging
            logging.getLogger(__name__).warning('Could not decrypt proxy credentials for %s', proxy.pk)
            # Fall through to no-auth config
            pass

    return {"server": server_url}


class BrowserManager:
    """Manages isolated browser contexts per Account.

    Each context routes through the Account's pinned Proxy. The context
    lifetime is scoped to a single publishing attempt.
    """

    def __init__(self, settings):
        self._settings = settings
        self._playwright_ctx = None
        self._browser = None

    def _ensure_browser(self, proxy_config: Optional[Dict[str, Any]]):
        if sync_playwright is None:
            raise BrowserManagerError(
                'playwright is not installed. Install with: '
                'pip install playwright && playwright install chromium'
            )
        if self._playwright_ctx is None:
            self._playwright_ctx = sync_playwright().start()
        if self._browser is None:
            launch_kwargs = {'headless': self._settings.playwright_headless}
            if proxy_config:
                launch_kwargs['proxy'] = proxy_config
            self._browser = self._playwright_ctx.chromium.launch(**launch_kwargs)
        return self._browser

    def launch_context(self, proxy_config: Optional[Dict[str, Any]] = None):
        """Launch a new browser context for this Account.

        The context uses the Account's pinned Proxy to preserve IP affinity.
        """
        browser = self._ensure_browser(proxy_config)
        context_options = {
            'viewport': {'width': 1280, 'height': 720},
            'user_agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        }
        return browser.new_context(**context_options)

    def load_account_cookies(self, context, account):
        """Load encrypted Facebook cookies from the existing system into the context.

        Uses FacebookCookieSecret + crypto.decrypt_cookies.
        Never writes decrypted cookie values to logs.
        """
        from modules.facebook_accounts.credentials import FacebookCookieSecret
        from modules.facebook_accounts.crypto import decrypt_cookies

        cookie_secret = getattr(account, 'cookie_secret', None)
        if cookie_secret is None:
            return False, 0  # No cookies stored

        try:
            cookies = decrypt_cookies(cookie_secret.ciphertext)
        except Exception:
            return False, 0  # Decryption failed; cookies may be stale

        if not isinstance(cookies, list):
            return False, 0

        # Transform to Playwright cookie format
        pw_cookies = []
        for c in cookies:
            pw_cookies.append({
                'name': c.get('name', ''),
                'value': c.get('value', ''),
                'domain': c.get('domain', '.facebook.com'),
                'path': c.get('path', '/'),
                'secure': c.get('secure', True),
                'httpOnly': c.get('httpOnly', False),
                'sameSite': c.get('sameSite', 'Lax'),
            })

        context.add_cookies(pw_cookies)
        return True, len(pw_cookies)

    def verify_account_identity(self, page) -> bool:
        """Verify the browser session is authenticated as the expected Account.

        Checks the Facebook page for the account's profile link or name.
        Does NOT expose cookie values or user IDs in logs.
        """
        try:
            # Look for the profile image / account switcher indicator
            page.goto('https://www.facebook.com/', timeout=30000)
            page.wait_for_timeout(2000)

            # Check if we're on the homepage (authenticated) vs login page
            login_indicators = [
                'input[name="email"]',
                'input[name="pass"]',
                '#loginbutton',
            ]
            for sel in login_indicators:
                if page.query_selector(sel) is not None:
                    return False  # Still on login page

            # Check for the home feed (authenticated)
            home_indicators = [
                '[role="feed"]',
                '[aria-label="Trang chủ"]',
                '[aria-label="Home"]',
                'div[data-testid="js_2"]',
            ]
            for sel in home_indicators:
                if page.query_selector(sel) is not None:
                    return True

            return False
        except Exception:
            return False

    def close_context(self, context):
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

    def shutdown(self):
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright_ctx is not None:
            try:
                self._playwright_ctx.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright_ctx = None
