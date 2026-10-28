import json
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.test import Client

username = f"toolnet_lockout_test_{uuid4().hex}"
test_ip = "198.51.100.77"

client = Client(
    enforce_csrf_checks=True,
    HTTP_HOST="127.0.0.1",
    REMOTE_ADDR=test_ip,
)

# Rollback toàn bộ dữ liệu thử nghiệm.
with transaction.atomic():
    csrf_response = client.get(
        "/api/v1/auth/csrf/",
        secure=True,
    )

    if csrf_response.status_code != 200:
        raise RuntimeError("CSRF endpoint failed")

    token = csrf_response.json()["csrfToken"]
    statuses = []

    for attempt in range(1, 7):
        response = client.post(
            "/api/v1/auth/login/",
            data=json.dumps({
                "username": username,
                "password": "invalid_test_password",
            }),
            content_type="application/json",
            secure=True,
            HTTP_X_CSRFTOKEN=token,
            HTTP_REFERER="https://127.0.0.1/",
        )

        statuses.append(response.status_code)
        print(
            f"ATTEMPT {attempt}: "
            f"HTTP {response.status_code}"
        )

    if any(code != 401 for code in statuses[:4]):
        raise RuntimeError(
            "Invalid login response unexpected"
        )

    lockout_code = settings.AXES_HTTP_RESPONSE_CODE

    if lockout_code not in statuses[4:]:
        raise RuntimeError(
            "Lockout was not triggered"
        )

    print("LOGIN LOCKOUT: PASSED")

    # Không lưu lịch sử thử nghiệm vào Neon.
    transaction.set_rollback(True)

print("TEST DATABASE CHANGES: ROLLED BACK")
