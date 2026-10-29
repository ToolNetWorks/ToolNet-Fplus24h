"""Step 9.7.16 — explicit, human-operated Facebook Group handoff.

Only metadata, never a session, HAR, token or private GraphQL payload.
A manual report is *not* independently verified publication.
"""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ManualPublishingHandoff(models.Model):
    class State(models.TextChoices):
        PREPARED = 'prepared', 'Đã chuẩn bị nội dung'
        OPENED = 'opened', 'Đã chuyển sang Facebook'
        SUBMITTED = 'submitted_reported', 'CTV báo đã gửi'
        PENDING = 'pending_reported', 'CTV báo đang chờ duyệt'
        REJECTED = 'rejected_reported', 'CTV báo bị từ chối'
        INCONCLUSIVE = 'inconclusive', 'Chưa rõ kết quả'
        ABANDONED = 'abandoned', 'Đã hủy trước khi mở Facebook'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    job = models.OneToOneField('publishing.PublishingJob', on_delete=models.PROTECT,
                               related_name='manual_handoff')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    state = models.CharField(max_length=24, choices=State.choices, default=State.PREPARED)
    version = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=500, blank=True, default='')
    prepared_at = models.DateTimeField(auto_now_add=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_manual_handoffs'
        indexes = [models.Index(fields=['pipeline', 'state', '-updated_at'],
                                name='manual_handoff_idx')]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.job_id and self.job.pipeline_id != self.pipeline_id:
            raise ValidationError('Handoff thuộc Job của Pipeline khác.')
        if self.pipeline_id and self.actor_id:
            if not (self.actor.is_active and (
                (self.actor.is_staff and self.actor.is_superuser)
                or self.pipeline.ctv_id == self.actor_id
            )):
                raise ValidationError('Người thao tác không thuộc Pipeline.')
        if self.state != self.State.PREPARED and self.state != self.State.ABANDONED and not self.opened_at:
            raise ValidationError('Chưa ghi nhận mở Facebook.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ManualPublishingEvent(models.Model):
    class Kind(models.TextChoices):
        PREPARED = 'prepared', 'Chuẩn bị'
        OPENED = 'opened', 'Mở Facebook'
        REPORTED = 'reported', 'Ghi nhận quan sát'
        ABANDONED = 'abandoned', 'Hủy trước khi thao tác'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    handoff = models.ForeignKey(ManualPublishingHandoff, on_delete=models.PROTECT,
                                related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    outcome = models.CharField(max_length=24, blank=True, default='')
    note = models.CharField(max_length=500, blank=True, default='')
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_manual_handoff_events'
        indexes = [models.Index(fields=['handoff', '-recorded_at'],
                                name='manual_handoff_event_idx')]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('ManualPublishingEvent là nhật ký chỉ ghi thêm.')
        return super().save(*args, **kwargs)
