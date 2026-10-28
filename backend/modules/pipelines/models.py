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
