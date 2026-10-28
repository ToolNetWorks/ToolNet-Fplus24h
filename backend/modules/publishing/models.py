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
