"""Read-back ledger. NO cookies, request payloads, private tokens or raw HAR."""
import uuid
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class PostSubmissionReference(models.Model):
    """Immutable post identity recorded by trusted server-side submission adapter.

    This is a correlation hint, NOT independent evidence that a post is public.
    No CTV endpoint can create or modify it.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    job = models.OneToOneField('publishing.PublishingJob', on_delete=models.PROTECT,
                               related_name='submission_reference')
    account_id_snapshot = models.UUIDField()
    group_id_snapshot = models.UUIDField()
    external_post_id = models.CharField(max_length=200)
    source_id = models.CharField(max_length=100)
    submitted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_post_submission_references'
        constraints = [models.UniqueConstraint(
            fields=['pipeline', 'external_post_id'], name='pubreadback_submission_unique',
        )]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.job_id:
            job = self.job
            if (job.pipeline_id != self.pipeline_id
                    or job.facebook_account_id != self.account_id_snapshot
                    or job.facebook_group_id != self.group_id_snapshot):
                raise ValidationError('Submission reference không trùng Job/Pipeline/Account/Group.')
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Submission reference chỉ được ghi một lần.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PostReadbackAudit(models.Model):
    """One immutable outcome per authorized readback check key."""
    class Outcome(models.TextChoices):
        PENDING = 'pending', 'Chờ duyệt'
        REJECTED = 'rejected', 'Bị từ chối (chưa tự kết thúc Job)'
        INCONCLUSIVE = 'inconclusive', 'Không đủ kết luận'
        MISMATCH = 'mismatch', 'Thông tin đối chiếu không khớp'
        VERIFIED = 'verified', 'Xác minh độc lập đã xuất bản'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    job = models.ForeignKey('publishing.PublishingJob', on_delete=models.PROTECT,
                            related_name='readback_checks')
    request_key = models.UUIDField()
    source_id = models.CharField(max_length=100)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    error_code = models.CharField(max_length=64, blank=True, default='')
    observed_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_post_readback_audits'
        constraints = [models.UniqueConstraint(
            fields=['job', 'request_key'], name='pubreadback_request_unique',
        )]
        indexes = [models.Index(fields=['pipeline', '-checked_at'], name='pubreadback_pipeline_idx')]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.job_id and self.job.pipeline_id != self.pipeline_id:
            raise ValidationError({'job': 'Job thuộc Pipeline khác.'})
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Readback audit chỉ được ghi thêm.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
