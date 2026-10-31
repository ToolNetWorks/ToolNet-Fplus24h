"""Configuration access for the Facebook Publishing Worker.

Reads environment variables with safe defaults:
  FACEBOOK_PUBLISHING_ENABLED (default: false)
  FACEBOOK_PUBLISHING_DRY_RUN (default: true)
  FACEBOOK_PUBLISHING_CONNECTION_MODE (default: proxy)
"""
import os
from dataclasses import dataclass
from modules.facebook_publishing.models import WorkerConfig, WorkerResultState, ConnectionMode


def _parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ('1', 'true', 'yes', 'on'):
        return True
    if s in ('0', 'false', 'no', 'off'):
        return False
    return default


def _parse_connection_mode(value, default=ConnectionMode.PROXY):
    if value is None:
        return default
    if isinstance(value, ConnectionMode):
        return value
    s = str(value).strip().lower()
    if s in ('direct', 'proxy'):
        return ConnectionMode(s)
    return default


@dataclass(frozen=True)
class WorkerSettings:
    enabled: bool
    dry_run: bool
    connection_mode: ConnectionMode = ConnectionMode.PROXY
    browser_timeout_seconds: int = 120
    max_retry_attempts: int = 3
    playwright_headless: bool = True
    facebook_base_url: str = 'https://www.facebook.com'

    @property
    def can_publish(self) -> bool:
        """Publishing to Facebook is only allowed when enabled AND dry_run is off."""
        return self.enabled and not self.dry_run

    @property
    def use_proxy(self) -> bool:
        """Whether to use the pinned proxy for this pipeline."""
        return self.connection_mode == ConnectionMode.PROXY


def load_settings(pipeline_id=None):
    """Load Worker settings from environment, optionally merged with DB config."""
    env = os.environ
    enabled = _parse_bool(env.get('FACEBOOK_PUBLISHING_ENABLED'), False)
    dry_run = _parse_bool(env.get('FACEBOOK_PUBLISHING_DRY_RUN'), True)
    connection_mode = _parse_connection_mode(env.get('FACEBOOK_PUBLISHING_CONNECTION_MODE'))
    timeout = env.get('FACEBOOK_PUBLISHING_BROWSER_TIMEOUT')
    try:
        timeout_seconds = int(timeout) if timeout else 120
    except (TypeError, ValueError):
        timeout_seconds = 120
    timeout_seconds = max(10, min(600, timeout_seconds))
    max_retry = env.get('FACEBOOK_PUBLISHING_MAX_RETRY')
    try:
        max_retry_attempts = int(max_retry) if max_retry else 3
    except (TypeError, ValueError):
        max_retry_attempts = 3
    headless = _parse_bool(env.get('FACEBOOK_PUBLISHING_HEADLESS'), True)
    base_url = env.get(
        'FACEBOOK_PUBLISHING_BASE_URL', 'https://www.facebook.com',
    ).rstrip('/')

    if pipeline_id is not None:
        try:
            config = WorkerConfig.objects.filter(pipeline_id=pipeline_id).first()
            if config is not None:
                return WorkerSettings(
                    enabled=config.enabled,
                    dry_run=config.dry_run,
                    connection_mode=config.connection_mode,
                    browser_timeout_seconds=config.browser_timeout_seconds,
                    max_retry_attempts=config.max_retry_attempts,
                    playwright_headless=True,
                    facebook_base_url='https://www.facebook.com',
                )
        except Exception:
            pass

    return WorkerSettings(
        enabled=enabled,
        dry_run=dry_run,
        connection_mode=connection_mode,
        browser_timeout_seconds=timeout_seconds,
        max_retry_attempts=max_retry_attempts,
        playwright_headless=True,
        facebook_base_url='https://www.facebook.com',
    )
