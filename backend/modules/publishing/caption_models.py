"""Pipeline-scoped AI caption content. Never store provider credentials here."""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PipelineCaptionSettings(models.Model):
    pipeline = models.OneToOneField('pipelines.Pipeline', primary_key=True,
        on_delete=models.PROTECT, related_name='caption_settings')
    destination = models.CharField(max_length=64, blank=True, default='')
    enabled = models.BooleanField(default=False)
    auto_generate = models.BooleanField(default=False)
    auto_approve = models.BooleanField(default=False)
    writing_guidance = models.TextField(max_length=2000, blank=True, default='')
    version = models.PositiveIntegerField(default=1)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_caption_settings'


class CaptionSample(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT,
        related_name='caption_samples')
    text = models.TextField(max_length=1500)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
        on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_caption_samples'
        indexes = [models.Index(fields=['pipeline', 'is_active', '-created_at'],
                                name='caption_sample_filter_idx')]

    def clean(self):
        if not self.text.strip():
            raise ValidationError('Caption mẫu không được để trống.')


class JobCaption(models.Model):
    class State(models.TextChoices):
        GENERATING = 'generating', 'Đang tạo'
        DRAFT = 'draft', 'Chờ duyệt'
        APPROVED = 'approved', 'Đã duyệt'
        FAILED = 'failed', 'Tạo thất bại'
        REJECTED = 'rejected', 'Đã từ chối'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    job = models.OneToOneField('publishing.PublishingJob', on_delete=models.PROTECT,
                               related_name='ai_caption')
    state = models.CharField(max_length=16, choices=State.choices, default=State.GENERATING)
    text = models.TextField(max_length=5000, blank=True, default='')
    destination_snapshot = models.CharField(max_length=64, blank=True, default='')
    settings_version = models.PositiveIntegerField(default=0)
    model_name = models.CharField(max_length=120, blank=True, default='')
    generation_token = models.UUIDField(null=True, blank=True)
    generation_started_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_job_captions'
        indexes = [models.Index(fields=['pipeline', 'state', '-updated_at'],
                                name='caption_job_state_idx')]

    def clean(self):
        if self.job_id and self.pipeline_id and self.job.pipeline_id != self.pipeline_id:
            raise ValidationError('Caption Job phải thuộc cùng Pipeline.')


class CaptionRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_caption = models.ForeignKey(JobCaption, on_delete=models.PROTECT,
                                    related_name='revisions')
    revision = models.PositiveIntegerField()
    action = models.CharField(max_length=32)
    text = models.TextField(max_length=5000)
    destination = models.CharField(max_length=64)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL)
    model_name = models.CharField(max_length=120, blank=True, default='')
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_caption_revisions'
        constraints = [models.UniqueConstraint(fields=['job_caption', 'revision'],
                                                name='unique_caption_revision')]


class CaptionSettingsEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    destination_before = models.CharField(max_length=64, blank=True, default='')
    destination_after = models.CharField(max_length=64, blank=True, default='')
    settings_version = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                              on_delete=models.SET_NULL)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_caption_settings_events'
        indexes = [models.Index(fields=['pipeline', '-recorded_at'],
                                name='caption_settings_audit_idx')]
