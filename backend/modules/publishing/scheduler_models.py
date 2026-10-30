"""Pipeline-local, opt-in scheduling configuration and auditable assignment ledger.

Imported by modules.publishing.models; no import of that module here.
"""
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q


class PipelineSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT,
                                 related_name='publication_schedules')
    name = models.CharField(max_length=150)
    enabled = models.BooleanField(default=False)
    interval_minutes = models.PositiveIntegerField(default=1440,
                         validators=[MinValueValidator(60), MaxValueValidator(10080)])
    max_groups_per_run = models.PositiveSmallIntegerField(default=10,
                         validators=[MinValueValidator(1), MaxValueValidator(50)])
    timezone_name = models.CharField(max_length=64, default='Asia/Ho_Chi_Minh')
    start_at = models.DateTimeField()
    next_run_at = models.DateTimeField()
    caption_template = models.TextField(max_length=5000, blank=True, default='')
    require_anonymous = models.BooleanField(default=True)
    require_nonmember = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_pipeline_schedules'
        constraints = [
            models.UniqueConstraint(fields=['pipeline', 'name'], name='pubsch_pipeline_name_unique'),
            models.CheckConstraint(condition=Q(interval_minutes__gte=60) & Q(interval_minutes__lte=10080), name='pubsch_interval_range'),
            models.CheckConstraint(condition=Q(max_groups_per_run__gte=1) & Q(max_groups_per_run__lte=50), name='pubsch_group_limit'),
        ]
        indexes = [models.Index(fields=['enabled', 'next_run_at'], name='pubsch_due_idx')]

    def clean(self):
        super().clean()
        self.name = (self.name or '').strip()
        if not self.name:
            raise ValidationError({'name': 'Tên lịch đăng không được trống.'})
        
        # If pipeline has AI Caption enabled with auto_approve, make caption_template optional
        if not self.caption_template.strip() and not self._has_ai_caption_enabled():
            raise ValidationError({'caption_template': 'Cần caption/mẫu caption đã duyệt.'})
        
        if not isinstance(self.caption_template, str) or not self.caption_template.strip():
            raise ValidationError({'caption_template': 'Cần caption/mẫu caption có nội dung.'})
        
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValidationError({'timezone_name': 'Timezone không hợp lệ.'})
        from django.utils import timezone
        if not self.start_at or timezone.is_naive(self.start_at):
            raise ValidationError({'start_at': 'Cần datetime có múi giờ.'})
        if not self.next_run_at or timezone.is_naive(self.next_run_at):
            raise ValidationError({'next_run_at': 'Cần datetime có múi giờ.'})

    def _has_ai_caption_enabled(self) -> bool:
        """Check if pipeline has AI Caption enabled with auto_approve."""
        return (
            getattr(self.pipeline, 'caption_settings', None) is not None and
            getattr(self.pipeline.caption_settings, 'auto_generate', False) and
            getattr(self.pipeline.caption_settings, 'auto_approve', False)
        )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AccountGroupEligibility(models.Model):
    """Manually documented and expiring Account-specific posting eligibility.

    A Group-wide verification flag cannot substitute for account-specific rights.
    """
    class State(models.TextChoices):
        UNKNOWN = 'unknown', 'Chưa xác minh'
        VERIFIED = 'verified', 'Đã kiểm tra thủ công'
        BLOCKED = 'blocked', 'Không đủ điều kiện'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    account = models.ForeignKey('facebook_accounts.FacebookAccount', on_delete=models.PROTECT)
    group = models.ForeignKey('facebook_groups.FacebookGroup', on_delete=models.PROTECT)
    state = models.CharField(max_length=12, choices=State.choices, default=State.UNKNOWN)
    can_post_anonymous = models.BooleanField(default=False)
    can_post_nonmember = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    evidence_note = models.CharField(max_length=500, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_account_group_eligibility'
        constraints = [models.UniqueConstraint(fields=['pipeline', 'account', 'group'],
                                               name='pubelig_pair_unique')]
        indexes = [models.Index(fields=['pipeline', 'state', 'expires_at'],
                                name='pubelig_valid_idx')]

    def clean(self):
        super().clean()
        if self.account_id and self.pipeline_id and not self.account.__class__.objects.filter(
                pk=self.account_id, pipeline_id=self.pipeline_id).exists():
            raise ValidationError({'account': 'Account thuộc Pipeline khác.'})
        if self.group_id and self.pipeline_id and not self.group.__class__.objects.filter(
                pk=self.group_id, pipeline_id=self.pipeline_id).exists():
            raise ValidationError({'group': 'Group thuộc Pipeline khác.'})
        if self.state == self.State.VERIFIED:
            if not self.verified_at or not self.expires_at or self.expires_at <= self.verified_at:
                raise ValidationError({'expires_at': 'Xác minh cần thời hạn hiệu lực.'})
            if not self.evidence_note.strip():
                raise ValidationError({'evidence_note': 'Ghi nguồn xác minh thủ công.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class GroupHealth(models.Model):
    class State(models.TextChoices):
        ACTIVE = 'active', 'Có thể xem xét đăng'
        PAUSED = 'paused', 'Tạm dừng thủ công'
        UNAVAILABLE = 'unavailable', 'Không khả dụng đã xác minh'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    group = models.OneToOneField('facebook_groups.FacebookGroup', on_delete=models.PROTECT,
                                 related_name='scheduling_health')
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    reason_code = models.CharField(max_length=80, blank=True, default='')
    evidence_note = models.CharField(max_length=500, blank=True, default='')
    review_after = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'publisher_group_scheduling_health'

    def clean(self):
        super().clean()
        if self.group_id and self.pipeline_id and not self.group.__class__.objects.filter(
                pk=self.group_id, pipeline_id=self.pipeline_id).exists():
            raise ValidationError({'group': 'Group thuộc Pipeline khác.'})
        if self.state == self.State.UNAVAILABLE and not self.evidence_note.strip():
            raise ValidationError({'evidence_note': 'Cần bằng chứng Group không khả dụng.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AccountProxyPin(models.Model):
    """Permanent scheduler pin. Never silently replace a changed proxy/IP."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    account = models.OneToOneField('facebook_accounts.FacebookAccount', on_delete=models.PROTECT)
    proxy = models.OneToOneField('proxies.ProxyEndpoint', on_delete=models.PROTECT)
    pinned_exit_ip = models.GenericIPAddressField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_account_proxy_pins'

    def clean(self):
        super().clean()
        if self.account_id and self.pipeline_id and self.account.pipeline_id != self.pipeline_id:
            raise ValidationError({'account': 'Account thuộc Pipeline khác.'})
        if self.proxy_id and self.pipeline_id:
            if self.proxy.pipeline_id != self.pipeline_id or self.proxy.account_id != self.account_id:
                raise ValidationError({'proxy': 'Proxy không được gắn với Account này.'})
        if self.pk and self.__class__.objects.filter(pk=self.pk).exists():
            old = self.__class__.objects.get(pk=self.pk)
            if (old.pipeline_id, old.account_id, old.proxy_id, old.pinned_exit_ip) != (
                    self.pipeline_id, self.account_id, self.proxy_id, self.pinned_exit_ip):
                raise ValidationError('Không thể tự thay đổi Proxy Pin. Cần quy trình quản trị riêng.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ScheduledBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pipeline = models.ForeignKey('pipelines.Pipeline', on_delete=models.PROTECT)
    schedule = models.ForeignKey(PipelineSchedule, on_delete=models.PROTECT, related_name='batches')
    slot_at = models.DateTimeField()
    assigned_count = models.PositiveSmallIntegerField(default=0)
    skipped = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'publisher_scheduled_batches'
        constraints = [models.UniqueConstraint(fields=['schedule', 'slot_at'],
                                               name='pubsch_batch_slot_unique')]
        indexes = [models.Index(fields=['pipeline', 'slot_at'], name='pubsch_batch_time_idx')]


class ScheduledAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(ScheduledBatch, on_delete=models.PROTECT, related_name='assignments')
    job = models.OneToOneField('publishing.PublishingJob', on_delete=models.PROTECT,
                               related_name='scheduled_assignment')
    account = models.ForeignKey('facebook_accounts.FacebookAccount', on_delete=models.PROTECT)
    group = models.ForeignKey('facebook_groups.FacebookGroup', on_delete=models.PROTECT)
    proxy = models.ForeignKey('proxies.ProxyEndpoint', on_delete=models.PROTECT)
    exit_ip_snapshot = models.GenericIPAddressField()
    scheduled_at = models.DateTimeField()

    class Meta:
        db_table = 'publisher_scheduled_assignments'
        constraints = [models.UniqueConstraint(fields=['batch', 'group'],
                                               name='pubsch_group_once_per_batch')]
