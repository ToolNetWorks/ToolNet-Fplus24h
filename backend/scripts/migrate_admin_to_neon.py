from django.contrib.auth import get_user_model
from django.db import transaction

from modules.pipelines.models import Pipeline


def migrate_admin():
    User = get_user_model()

    source = User.objects.using("default")
    target = User.objects.using("neon")

    # Guard: chỉ hỗ trợ trạng thái đã kiểm tra.
    if source.count() != 1:
        raise RuntimeError(
            "SQLite không có đúng 1 User. Dừng chuyển dữ liệu."
        )

    if Pipeline.objects.using("default").exists():
        raise RuntimeError(
            "SQLite có Pipeline. Cần chuyển toàn bộ quan hệ."
        )

    if target.exists():
        raise RuntimeError(
            "Neon đã có User. Không ghi đè dữ liệu."
        )

    admin = source.get()

    if not admin.is_superuser or not admin.is_staff:
        raise RuntimeError(
            "User nguồn không phải Admin."
        )

    # Sao chép password hash, không tạo mật khẩu mới.
    with transaction.atomic(using="neon"):
        new_admin = target.create(
            username=admin.username,
            email=admin.email,
            password=admin.password,
            first_name=admin.first_name,
            last_name=admin.last_name,
            is_active=admin.is_active,
            is_staff=admin.is_staff,
            is_superuser=admin.is_superuser,
            date_joined=admin.date_joined,
            last_login=admin.last_login,
        )

        if new_admin.password != admin.password:
            raise RuntimeError(
                "Password hash không khớp."
            )

        if not new_admin.is_superuser:
            raise RuntimeError(
                "Quyền Admin không hợp lệ."
            )

    print("ADMIN MIGRATION: SUCCESS")
    print("USERNAME:", new_admin.username)
    print("SUPERUSER:", new_admin.is_superuser)
    print("PASSWORD HASH: VERIFIED")
    print("NEON USERS:", target.count())


migrate_admin()
