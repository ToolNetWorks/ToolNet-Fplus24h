import json

from django.contrib.auth import get_user_model
from django.test import Client


def check(condition, message):
    if not condition:
        raise RuntimeError(f"FAILED: {message}")

    print(f"PASS: {message}")


client = Client(
    enforce_csrf_checks=True,
    HTTP_HOST="127.0.0.1",
)

# 1. CSRF Token
response = client.get(
    "/api/v1/auth/csrf/",
    secure=True,
)

check(response.status_code == 200, "CSRF endpoint")

token = response.json().get("csrfToken")
check(bool(token), "CSRF token generated")

# 2. POST thiếu CSRF phải bị chặn
response = client.post(
    "/api/v1/auth/login/",
    data=json.dumps({
        "username": "invalid_test_user",
        "password": "invalid_test_password",
    }),
    content_type="application/json",
    secure=True,
)

check(response.status_code == 403, "CSRF protection")

# 3. Sai tài khoản và mật khẩu
response = client.post(
    "/api/v1/auth/login/",
    data=json.dumps({
        "username": "invalid_test_user",
        "password": "invalid_test_password",
    }),
    content_type="application/json",
    secure=True,
    HTTP_X_CSRFTOKEN=token,
)

check(response.status_code == 401, "Invalid login rejected")

# 4. Người chưa đăng nhập
response = client.get(
    "/api/v1/auth/me/",
    secure=True,
)

check(response.status_code == 401, "Anonymous rejected")

# 5. Phiên Super Admin
User = get_user_model()

admin = User.objects.filter(
    is_superuser=True,
    is_active=True,
).first()

check(admin is not None, "Super Admin exists")

client.force_login(admin)

response = client.get(
    "/api/v1/auth/me/",
    secure=True,
)

check(response.status_code == 200, "Admin session")

data = response.json()
check(data["user"]["role"] == "admin", "Admin role")

print("AUTH SECURITY CHECK: PASSED")
