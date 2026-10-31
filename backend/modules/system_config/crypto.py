import base64
import hashlib
import os
import re
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet
from django.conf import settings

# Salt for PBKDF2 key derivation from settings.SECRET_KEY
KDF_SALT = b"toolnet_fplus24h_system_config_salt_v1"


@lru_cache(maxsize=1)
def get_system_fernet() -> Fernet:
    """Return a Fernet cipher instance using a persistent, deterministic key.

    Priority:
    1. SYSTEM_CONFIG_FERNET_KEY environment variable if defined.
    2. Derived 32-byte key from Django's settings.SECRET_KEY via PBKDF2 HMAC-SHA256.
       Since SECRET_KEY is long and stable in production, this provides safe,
       durable encryption without requiring manual key management.
    """
    custom_key = os.environ.get("SYSTEM_CONFIG_FERNET_KEY")
    if custom_key:
        return Fernet(custom_key.encode("ascii"))

    secret_key = getattr(settings, "SECRET_KEY", "")
    if not secret_key:
        raise RuntimeError("Django SECRET_KEY must be set to derive system config cipher.")

    key_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        secret_key.encode("utf-8"),
        KDF_SALT,
        iterations=100_000,
    )
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext secret (API Key, Secret Access Key, etc.) into Fernet token."""
    if not plaintext:
        return ""
    token_bytes = get_system_fernet().encrypt(plaintext.encode("utf-8"))
    return token_bytes.decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a Fernet token back into plaintext. Returns empty string on failure or empty input."""
    if not ciphertext:
        return ""
    try:
        decrypted = get_system_fernet().decrypt(ciphertext.encode("ascii"))
        return decrypted.decode("utf-8")
    except Exception:
        return ""


def mask_secret(secret: Optional[str], visible_chars: int = 4) -> str:
    """Return a masked representation of a secret string for safe display."""
    if not secret:
        return ""
    if len(secret) <= visible_chars * 2:
        return "••••••••"
    return f"{secret[:visible_chars]}••••••••{secret[-visible_chars:]}"


# Patterns for credentials scrubbing in error messages and logs
_SENSITIVE_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-_\.=]+", re.IGNORECASE),
    re.compile(r"x-api-key:\s*[^\s,]+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9\-_]{10,}", re.IGNORECASE),
    re.compile(r"gsk_[A-Za-z0-9\-_]{10,}", re.IGNORECASE),
    re.compile(r"key=[A-Za-z0-9\-_\.]{15,}", re.IGNORECASE),
    re.compile(r"://([^:@]+):([^@]+)@", re.IGNORECASE),  # URL user:password@
]


def sanitize_text(text: str) -> str:
    """Clean sensitive information (passwords, tokens, keys) from error messages and logs."""
    if not text:
        return ""
    cleaned = str(text)
    # Mask URL passwords
    cleaned = re.sub(r"://([^:@\s]+):([^@\s]+)@", r"://\1:••••••••@", cleaned)
    # Mask Bearer tokens
    cleaned = re.sub(r"(Bearer\s+)[A-Za-z0-9\-_\.=]+", r"\1••••••••", cleaned, flags=re.IGNORECASE)
    # Mask API keys
    cleaned = re.sub(r"(sk-[A-Za-z0-9\-_]{4})[A-Za-z0-9\-_]+", r"\1••••••••", cleaned)
    cleaned = re.sub(r"(gsk_[A-Za-z0-9\-_]{4})[A-Za-z0-9\-_]+", r"\1••••••••", cleaned)
    cleaned = re.sub(r"([?&]key=)[^&\s]+", r"\1••••••••", cleaned)
    cleaned = re.sub(r"(?i)((?:x-api-key|api[_-]?key|token|cookie|set-cookie|password|secret[_-]?(?:access[_-]?)?key)\s*[:=]\s*)[^\r\n,;]+", r"\1[REDACTED]", cleaned)
    return cleaned
