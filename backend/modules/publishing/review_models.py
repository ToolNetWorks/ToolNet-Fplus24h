"""Human review workflow for ambiguous PublishingJobs. Does not alter job state."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class PublishingReviewCase(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Mới tạo'
        IN_REVIEW = 'in_review', 'Đang xử lý'
        AWAITING = 'awaiting_verification', 'Chờ xác minh'
        CLOSED = 'closed', 'Đã hoàn tất'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    job = models.OneToOneField('publishing.PublishingJob', on_delete=models.PROTECT,
                               related_name='review_case')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    null=True, blank=True, related_name='publishing_reviews')
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    version = models.PositiveIntegerField(default=1)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_review_cases'
        indexes = [
            models.Index(fields=['pipeline', 'status', '-updated_at'], name='pubreview_case_list_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(version__gte=1), name='pubreview_case_version_pos'),
        ]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.job_id:
            if not self.job.__class__.objects.filter(pk=self.job_id, pipeline_id=self.pipeline_id).exists():
                raise ValidationError({'job': 'Job không thuộc Pipeline.'})
        if self.pipeline_id and self.assigned_to_id:
            if not self.pipeline.__class__.objects.filter(
                    pk=self.pipeline_id, ctv_id=self.assigned_to_id).exists():
                raise ValidationError({'assigned_to': 'Người xử lý phải là CTV của Pipeline.'})
        if self.status == self.Status.CLOSED and not self.closed_at:
            raise ValidationError({'closed_at': 'Hồ sơ đã đóng cần thời điểm đóng.'})
        if self.status != self.Status.CLOSED and self.closed_at:
            raise ValidationError({'closed_at': 'Không được đóng hồ sơ đang xử lý.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PublishingReviewEvent(models.Model):
    class Kind(models.TextChoices):
        OPENED = 'opened', 'Tạo hồ sơ'
        ASSIGNED = 'assigned', 'Nhận hồ sơ'
        UNASSIGNED = 'unassigned', 'Trả hồ sơ'
        EVIDENCE = 'evidence', 'Ghi bằng chứng'
        ESCALATED = 'escalated', 'Yêu cầu xác minh'
        CLOSED = 'closed', 'Đóng hồ sơ sau khi Job đã kết thúc'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(PublishingReviewCase, on_delete=models.PROTECT, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    note = models.TextField(max_length=2000, blank=True, default='')
    evidence_url = models.URLField(max_length=1000, blank=True, default='')
    job_state_snapshot = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_review_events'
        ordering = ['created_at', 'pk']
        indexes = [models.Index(fields=['case', 'created_at'], name='pubreview_case_events_idx')]

    def clean(self):
        super().clean()
        if self.case_id and self.actor_id:
            if not self.case.pipeline.__class__.objects.filter(
                    pk=self.case.pipeline_id, ctv_id=self.actor_id).exists() and not (
                        self.actor.is_staff and self.actor.is_superuser):
                raise ValidationError({'actor': 'Người ghi không có quyền trên Pipeline.'})
        if self.pk and self.__class__.objects.filter(pk=self.pk).exists():
            raise ValidationError('Sự kiện đối soát là bất biến, chỉ được ghi thêm.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
