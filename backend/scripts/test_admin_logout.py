from django.contrib.auth import get_user_model
from django.test import Client


def check(condition, message):
    if not condition:
        raise RuntimeError(f"FAILED: {message}")
    print(f"PASS: {message}")


User = get_user_model()

admin = User.objects.filter(
    is_superuser=True,
    is_active=True,
).first()

check(admin is not None, "Admin exists")

client = Client(
    enforce_csrf_checks=True,
    HTTP_HOST="127.0.0.1",
)

# Tạo session kiểm thử, không cần mật khẩu.
client.force_login(admin)
old_session = client.cookies["sessionid"].value

# Kiểm tra session trước Logout.
response = client.get(
    "/api/v1/auth/me/",
    secure=True,
)
check(response.status_code == 200, "Admin authenticated")

# Lấy CSRF token hợp lệ.
response = client.get(
    "/api/v1/auth/csrf/",
    secure=True,
)
check(response.status_code == 200, "CSRF endpoint")
csrf_token = response.json()["csrfToken"]

# Thực hiện Logout.
response = client.post(
    "/api/v1/auth/logout/",
    secure=True,
    HTTP_X_CSRFTOKEN=csrf_token,
    HTTP_REFERER="https://127.0.0.1/",
)
print("LOGOUT HTTP:", response.status_code)
check(response.status_code == 200, "Logout successful")

# Kiểm tra client sau Logout.
response = client.get(
    "/api/v1/auth/me/",
    secure=True,
)
check(response.status_code == 401, "Session invalidated")

# Thử sử dụng lại session cũ.
replay_client = Client(
    HTTP_HOST="127.0.0.1",
)
replay_client.cookies["sessionid"] = old_session
response = replay_client.get(
    "/api/v1/auth/me/",
    secure=True,
)
check(response.status_code == 401, "Old session rejected")

print("ADMIN LOGOUT SECURITY: PASSED")
