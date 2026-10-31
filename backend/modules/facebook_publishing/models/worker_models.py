"""Immutable audit models for the Facebook Publishing Worker.

Tracks the Worker's internal publishing lifecycle, separate from PublishingJob.
Never stores cookies, tokens, CSRF values, or proxy credentials.
"""
import re
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

RESULT_RE = re.compile(r'^[A-Z][A-Z0-9_]{0,63}$')


class WorkerResultState(models.TextChoices):
    """Worker-level publishing states. Cross-checked against PublishingJob.State."""
    QUEUED = 'queued', 'Queued'
    PREPARING = 'preparing', 'Preparing'
    READY = 'ready', 'Ready'
    SUBMITTING = 'submitting', 'Submitting'
    SUBMITTED_UNVERIFIED = 'submitted_unverified', 'Submitted Unverified'
    PENDING_APPROVAL = 'pending_approval', 'Pending Approval'
    PUBLISHED = 'published', 'Published'
    REJECTED = 'rejected', 'Rejected'
    FAILED = 'failed', 'Failed'
    UNCERTAIN = 'uncertain', 'Uncertain'


class ConnectionMode(models.TextChoices):
    DIRECT = 'direct', 'Direct connection (no proxy)'
    PROXY = 'proxy', 'Via pinned proxy'


class WorkerConfig(models.Model):
    """Per-Pipeline Facebook Publishing Worker enablement and dry-run flag."""

    pipeline = models.OneToOneField(
        'pipelines.Pipeline', on_delete=models.PROTECT,
        related_name='fb_publishing_config',
    )
    enabled = models.BooleanField(
        default=False,
        help_text='MASTER SWITCH. Must be explicitly set to True in production.',
    )
    dry_run = models.BooleanField(
        default=True,
        help_text='Validate everything but never click Post or create a real post.',
    )
    connection_mode = models.CharField(
        max_length=10,
        choices=ConnectionMode.choices,
        default=ConnectionMode.PROXY,
        help_text='DIRECT: connect directly via VPS IP; PROXY: use pinned proxy.',
    )
    browser_timeout_seconds = models.PositiveIntegerField(
        default=120, validators=[MinValueValidator(10), ],
    )
    max_retry_attempts = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fb_publishing_worker_config'

    def clean(self):
        super().clean()
        if self.enabled and not getattr(self.pipeline, 'ctv', None):
            raise ValidationError({'pipeline': 'Pipeline without CTV cannot be enabled.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class WorkerPublishJob(models.Model):
    """Worker-tracked publishing lifecycle for a single PublishingJob.

    References the authoritative PublishingJob row for cross-checking state.
    """

    job = models.OneToOneField(
        'publishing.PublishingJob', on_delete=models.PROTECT,
        related_name='fb_worker_job',
    )
    pipeline = models.ForeignKey(
        'pipelines.Pipeline', on_delete=models.PROTECT,
        related_name='fb_publishing_jobs',
    )
    account = models.ForeignKey(
        'facebook_accounts.FacebookAccount', on_delete=models.PROTECT,
    )
    group = models.ForeignKey(
        'facebook_groups.FacebookGroup', on_delete=models.PROTECT,
    )
    proxy = models.ForeignKey(
        'proxies.ProxyEndpoint', on_delete=models.PROTECT,
        null=True, blank=True,
    )
    worker_id = models.CharField(max_length=100)
    state = models.CharField(
        max_length=24, choices=WorkerResultState.choices,
        default=WorkerResultState.QUEUED,
    )
    attempt_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
    )
    dry_run = models.BooleanField(default=True)
    error_code = models.CharField(max_length=80, blank=True, default='')
    error_detail = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    external_post_id = models.CharField(max_length=200, blank=True, default='')
    audit_entries = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fb_publishing_worker_jobs'
        indexes = [
            models.Index(
                fields=['pipeline', 'state', '-created_at'],
                name='fbpubjob_state_idx',
            ),
        ]

    def clean(self):
        super().clean()
        if self.pipeline_id and self.job_id:
            if self.job.pipeline_id != self.pipeline_id:
                raise ValidationError({'job': 'Job không thuộc Pipeline.'})
        if self.account_id and self.pipeline_id:
            if self.account.pipeline_id != self.pipeline_id:
                raise ValidationError({'account': 'Account không thuộc Pipeline.'})
        if self.group_id and self.pipeline_id:
            if self.group.pipeline_id != self.pipeline_id:
                raise ValidationError({'group': 'Group không thuộc Pipeline.'})
        if self.proxy_id and self.pipeline_id:
            if self.proxy.pipeline_id != self.pipeline_id:
                raise ValidationError({'proxy': 'Proxy không thuộc Pipeline.'})
        if self.pk is None and not self.dry_run and not self._state.adding:
            pass

    def add_audit(self, event, detail=None, sensitive=False):
        entry = {
            'ts': timezone.now().isoformat(),
            'event': event,
        }
        if detail is not None and not sensitive:
            entry['detail'] = str(detail)[:2000]
        self.audit_entries.append(entry)
        self.save(update_fields=['audit_entries'])

    def clean_log_value(self, raw):
        """Strip sensitive values before logging."""
        if raw is None:
            return None
        s = str(raw)
        s = re.sub(r'(?i)(password|cookie|token|secret|key|credential)\s*[=:]\s*\S+',
                   r'\1=[REDACTED]', s)
        return s[:500]


class WorkerRunningOp(models.Model):
    """Advisory lock: one Account may have at most one in-flight Worker operation."""

    account = models.OneToOneField(
        'facebook_accounts.FacebookAccount', on_delete=models.CASCADE,
        related_name='fb_worker_running_op',
    )
    publish_job = models.ForeignKey(
        WorkerPublishJob, on_delete=models.CASCADE,
        related_name='running_op',
    )
    worker_id = models.CharField(max_length=100)
    started_at = models.DateTimeField()
    heartbeat_at = models.DateTimeField()
    browser_session_id = models.CharField(max_length=128, blank=True, default='')

    class Meta:
        db_table = 'fb_publishing_running_ops'

    def is_stale(self, now=None, lease_seconds=600):
        now = now or timezone.now()
        return (now - self.heartbeat_at).total_seconds() > lease_seconds
