import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Pipeline(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Hoạt động"
        DISABLED = "disabled", "Tạm khóa"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(
        "Tên Pipeline",
        max_length=150,
        unique=True,
    )

    ctv = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pipeline",
        verbose_name="Tài khoản CTV",
    )

    status = models.CharField(
        "Trạng thái",
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if not self.ctv_id:
            return

        if self.ctv.is_staff or self.ctv.is_superuser:
            raise ValidationError({
                "ctv": "Không thể gán tài khoản quản trị làm CTV."
            })

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Pipeline"
        verbose_name_plural = "Danh sách Pipeline"
        ordering = ["-created_at"]


class CTVAdminAuditLog(models.Model):
    """Immutable audit trail for CTV management actions by Super Admin."""

    class Action(models.TextChoices):
        CREATE_CTV = "create_ctv", "Tạo CTV"
        LOCK_CTV = "lock_ctv", "Khóa CTV"
        UNLOCK_CTV = "unlock_ctv", "Mở khóa CTV"
        RESET_PASSWORD = "reset_password", "Đặt lại mật khẩu"

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ctv_admin_audit_logs",
        verbose_name="Admin thực hiện",
    )

    admin_username = models.CharField(
        "Username Admin",
        max_length=150,
    )

    action = models.CharField(
        "Hành động",
        max_length=32,
        choices=Action.choices,
    )

    pipeline_id = models.UUIDField(
        "ID Pipeline",
        null=True,
        blank=True,
    )

    pipeline_name = models.CharField(
        "Tên Pipeline",
        max_length=150,
    )

    ctv_id = models.BigIntegerField(
        "ID CTV",
        null=True,
        blank=True,
    )

    ctv_username = models.CharField(
        "Username CTV",
        max_length=150,
    )

    created_at = models.DateTimeField(
        "Thời gian",
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        verbose_name = "Audit quản lý CTV"
        verbose_name_plural = "Audit quản lý CTV"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["action", "-created_at"],
                name="ctvaudit_action_time_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_action_display()} - "
            f"{self.ctv_username}"
        )
