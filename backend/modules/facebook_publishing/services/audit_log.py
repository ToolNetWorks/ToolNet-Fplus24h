"""Structured audit logging for the Facebook Publishing Worker.

Never logs cookies, tokens, or proxy credentials. All sensitive values are
scrubbed before logging.
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger('facebook_publishing.worker')

SENSITIVE_PATTERNS = [
    re.compile(r'(?i)(password|bearer|token|cookie|secret|credential)\s*[=:]\s*\S+'),
    re.compile(r'(?i)(api[_-]?key|access[_-]?key|secret[_-]?key)\s*[=:]\s*\S+'),
    re.compile(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'),
    re.compile(r'(?<=//)[^:@/]+:[^@/]+@'),
    re.compile(r'(?i)(c_user|xs|fr|sb|cookieid)\s*[=:]\s*\S+'),
    re.compile(r'(?i)(session|access_token|refresh_token|js_sdk)\s*[=:]\s*\S+'),
]

REDACTED = '[REDACTED]'


def scrub_value(value: Any) -> str:
    """Convert any value to string and scrub sensitive patterns."""
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return scrub_value(json.dumps(value))
    text = str(value)
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text[:2000]


def scrub_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively scrub sensitive keys from a dict."""
    result = {}
    sensitive_keys = {
        'password', 'token', 'cookie', 'secret', 'credential',
        'api_key', 'access_key', 'secret_key', 'proxy_password',
        'proxy_url', 'encrypted_cookies', 'claim_token',
    }
    for key, value in d.items():
        if isinstance(key, str) and key.lower() in sensitive_keys:
            result[key] = REDACTED
        elif isinstance(value, dict):
            result[key] = scrub_dict(value)
        elif isinstance(value, list):
            result[key] = [scrub_dict(item) if isinstance(item, dict) else scrub_value(item)
                           for item in value]
        else:
            result[key] = scrub_value(value)
    return result


class AuditLogger:
    """Structured audit logging with automatic sensitive-value scrubbing."""

    def __init__(self, worker_id: str, job_id: Optional[str] = None):
        self._worker_id = worker_id
        self._job_id = job_id

    def log(self, event: str, level: str = 'info', **kwargs):
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'worker_id': self._worker_id,
            'job_id': self._job_id,
            'event': event,
            'data': scrub_dict(kwargs),
        }
        line = json.dumps(entry, ensure_ascii=False)
        log_fn = {
            'info': logger.info,
            'warning': logger.warning,
            'error': logger.error,
            'debug': logger.debug,
        }.get(level, logger.info)
        log_fn(line)
        return entry

    def log_transition(self, from_state: str, to_state: str, **kwargs):
        return self.log(
            'state_transition',
            from_state=from_state,
            to_state=to_state,
            **kwargs,
        )

    def log_error(self, error_code: str, message: str, **kwargs):
        return self.log(
            'worker_error',
            level='error',
            error_code=error_code,
            message=message,
            **kwargs,
        )

    def log_event(self, event: str, **kwargs):
        return self.log(event, **kwargs)
