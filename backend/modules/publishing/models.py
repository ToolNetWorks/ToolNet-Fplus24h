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


class PublishingJob(models.Model):
    """One intended group post. External network publication is NOT implemented here."""

    class State(models.TextChoices):
        QUEUED = "queued", "Chờ xử lý"
        CLAIMED = "claimed", "Worker đã nhận"
        READY = "ready", "Đã chuẩn bị ảnh"
        DISPATCHING = "dispatching", "Đã cho phép thử đăng"
        UNCERTAIN = "uncertain", "Chờ đối soát"
        PUBLISHED = "published", "Đã xác minh đăng thành công"
        FAILED = "failed", "Lỗi trước khi đăng"
        CANCELLED = "cancelled", "Đã hủy"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey(
        Pipeline, on_delete=models.PROTECT, related_name="publishing_jobs",
    )
    facebook_account = models.ForeignKey(
        "facebook_accounts.FacebookAccount", on_delete=models.PROTECT,
        related_name="publishing_jobs",
    )
    facebook_group = models.ForeignKey(
        "facebook_groups.FacebookGroup", on_delete=models.PROTECT,
        related_name="publishing_jobs",
    )
    request_key = models.CharField(max_length=128)
    caption = models.TextField(blank=True, default="", max_length=5000)
    state = models.CharField(
        max_length=20, choices=State.choices, default=State.QUEUED,
    )
    scheduled_at = models.DateTimeField()
    next_run_at = models.DateTimeField()
    max_attempts = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    worker_id = models.CharField(max_length=100, blank=True, default="")
    # Secret worker token. Never serialize to CTV or Admin API responses.
    claim_token = models.CharField(max_length=100, blank=True, default="")
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    media_allocation = models.ForeignKey(
        "publishing.MediaAllocation", on_delete=models.PROTECT,
        null=True, blank=True, related_name="publishing_jobs",
    )
    external_post_id = models.CharField(max_length=200, blank=True, default="")
    error_code = models.CharField(max_length=80, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "publisher_publishing_jobs"
        ordering = ["scheduled_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline", "request_key"],
                name="unique_publishing_job_request",
            ),
            models.UniqueConstraint(
                fields=["pipeline", "external_post_id"],
                condition=~Q(external_post_id=""),
                name="unique_pubjob_external_post",
            ),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1) & Q(max_attempts__lte=5),
                name="pubjob_max_attempts_range",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__gte=0) & Q(attempt_count__lte=5),
                name="pubjob_attempt_count_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline", "state", "next_run_at"],
                name="pubjob_queue_idx",
            ),
            models.Index(
                fields=["pipeline", "state", "lease_expires_at"],
                name="pubjob_lease_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.facebook_account_id:
            from modules.facebook_accounts.models import FacebookAccount
            if not FacebookAccount.objects.filter(
                pk=self.facebook_account_id, pipeline_id=self.pipeline_id,
            ).exists():
                raise ValidationError({"facebook_account": "Tài khoản sai Pipeline."})
        if self.pipeline_id and self.facebook_group_id:
            from modules.facebook_groups.models import FacebookGroup
            if not FacebookGroup.objects.filter(
                pk=self.facebook_group_id, pipeline_id=self.pipeline_id,
            ).exists():
                raise ValidationError({"facebook_group": "Group sai Pipeline."})
        if self.pipeline_id and self.media_allocation_id:
            if not MediaAllocation.objects.filter(
                pk=self.media_allocation_id, pipeline_id=self.pipeline_id,
            ).exists():
                raise ValidationError({"media_allocation": "Cấp phát ảnh sai Pipeline."})
        if self.attempt_count > self.max_attempts:
            raise ValidationError({"attempt_count": "Quá số lần thử."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PublishingAttempt(models.Model):
    """Immutable attempt number and media allocation history per Job."""

    class State(models.TextChoices):
        CLAIMED = "claimed", "Đã nhận"
        READY = "ready", "Có ảnh"
        DISPATCHING = "dispatching", "Đã bắt đầu thử đăng"
        UNCERTAIN = "uncertain", "Cần đối soát"
        PUBLISHED = "published", "Đã xác minh"
        RELEASED = "released", "Đã giải phóng trước khi đăng"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        PublishingJob, on_delete=models.PROTECT, related_name="attempts",
    )
    number = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    media_allocation = models.OneToOneField(
        MediaAllocation, null=True, blank=True,
        on_delete=models.PROTECT, related_name="publishing_attempt",
    )
    state = models.CharField(
        max_length=20, choices=State.choices, default=State.CLAIMED,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "publisher_publishing_attempts"
        ordering = ["number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "number"], name="unique_pubjob_attempt_number",
            ),
        ]

    def clean(self):
        super().clean()
        if self.job_id and self.media_allocation_id:
            if not MediaAllocation.objects.filter(
                pk=self.media_allocation_id,
                pipeline_id=self.job.pipeline_id,
            ).exists():
                raise ValidationError({"media_allocation": "Cấp phát ảnh sai Pipeline."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


# Scheduling models live in their own module.
from .scheduler_models import (
    PipelineSchedule, AccountGroupEligibility, GroupHealth,
    AccountProxyPin, ScheduledBatch, ScheduledAssignment,
)

from .scheduler_tick_models import SchedulerTickAudit
