import uuid
from urllib.parse import urlsplit
from django.core.exceptions import ValidationError
from django.db import models
from modules.pipelines.models import Pipeline
ALLOWED_FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "web.facebook.com",
    "fb.com",
    "www.fb.com",
}
class FacebookAccount(models.Model):
    class ConnectionStatus(models.TextChoices):
        NOT_CONNECTED = (
            "not_connected",
            "Chưa kết nối",
        )
        CONNECTED = (
            "connected",
            "Đã kết nối",
        )
        EXPIRED = (
            "expired",
            "Hết phiên",
        )
        DISABLED = (
            "disabled",
            "Đã vô hiệu hóa",
        )
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.PROTECT,
        related_name="facebook_accounts",
    )
    label = models.CharField(
        max_length=150,
    )
    profile_url = models.URLField(
        max_length=500,
        blank=True,
    )
    # Chỉ gán ID sau khi xác minh danh tính thực sự.
    facebook_user_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        editable=False,
    )
    connection_status = models.CharField(
        max_length=20,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.NOT_CONNECTED,
        db_index=True,
    )
    last_verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )
    class Meta:
        db_table = "publisher_facebook_accounts"
        ordering = [
            "-created_at",
            "-id",
        ]
        indexes = [
            models.Index(
                fields=[
                    "pipeline",
                    "connection_status",
                ],
                name="fbacct_pipeline_status_idx",
            ),
        ]
    def clean(self):
        super().clean()
        if not self.label.strip():
            raise ValidationError({
                "label": "Tên tài khoản không được để trống."
            })
        self.label = self.label.strip()
        if not self.profile_url:
            return
        parsed = urlsplit(self.profile_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ALLOWED_FACEBOOK_HOSTS
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValidationError({
                "profile_url": (
                    "Chỉ chấp nhận URL Facebook HTTPS hợp lệ."
                )
            })
    def __str__(self):
        return f"{self.label} [{self.pipeline_id}]"
# Register the separate encrypted credential model.
from .credentials import FacebookCookieSecret  # noqa: E402,F401
