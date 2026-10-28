import uuid
from django.db import models
from modules.pipelines.models import Pipeline
from .validators import normalize_facebook_group_url
class FacebookGroup(models.Model):
    class VerificationStatus(models.TextChoices):
        UNKNOWN = "unknown", "Chưa xác minh"
        VERIFIED = "verified", "Đã xác minh"
        UNAVAILABLE = "unavailable", "Không truy cập được"
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.PROTECT,
        related_name="facebook_groups",
    )
    name = models.CharField(
        max_length=200,
    )
    group_url = models.URLField(
        max_length=500,
    )
    group_key = models.CharField(
        max_length=150,
        editable=False,
    )
    is_enabled = models.BooleanField(
        default=True,
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNKNOWN,
        db_index=True,
    )
    notes = models.TextField(
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )
    class Meta:
        db_table = "publisher_facebook_groups"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "group_key"],
                name="unique_group_per_pipeline",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline", "is_enabled"],
                name="fbgrp_pipeline_enabled_idx",
            ),
        ]
    def clean(self):
        super().clean()
        self.name = (self.name or "").strip()
        if not self.name:
            from django.core.exceptions import ValidationError
            raise ValidationError({
                "name": "Tên Group không được để trống."
            })
        self.group_key, self.group_url = (
            normalize_facebook_group_url(
                self.group_url
            )
        )
    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
    def __str__(self):
        return f"{self.name} [{self.pipeline_id}]"
