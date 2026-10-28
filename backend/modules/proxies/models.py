import ipaddress
import re
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import (
    MinValueValidator,
    MaxValueValidator,
)
from django.db import models
from modules.facebook_accounts.models import FacebookAccount
from modules.pipelines.models import Pipeline


class ProxyEndpoint(models.Model):
    class Protocol(models.TextChoices):
        HTTP = "http", "HTTP"
        HTTPS = "https", "HTTPS"
        SOCKS5 = "socks5", "SOCKS5"

    class HealthStatus(models.TextChoices):
        UNTESTED = "untested", "Chưa kiểm tra"
        HEALTHY = "healthy", "Hoạt động"
        FAILED = "failed", "Không kết nối được"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.PROTECT,
        related_name="proxies",
    )
    # One Facebook Account can have at most one proxy.
    # One ProxyEndpoint cannot be shared by two accounts.
    account = models.OneToOneField(
        FacebookAccount,
        on_delete=models.PROTECT,
        related_name="assigned_proxy",
        null=True,
        blank=True,
    )
    protocol = models.CharField(
        max_length=10,
        choices=Protocol.choices,
        default=Protocol.HTTP,
    )
    host = models.CharField(max_length=253)
    port = models.PositiveIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(65535),
        ],
    )
    is_enabled = models.BooleanField(default=True)
    health_status = models.CharField(
        max_length=20,
        choices=HealthStatus.choices,
        default=HealthStatus.UNTESTED,
    )
    exit_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
    )
    last_checked_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    notes = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publisher_proxies"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "pipeline",
                    "protocol",
                    "host",
                    "port",
                ],
                name="unique_pipeline_proxy_endpoint",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline", "is_enabled"],
                name="proxy_pipeline_enabled_idx",
            ),
        ]

    def clean(self):
        super().clean()
        host = (self.host or "").strip().lower()
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        if not host or "://" in host or any(
            char in host for char in "/@?#\\"
        ):
            raise ValidationError({
                "host": "Chỉ nhập IP hoặc hostname, không nhập URL."
            })
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # Syntax validation only. DNS/IP safety must
            # also be checked when connecting to a proxy.
            host = host.rstrip(".")
            if len(host) > 253:
                raise ValidationError({
                    "host": "Hostname quá dài."
                })
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise ValidationError({
                    "host": "Hostname không hợp lệ."
                }) from exc
            labels = host.split(".")
            if (
                len(labels) < 2
                or host == "localhost"
                or host.endswith((".local", ".internal", ".localhost"))
                or not all(
                    re.fullmatch(
                        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                        label,
                    )
                    for label in labels
                )
            ):
                raise ValidationError({
                    "host": "Hostname Proxy không hợp lệ."
                })
        else:
            if not address.is_global:
                raise ValidationError({
                    "host": "Không cho phép IP nội bộ hoặc loopback."
                })
            host = str(address)
        self.host = host
        if not self.account_id or not self.pipeline_id:
            return
        owner_id = (
            FacebookAccount.objects
            .filter(pk=self.account_id)
            .values_list("pipeline_id", flat=True)
            .first()
        )
        if owner_id is not None and owner_id != self.pipeline_id:
            raise ValidationError({
                "account": (
                    "Facebook Account không thuộc Pipeline này."
                ),
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.protocol}://{self.host}:{self.port}"


class ProxyAuthSecret(models.Model):
    """
    Encrypted proxy credentials only.
    The API must encrypt credentials before saving.
    Never return ciphertext or passwords to React.
    """
    proxy = models.OneToOneField(
        ProxyEndpoint,
        on_delete=models.CASCADE,
        related_name="auth_secret",
        primary_key=True,
    )
    ciphertext = models.TextField()
    key_version = models.PositiveSmallIntegerField(
        default=1,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publisher_proxy_auth_secrets"
