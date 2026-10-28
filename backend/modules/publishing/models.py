import uuid
from django.core.exceptions import ValidationError
from django.core.validators import (
    MinValueValidator,
    MaxValueValidator,
)
from django.db import models
from django.db.models import Q
from modules.albums.models import Album
from modules.pipelines.models import Pipeline


class PipelineMediaPolicy(models.Model):
    """
    Image selection configuration of exactly one Pipeline.
    This is configuration only. Actual image usage will
    be tracked by the future publishing scheduler.
    """
    class SelectionMode(models.TextChoices):
        IN_ORDER = "in_order", "Theo thứ tự"
        RANDOM = "random", "Ngẫu nhiên"

    class ReusePolicy(models.TextChoices):
        NO_REPEAT = "no_repeat", "Không lặp"
        CYCLE = "cycle", "Quay vòng"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    pipeline = models.OneToOneField(
        Pipeline,
        on_delete=models.PROTECT,
        related_name="media_policy",
    )
    is_enabled = models.BooleanField(default=False)
    album_selection = models.CharField(
        max_length=20,
        choices=SelectionMode.choices,
        default=SelectionMode.IN_ORDER,
    )
    image_selection = models.CharField(
        max_length=20,
        choices=SelectionMode.choices,
        default=SelectionMode.IN_ORDER,
    )
    reuse_policy = models.CharField(
        max_length=20,
        choices=ReusePolicy.choices,
        default=ReusePolicy.NO_REPEAT,
    )
    images_per_post = models.PositiveSmallIntegerField(
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(10),
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publisher_media_policies"
        verbose_name = "Pipeline Media Policy"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(images_per_post__gte=1)
                    & Q(images_per_post__lte=10)
                ),
                name="media_images_count_range",
            ),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"Media policy: {self.pipeline_id}"


class PipelineAlbumSource(models.Model):
    """
    Album selected as a publishing source.
    A source and its album must belong to the same
    Pipeline. Position controls album priority.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.PROTECT,
        related_name="album_sources",
    )
    album = models.ForeignKey(
        Album,
        on_delete=models.PROTECT,
        related_name="publishing_sources",
    )
    position = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
    )
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publisher_album_sources"
        ordering = [
            "position",
            "id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "album"],
                name="unique_pipeline_album_source",
            ),
            models.UniqueConstraint(
                fields=["pipeline", "position"],
                name="unique_pipeline_album_position",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline", "is_enabled"],
                name="src_pipeline_enabled_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.pipeline_id or not self.album_id:
            return
        album_pipeline_id = (
            Album.objects
            .filter(pk=self.album_id)
            .values_list("pipeline_id", flat=True)
            .first()
        )
        if (
            album_pipeline_id is not None
            and album_pipeline_id != self.pipeline_id
        ):
            raise ValidationError({
                "album": (
                    "Album không thuộc Pipeline hiện tại."
                ),
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.pipeline_id} -> "
            f"{self.album_id} ({self.position})"
        )


class MediaAllocation(models.Model):
    """Idempotent image lease for one future publishing job.

    Publishing must confirm an allocation *only after* the external post
    is verified. An uncertain result must never be silently released.
    No Facebook operations are implemented here.
    """

    class State(models.TextChoices):
        RESERVED = "reserved", "Đang giữ chỗ"
        CONSUMED = "consumed", "Đã sử dụng"
        RELEASED = "released", "Đã giải phóng"
        UNCERTAIN = "uncertain", "Chưa rõ kết quả đăng"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey(
        Pipeline, on_delete=models.PROTECT, related_name="media_allocations",
    )
    # Caller supplies a stable, non-secret, per-job idempotency key.
    request_key = models.CharField(max_length=128)
    state = models.CharField(
        max_length=12, choices=State.choices, default=State.RESERVED,
    )
    images_requested = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    # The cycle is advanced *only* by Media Selection Engine (Step 9.6.2).
    cycle_number = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)],
    )
    # Policy is snapshotted for audit; credentials / R2 secrets never belong here.
    policy_snapshot = models.JSONField(default=dict)
    policy_version = models.CharField(max_length=50, blank=True, default="")
    lease_expires_at = models.DateTimeField()
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publisher_media_allocations"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "request_key"],
                name="unique_media_allocation_request",
            ),
            models.CheckConstraint(
                condition=Q(images_requested__gte=1) & Q(images_requested__lte=10),
                name="media_allocation_images_range",
            ),
            models.CheckConstraint(
                condition=Q(cycle_number__gte=1),
                name="media_allocation_cycle_positive",
            ),
            models.CheckConstraint(
                condition=Q(state__in=["reserved", "consumed", "released", "uncertain"]),
                name="media_allocation_state_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline", "state", "lease_expires_at"],
                name="media_alloc_lease_idx",
            ),
            models.Index(
                fields=["pipeline", "cycle_number", "state"],
                name="media_alloc_cycle_idx",
            ),
        ]

    def clean(self):
        super().clean()
        self.request_key = (self.request_key or "").strip()
        if not self.request_key:
            raise ValidationError({"request_key": "Thiếu khóa tác vụ cấp phát."})
        if not isinstance(self.policy_snapshot, dict):
            raise ValidationError({"policy_snapshot": "Chính sách chụp lại không hợp lệ."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class MediaAllocationItem(models.Model):
    """Immutable identity snapshot for each selected image.

    AlbumImage can later be deleted from R2 after allocation is finalized;
    image_uuid and album_uuid keep usage history available. Future reserve
    logic must hold the Pipeline/Album locks when choosing these rows.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    allocation = models.ForeignKey(
        MediaAllocation, on_delete=models.PROTECT, related_name="items",
    )
    image = models.ForeignKey(
        "albums.AlbumImage", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="media_allocation_items",
    )
    image_uuid = models.UUIDField()
    album_uuid = models.UUIDField()
    position = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "publisher_media_allocation_items"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["allocation", "image_uuid"],
                name="unique_media_alloc_image",
            ),
            models.UniqueConstraint(
                fields=["allocation", "position"],
                name="unique_media_alloc_position",
            ),
            models.CheckConstraint(
                condition=Q(position__gte=1) & Q(position__lte=10),
                name="media_alloc_item_position_range",
            ),
        ]
        indexes = [
            models.Index(fields=["image_uuid"], name="media_alloc_image_idx"),
        ]

    def clean(self):
        super().clean()
        if not self.allocation_id or not self.image_id:
            return
        # Validate tenant isolation and immutable snapshot when image exists.
        identity = (
            self.image.__class__.objects
            .filter(pk=self.image_id)
            .values_list("album_id", "album__pipeline_id")
            .first()
        )
        if identity is None:
            raise ValidationError({"image": "Ảnh không tồn tại."})
        album_id, pipeline_id = identity
        if pipeline_id != self.allocation.pipeline_id:
            raise ValidationError({"image": "Ảnh thuộc Pipeline khác."})
        if self.image_uuid != self.image_id or self.album_uuid != album_id:
            raise ValidationError("Định danh ảnh/Album đã chụp lại không khớp.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
