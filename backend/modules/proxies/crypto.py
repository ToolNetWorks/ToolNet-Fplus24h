import json
import os
from functools import lru_cache
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import dotenv_values

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


@lru_cache(maxsize=1)
def get_proxy_fernet():
    key = (
        os.environ.get("PROXY_FERNET_KEY")
        or dotenv_values(ENV_PATH).get("PROXY_FERNET_KEY")
    )
    if not key:
        raise RuntimeError("PROXY_FERNET_KEY is missing")
    return Fernet(key.encode("ascii"))


def encrypt_proxy_credentials(username, password):
    payload = json.dumps(
        {
            "username": username,
            "password": password,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return get_proxy_fernet().encrypt(payload).decode("ascii")


def decrypt_proxy_credentials(ciphertext):
    plaintext = get_proxy_fernet().decrypt(
        ciphertext.encode("ascii")
    )
    payload = json.loads(plaintext.decode("utf-8"))
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("username"), str)
        or not isinstance(payload.get("password"), str)
    ):
        raise ValueError("Invalid proxy credentials")
    return payload
