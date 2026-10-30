"""Configuration access for the Facebook Publishing Worker.

Reads environment variables with safe defaults:
  FACEBOOK_PUBLISHING_ENABLED (default: false)
  FACEBOOK_PUBLISHING_DRY_RUN (default: true)
"""
import os
from dataclasses import dataclass
from modules.facebook_publishing.models import WorkerConfig, WorkerResultState


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


@dataclass(frozen=True)
class WorkerSettings:
    enabled: bool
    dry_run: bool
    browser_timeout_seconds: int
    max_retry_attempts: int
    playwright_headless: bool
    facebook_base_url: str

    @property
    def can_publish(self) -> bool:
        """Publishing to Facebook is only allowed when enabled AND dry_run is off."""
        return self.enabled and not self.dry_run


def load_settings(pipeline_id=None):
    """Load Worker settings from environment, optionally merged with DB config."""
    env = os.environ
    enabled = _parse_bool(env.get('FACEBOOK_PUBLISHING_ENABLED'), False)
    dry_run = _parse_bool(env.get('FACEBOOK_PUBLISHING_DRY_RUN'), True)
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
            from modules.publishing.models import PublishingJob
            config = WorkerConfig.objects.filter(pipeline_id=pipeline_id).first()
            if config is not None:
                return WorkerSettings(
                    enabled=config.enabled,
                    dry_run=config.dry_run,
                    browser_timeout_seconds=config.browser_timeout_seconds,
                    max_retry_attempts=config.max_retry_attempts,
                    playwright_headless=headless,
                    facebook_base_url=base_url,
                )
        except Exception:
            pass

    return WorkerSettings(
        enabled=enabled,
        dry_run=dry_run,
        browser_timeout_seconds=timeout_seconds,
        max_retry_attempts=max_retry_attempts,
        playwright_headless=headless,
        facebook_base_url=base_url,
    )
