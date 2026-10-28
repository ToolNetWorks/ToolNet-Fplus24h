from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.db import connection

from modules.pipelines.models import Pipeline


def check_dashboard():
    if connection.vendor != "postgresql":
        raise RuntimeError(
            "Database chính chưa phải PostgreSQL."
        )

    User = get_user_model()

    admin = User.objects.filter(
        is_superuser=True,
        is_active=True,
    ).first()

    if admin is None:
        raise RuntimeError(
            "Không tìm thấy tài khoản Admin trên Neon."
        )

    url = reverse("adminpanel:dashboard")
    client = Client(HTTP_HOST="127.0.0.1")

    # Người chưa đăng nhập phải bị chuyển hướng.
    response = client.get(url)

    if response.status_code != 302:
        raise RuntimeError(
            "Anonymous access không được chặn."
        )

    print("ANONYMOUS ACCESS: BLOCKED")

    # Kiểm tra phiên đăng nhập Admin.
    client.force_login(admin)
    response = client.get(url)

    if response.status_code != 200:
        raise RuntimeError(
            f"Admin Dashboard HTTP {response.status_code}"
        )

    if b"Dashboard" not in response.content:
        raise RuntimeError(
            "Dashboard không hiển thị đúng HTML."
        )

    print("ADMIN DASHBOARD: HTTP 200")
    print("DATABASE:", connection.vendor)
    print("TOTAL PIPELINES:", Pipeline.objects.count())
    print("TOTAL USERS:", User.objects.count())
    print("DASHBOARD CHECK: PASSED")


check_dashboard()
