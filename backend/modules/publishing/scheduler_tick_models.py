"""Per-slot Scheduler Tick audit. No credentials or Facebook request content."""
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from modules.publishing.scheduler_models import PipelineSchedule


class SchedulerTickAudit(models.Model):
    """Single audit row per schedule slot, updated on retries/reconciliation.

    ScheduledBatch remains the source of truth for successfully queued Jobs.
    This audit exists for visibility into failed or replayed Scheduler ticks.
    """

    class Outcome(models.TextChoices):
        QUEUED = 'queued', 'Đã tạo hàng đợi'
        REPLAYED = 'replayed', 'Batch đã tồn tại'
        ERROR = 'error', 'Lỗi lập lịch'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT,
                                 related_name='scheduler_tick_audits')
    schedule = models.ForeignKey('publishing.PipelineSchedule', on_delete=models.PROTECT,
                                 related_name='tick_audits')
    slot_at = models.DateTimeField()
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    assigned_count = models.PositiveSmallIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    attempt_count = models.PositiveIntegerField(default=1)
    worker_id = models.CharField(max_length=100)
    error_code = models.CharField(max_length=80, blank=True, default='')
    batch_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_scheduler_tick_audits'
        constraints = [
            models.UniqueConstraint(fields=['schedule', 'slot_at'],
                                    name='pubtick_unique_slot'),
            models.CheckConstraint(condition=Q(attempt_count__gte=1),
                                   name='pubtick_attempt_positive'),
        ]
        indexes = [
            models.Index(fields=['pipeline', '-updated_at'],
                         name='pubtick_pipeline_latest_idx'),
            models.Index(fields=['outcome', 'updated_at'],
                         name='pubtick_outcome_time_idx'),
        ]

    def clean(self):
        super().clean()
        if self.schedule_id and self.pipeline_id:
            if not PipelineSchedule.objects.filter(
                pk=self.schedule_id, pipeline_id=self.pipeline_id,
            ).exists():
                raise ValidationError({'schedule': 'Schedule thuộc Pipeline khác.'})
        if not self.worker_id or len(self.worker_id) > 100:
            raise ValidationError({'worker_id': 'Worker ID không hợp lệ.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
