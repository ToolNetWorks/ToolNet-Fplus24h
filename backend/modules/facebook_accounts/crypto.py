import json
import os
from functools import lru_cache
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import dotenv_values
ENV_PATH = (
    Path(__file__).resolve().parents[3] / ".env"
)
@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    key = (
        os.environ.get("FACEBOOK_COOKIE_FERNET_KEY")
        or dotenv_values(ENV_PATH).get(
            "FACEBOOK_COOKIE_FERNET_KEY"
        )
    )
    if not key:
        raise RuntimeError(
            "FACEBOOK_COOKIE_FERNET_KEY is missing."
        )
    return Fernet(key.encode())
def encrypt_cookies(cookies: list[dict]) -> str:
    plaintext = json.dumps(
        cookies,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return get_fernet().encrypt(
        plaintext
    ).decode("ascii")
def decrypt_cookies(ciphertext: str) -> list[dict]:
    plaintext = get_fernet().decrypt(
        ciphertext.encode("ascii")
    )
    result = json.loads(
        plaintext.decode("utf-8")
    )
    if not isinstance(result, list):
        raise ValueError("Invalid encrypted payload.")
    return result
