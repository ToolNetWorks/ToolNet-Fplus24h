"""Step 9.7.15: immutable audit of explicit, local worker-lease quarantine.

No credentials, cookies, claim tokens or external Facebook payloads are stored.
"""
import uuid
from django.core.exceptions import ValidationError
from django.db import models


class WorkerLeaseEvent(models.Model):
    class Kind(models.TextChoices):
        QUARANTINED = 'quarantined', 'Expired lease moved to uncertain'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    job = models.ForeignKey('publishing.PublishingJob', on_delete=models.PROTECT,
                            related_name='worker_lease_events')
    attempt_number = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.QUARANTINED)
    previous_state = models.CharField(max_length=20)
    reason_code = models.CharField(max_length=64)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_worker_lease_events'
        constraints = [models.UniqueConstraint(
            fields=['job', 'attempt_number', 'kind'], name='pub_worker_lease_once',
        )]
        indexes = [models.Index(fields=['pipeline', '-recorded_at'],
                                name='pub_worker_lease_recent')]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.job_id and self.job.pipeline_id != self.pipeline_id:
            raise ValidationError('Worker event belongs to a foreign Pipeline.')
        if self.attempt_number < 1:
            raise ValidationError('Worker event requires a valid attempt.')
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Worker event is immutable and append-only.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
