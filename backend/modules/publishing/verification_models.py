"""Immutable, minimal observations and trusted verification receipts.

Never store HAR contents, cookies, CSRF values, auth headers or raw requests.
An observation is NOT proof that a Facebook Group post is visible.
"""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PostVerificationObservation(models.Model):
    class Source(models.TextChoices):
        MANUAL = 'manual_review', 'Manual observation'
        SANITIZED_HAR = 'sanitized_har', 'Sanitized HAR summary'

    class Outcome(models.TextChoices):
        SUBMITTED = 'submitted', 'Submission acknowledged'
        PENDING = 'pending_moderation', 'Pending Group approval'
        VISIBLE_REPORTED = 'visible_reported', 'Visibility reported, not verified'
        REJECTED_REPORTED = 'rejected_reported', 'Rejection reported, not verified'
        INCONCLUSIVE = 'inconclusive', 'Not conclusive'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    job = models.ForeignKey('publishing.PublishingJob', on_delete=models.PROTECT,
                            related_name='verification_observations')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.UUIDField()
    source = models.CharField(max_length=20, choices=Source.choices)
    outcome = models.CharField(max_length=24, choices=Outcome.choices)
    note = models.TextField(max_length=1000)
    evidence_url = models.URLField(max_length=800, blank=True, default='')
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_post_verification_observations'
        ordering = ['-recorded_at', '-pk']
        constraints = [models.UniqueConstraint(
            fields=['job', 'idempotency_key'], name='pubverify_observation_idempotent',
        )]
        indexes = [models.Index(fields=['pipeline', '-recorded_at'], name='pubverify_observation_idx')]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.job_id and self.job.pipeline_id != self.pipeline_id:
            raise ValidationError({'job': 'Job không thuộc Pipeline.'})
        if self.pipeline_id and self.actor_id and not (
            self.actor.is_staff and self.actor.is_superuser
        ) and self.pipeline.ctv_id != self.actor_id:
            raise ValidationError({'actor': 'Người ghi không thuộc Pipeline.'})
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Observation là bất biến; chỉ được ghi thêm.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TrustedPostVerification(models.Model):
    """Created only by an explicitly configured, server-side readback adapter."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    job = models.OneToOneField('publishing.PublishingJob', on_delete=models.PROTECT,
                               related_name='trusted_verification')
    external_post_id = models.CharField(max_length=200)
    verifier_id = models.CharField(max_length=100)
    observed_at = models.DateTimeField()
    verified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_trusted_post_verifications'
        constraints = [models.UniqueConstraint(
            fields=['pipeline', 'external_post_id'], name='pubverify_one_post_per_pipeline',
        )]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.job_id and self.job.pipeline_id != self.pipeline_id:
            raise ValidationError({'job': 'Job không thuộc Pipeline.'})
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Trusted verification là bất biến.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
