"""Step 9.7.18: bounded read-only Pipeline isolation audit.

No Facebook/network I/O, no secret values, no writes. The audit checks linked
identities and R2 object metadata but does not certify a running deployment.
A bounded scan or a failed query must never be interpreted as security approval.
"""
from django.db.models import F, Q, Value, CharField
from django.db.models.functions import Cast, Concat
from django.utils import timezone

from modules.albums.models import AlbumImage
from modules.facebook_accounts.credentials import FacebookCookieSecret
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyAuthSecret, ProxyEndpoint
from modules.publishing.models import (
    PublishingJob, PipelineAlbumSource, MediaAllocationItem,
)
from modules.publishing.scheduler_models import AccountGroupEligibility, AccountProxyPin
from modules.publishing.manual_handoff_models import ManualPublishingHandoff
from modules.publishing.worker_models import WorkerLeaseEvent
from modules.publishing.alert_models import PublishingAlertIncident


class SecurityAuditError(ValueError):
    pass


def _rules(pipeline_id):
    """Return *violation-only* querysets; every root is strictly scoped.

    Use relational comparisons inside PostgreSQL, not client-supplied IDs or
    hand-built SQL, so cross-Pipeline references remain detectable even when a
    bulk update has bypassed model.full_clean().
    """
    return (
        ('JOB_ACCOUNT_FOREIGN', 'critical', 'publishing_job',
         PublishingJob.objects.filter(pipeline_id=pipeline_id)
         .exclude(facebook_account__pipeline_id=F('pipeline_id'))),
        ('JOB_GROUP_FOREIGN', 'critical', 'publishing_job',
         PublishingJob.objects.filter(pipeline_id=pipeline_id)
         .exclude(facebook_group__pipeline_id=F('pipeline_id'))),
        ('JOB_MEDIA_FOREIGN', 'critical', 'publishing_job',
         PublishingJob.objects.filter(pipeline_id=pipeline_id, media_allocation__isnull=False)
         .exclude(media_allocation__pipeline_id=F('pipeline_id'))),
        ('PROXY_ACCOUNT_FOREIGN', 'critical', 'proxy_endpoint',
         ProxyEndpoint.objects.filter(pipeline_id=pipeline_id, account__isnull=False)
         .exclude(account__pipeline_id=F('pipeline_id'))),
        ('PROXY_PIN_ACCOUNT_FOREIGN', 'critical', 'proxy_pin',
         AccountProxyPin.objects.filter(pipeline_id=pipeline_id)
         .exclude(account__pipeline_id=F('pipeline_id'))),
        ('PROXY_PIN_PROXY_FOREIGN', 'critical', 'proxy_pin',
         AccountProxyPin.objects.filter(pipeline_id=pipeline_id)
         .exclude(proxy__pipeline_id=F('pipeline_id'))),
        ('PROXY_PIN_ACCOUNT_MISMATCH', 'critical', 'proxy_pin',
         AccountProxyPin.objects.filter(pipeline_id=pipeline_id)
         .exclude(proxy__account_id=F('account_id'))),
        ('PROXY_PIN_EXIT_IP_MISMATCH', 'critical', 'proxy_pin',
         AccountProxyPin.objects.filter(pipeline_id=pipeline_id)
         .exclude(proxy__exit_ip=F('pinned_exit_ip'))),
        ('ELIGIBILITY_ACCOUNT_FOREIGN', 'critical', 'account_group_eligibility',
         AccountGroupEligibility.objects.filter(pipeline_id=pipeline_id)
         .exclude(account__pipeline_id=F('pipeline_id'))),
        ('ELIGIBILITY_GROUP_FOREIGN', 'critical', 'account_group_eligibility',
         AccountGroupEligibility.objects.filter(pipeline_id=pipeline_id)
         .exclude(group__pipeline_id=F('pipeline_id'))),
        ('ALBUM_SOURCE_FOREIGN', 'critical', 'pipeline_album_source',
         PipelineAlbumSource.objects.filter(pipeline_id=pipeline_id)
         .exclude(album__pipeline_id=F('pipeline_id'))),
        ('HANDOFF_JOB_FOREIGN', 'critical', 'manual_handoff',
         ManualPublishingHandoff.objects.filter(pipeline_id=pipeline_id)
         .exclude(job__pipeline_id=F('pipeline_id'))),
        ('HANDOFF_ACTOR_FOREIGN', 'critical', 'manual_handoff',
         ManualPublishingHandoff.objects.filter(pipeline_id=pipeline_id)
         .exclude(Q(actor_id=F('pipeline__ctv_id')) |
                  Q(actor__is_staff=True, actor__is_superuser=True))),
        ('WORKER_EVENT_JOB_FOREIGN', 'critical', 'worker_event',
         WorkerLeaseEvent.objects.filter(pipeline_id=pipeline_id)
         .exclude(job__pipeline_id=F('pipeline_id'))),
        ('ALERT_ACK_ACTOR_FOREIGN', 'critical', 'alert_incident',
         PublishingAlertIncident.objects.filter(pipeline_id=pipeline_id,
                                              acknowledged_by__isnull=False)
         .exclude(Q(acknowledged_by_id=F('pipeline__ctv_id')) |
                  Q(acknowledged_by__is_staff=True, acknowledged_by__is_superuser=True))),
        ('IMAGE_ALLOCATION_FOREIGN', 'critical', 'media_allocation_item',
         MediaAllocationItem.objects.filter(allocation__pipeline_id=pipeline_id,
                                            image__isnull=False)
         .exclude(image__album__pipeline_id=F('allocation__pipeline_id'))),
        ('IMAGE_ALLOCATION_IDENTITY_MISMATCH', 'critical', 'media_allocation_item',
         MediaAllocationItem.objects.filter(allocation__pipeline_id=pipeline_id,
                                            image__isnull=False)
         .filter(~Q(image_uuid=F('image_id')) | ~Q(album_uuid=F('image__album_id')))),
        ('COOKIE_CIPHERTEXT_EMPTY', 'critical', 'facebook_cookie_secret',
         FacebookCookieSecret.objects.filter(account__pipeline_id=pipeline_id)
         .filter(Q(ciphertext='') | Q(ciphertext__isnull=True))),
        ('PROXY_CIPHERTEXT_EMPTY', 'critical', 'proxy_auth_secret',
         ProxyAuthSecret.objects.filter(proxy__pipeline_id=pipeline_id)
         .filter(Q(ciphertext='') | Q(ciphertext__isnull=True))),
    )


def security_snapshot(*, pipeline_id, limit=100):
    """Read-only bounded audit; fail closed on partial coverage.

    Findings expose only code, severity, type and the *local* record UUID.
    No ciphertext, cookie, proxy host/IP, R2 key, caption or PII is serialized.
    """
    if type(limit) is not int or not 1 <= limit <= 250:
        raise SecurityAuditError('limit phải từ 1 đến 250.')
    if not Pipeline.objects.filter(pk=pipeline_id).exists():
        raise SecurityAuditError('Pipeline không tồn tại.')
    findings = []
    truncated = []
    scanned = {}
    for code, severity, kind, qs in _rules(pipeline_id):
        # Each rule queries *only violations*. An over-limit category is never
        # declared fully checked, even when all visible samples are benign.
        rows = list(qs.order_by('pk').values_list('pk', flat=True)[:limit + 1])
        if len(rows) > limit:
            truncated.append(code)
        rows = rows[:limit]
        scanned[code] = len(rows)
        for pk in rows:
            findings.append({
                'code': code, 'severity': severity, 'object_type': kind,
                'object_id': str(pk),
            })
    # Canonical R2 storage keys are compared INSIDE PostgreSQL so even large
    # Albums can be fully checked without downloading image data or returning
    # storage keys. Only violating object IDs are returned, bounded by `limit`.
    canonical = Concat(
        Value('pipeline-albums/'), Cast(F('album__pipeline_id'), CharField()),
        Value('/'), Cast(F('album_id'), CharField()), Value('/'),
        Cast(F('pk'), CharField()), Value('.webp'),
        output_field=CharField(),
    )
    images = (AlbumImage.objects.filter(
        album__pipeline_id=pipeline_id, upload_status=AlbumImage.UploadStatus.READY,
    ).annotate(_expected_security_key=canonical).filter(
        Q(storage_key__isnull=True) | ~Q(storage_key=F('_expected_security_key'))
    ))
    bad_image_ids = list(images.order_by('pk').values_list('pk', flat=True)[:limit + 1])
    if len(bad_image_ids) > limit:
        truncated.append('ALBUM_IMAGE_STORAGE_SCOPE')
    scanned['ALBUM_IMAGE_STORAGE_SCOPE'] = min(limit, len(bad_image_ids))
    for image_id in bad_image_ids[:limit]:
        findings.append({
            'code': 'ALBUM_IMAGE_STORAGE_SCOPE', 'severity': 'critical',
            'object_type': 'album_image', 'object_id': str(image_id),
        })
    complete = not truncated
    status = 'incomplete' if not complete else 'attention_required' if findings else 'consistent'
    return {
        'pipeline_id': str(pipeline_id), 'checked_at': timezone.now().isoformat(),
        'status': status, 'complete': complete, 'findings': findings,
        'summary': {'findings_in_sample': len(findings),
                    'critical_in_sample': sum(x['severity'] == 'critical' for x in findings)},
        'sampled_violations_by_category': scanned, 'truncated_categories': truncated,
        'limit_per_category': limit, 'read_only': True,
        'production_security_certified': False,
        'contains_credentials': False,
        'note': 'Chỉ kiểm tra quan hệ và metadata trong Neon; không thay thế penetration test, kiểm tra VPS hay kiểm tra phân quyền Facebook thực tế.',
    }
