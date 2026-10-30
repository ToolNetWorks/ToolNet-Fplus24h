"""Browser and session management for the Facebook Publishing Worker.

Each Account gets its own browser context with its own cookies and its pinned Proxy.
Cookies are encrypted; never write secret values to logs.
"""
import os
import time
import uuid as _uuid
from contextlib import contextmanager

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


class BrowserManagerError(Exception):
    pass


class CookieCrypto:
    """Encrypt/decrypt cookie blobs. Never expose plaintext cookies in logs."""

    def __init__(self, key=None):
        from cryptography.fernet import Fernet
        self._fernet = Fernet(key or os.environ.get(
            'FACEBOOK_COOKIE_ENCRYPTION_KEY',
            Fernet.generate_key(),
        ))

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ''
        return self._fernet.encrypt(plaintext.encode('utf-8')).decode('ascii')

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ''
        return self._fernet.decrypt(ciphertext.encode('ascii')).decode('utf-8')


class BrowserManager:
    """Manages isolated browser contexts per Account.

    Each context routes through the Account's pinned Proxy. The context
    lifetime is scoped to a single publishing attempt.
    """

    def __init__(self, settings):
        self._settings = settings
        self._playwright_ctx = None
        self._browser = None

    @property
    def _proxy_url(self):
        return getattr(self, '_current_proxy_url', None)

    def _ensure_browser(self, proxy_url):
        if sync_playwright is None:
            raise BrowserManagerError(
                'playwright is not installed. Install with: pip install playwright && playwright install chromium'
            )
        if self._playwright_ctx is None:
            self._playwright_ctx = sync_playwright().start()
        if self._browser is None:
            launch_kwargs = {'headless': self._settings.playwright_headless}
            if proxy_url:
                launch_kwargs['proxy'] = {'server': proxy_url}
            self._browser = self._playwright_ctx.chromium.launch(**launch_kwargs)
        return self._browser

    def __init_browser(self, proxy_url):
        if sync_playwright is None:
            raise BrowserManagerError(
                'playwright is not installed.'
            )
        if self._playwright_ctx is None:
            self._playwright_ctx = sync_playwright().start()
        if self._browser is None:
            launch_kwargs = {'headless': self._settings.playwright_headless}
            if proxy_url:
                launch_kwargs['proxy'] = {'server': proxy_url}
            self._browser = self._playwright_ctx.chromium.launch(**launch_kwargs)
        return self._browser

    @property
    def _proxy_url(self):
        return getattr(self, '_current_proxy_url', None)

    def __init_browser(self, proxy_url):
        return self._ensure_browser(proxy_url)

    def launch_context(self, account_id, proxy_server=None):
        """Launch a new browser context for this Account.

        The context uses the Account's pinned Proxy to preserve IP affinity.
        """
        self._current_proxy_url = proxy_server
        browser = self.__init_browser(proxy_server)
        context_options = {
            'viewport': {'width': 1280, 'height': 720},
            'user_agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        }
        return browser.new_context(**context_options)

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
