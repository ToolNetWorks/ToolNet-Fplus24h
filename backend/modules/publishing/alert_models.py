"""Step 9.7.14: per-Pipeline operational alerts, never publication evidence.

Incident identity is (pipeline, code); events are append-only and contain no
credentials, HAR content, user-provided HTML or Facebook API response bodies.
"""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PublishingAlertIncident(models.Model):
    class State(models.TextChoices):
        OPEN = 'open', 'Cần theo dõi'
        RESOLVED = 'resolved', 'Đã hết cảnh báo'

    class Severity(models.TextChoices):
        WARNING = 'warning', 'Cảnh báo'
        CRITICAL = 'critical', 'Nghiêm trọng'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT,
                                 related_name='publishing_alerts')
    code = models.CharField(max_length=64)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN)
    version = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    seen_count = models.PositiveIntegerField(default=1)
    resolved_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.PROTECT)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_operational_alert_incidents'
        constraints = [models.UniqueConstraint(fields=['pipeline', 'code'],
                                               name='pubalert_unique_pipeline_code')]
        indexes = [models.Index(fields=['pipeline', 'state', '-updated_at'],
                                name='pubalert_pipeline_state_idx')]

    def clean(self):
        super().clean()
        if self.state == self.State.RESOLVED and not self.resolved_at:
            raise ValidationError('Resolved incident needs resolved_at.')
        if self.state == self.State.OPEN and self.resolved_at:
            raise ValidationError('Open incident cannot have resolved_at.')
        if self.acknowledged_by_id and self.pipeline_id:
            actor = self.acknowledged_by
            if not (actor.is_active and ((actor.is_superuser and actor.is_staff)
                                         or self.pipeline.ctv_id == actor.pk)):
                raise ValidationError('Acknowledging user belongs to another Pipeline.')


class PublishingAlertEvent(models.Model):
    class Kind(models.TextChoices):
        DETECTED = 'detected', 'Phát hiện'
        REOPENED = 'reopened', 'Tái phát'
        RESOLVED = 'resolved', 'Đã hết'
        ACKNOWLEDGED = 'acknowledged', 'Đã xem'
        SNOOZED = 'snoozed', 'Tạm ẩn'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(PublishingAlertIncident, on_delete=models.PROTECT,
                                 related_name='events')
    kind = models.CharField(max_length=16, choices=Kind.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_operational_alert_events'
        indexes = [models.Index(fields=['incident', '-recorded_at'],
                                name='pubalert_events_recent_idx')]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Alert events are append-only.')
        return super().save(*args, **kwargs)


class PublishingAlertScan(models.Model):
    """A healthy Pipeline with no incidents still needs a last scan timestamp."""
    pipeline = models.OneToOneField('pipelines.Pipeline', on_delete=models.PROTECT,
                                    primary_key=True, related_name='alert_scan')
    last_checked_at = models.DateTimeField()
    active_count = models.PositiveIntegerField(default=0)
    critical_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_operational_alert_scans'
