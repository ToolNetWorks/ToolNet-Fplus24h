"""Operational alert inbox and an explicitly invoked, fail-closed scanner.

Scanning reads operational health and review SLA *before* any mutation. A failed
scan preserves existing alerts; it never resolves them falsely. No network I/O,
Facebook dispatch, retries, proxy changes, or notifications to outside parties.
"""
from datetime import timedelta

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.alert_models import (
    PublishingAlertIncident, PublishingAlertEvent, PublishingAlertScan,
)
from modules.publishing.services.operations_health import health_snapshot
from modules.publishing.services.review_sla import review_sla_snapshot


class AlertError(ValueError):
    pass


class AlertConflict(AlertError):
    pass


# No arbitrary external text is persisted. The catalog is deliberate and stable.
ALERT_CATALOG = {
    'DATABASE_UNAVAILABLE': ('critical', 'Không thể kết nối cơ sở dữ liệu'),
    'SCHEDULE_OVERDUE': ('warning', 'Có lịch đăng trễ trên 15 phút'),
    'SCHEDULER_TICK_ERRORS': ('critical', 'Scheduler Tick báo lỗi trong một giờ'),
    'UNRESOLVED_JOBS_OVER_48H': ('critical', 'Có Job chưa xác minh quá 48 giờ'),
    'EXPIRED_WORKER_LEASES': ('critical', 'Worker lease đã hết hạn'),
    'INTEGRITY_ATTENTION_REQUIRED': ('critical', 'Kiểm toán phát hiện dữ liệu bất thường'),
    'INTEGRITY_INCOMPLETE': ('warning', 'Kiểm toán dữ liệu chưa đầy đủ'),
    'REVIEW_SLA_OVERDUE': ('warning', 'Có hồ sơ đối soát quá hạn SLA'),
    'REVIEW_SLA_CRITICAL': ('critical', 'Có hồ sơ đối soát ở mức nghiêm trọng'),
}


def _alert_payload(row, *, now):
    snoozed = bool(row.snoozed_until and row.snoozed_until > now)
    return {
        'id': str(row.pk), 'code': row.code,
        'title': ALERT_CATALOG.get(row.code, ('warning', 'Cảnh báo hệ thống'))[1],
        'severity': row.severity, 'state': row.state, 'version': row.version,
        'first_seen_at': row.first_seen_at.isoformat(),
        'last_seen_at': row.last_seen_at.isoformat(),
        'resolved_at': row.resolved_at.isoformat() if row.resolved_at else None,
        'acknowledged_at': row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        'snoozed_until': row.snoozed_until.isoformat() if row.snoozed_until else None,
        'is_snoozed': snoozed, 'seen_count': row.seen_count,
        'requires_attention': row.state == 'open' and not row.acknowledged_at and not snoozed,
    }


def list_alerts(*, pipeline_id, state='open', page=1, page_size=20, now=None):
    if state not in ('open', 'resolved', 'all'):
        raise AlertError('Bộ lọc trạng thái không hợp lệ.')
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 50:
        raise AlertError('Phân trang không hợp lệ.')
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise AlertError('Thời gian cần có múi giờ.')
    if not Pipeline.objects.filter(pk=pipeline_id).exists():
        raise AlertError('Pipeline không tồn tại.')
    base = PublishingAlertIncident.objects.filter(pipeline_id=pipeline_id)
    stats = base.aggregate(
        open=Count('pk', filter=Q(state='open')),
        critical_open=Count('pk', filter=Q(state='open', severity='critical')),
        unacknowledged_open=Count('pk', filter=Q(state='open', acknowledged_at__isnull=True)),
        resolved=Count('pk', filter=Q(state='resolved')),
    )
    pending_attention = base.filter(state='open', acknowledged_at__isnull=True).filter(
        Q(snoozed_until__isnull=True) | Q(snoozed_until__lte=now)
    ).count()
    scan = PublishingAlertScan.objects.filter(pipeline_id=pipeline_id).first()
    qs = base if state == 'all' else base.filter(state=state)
    pages = Paginator(qs.order_by('-updated_at', 'pk'), page_size)
    result = pages.get_page(page)
    if result.number != page:
        raise AlertError('Trang không tồn tại.')
    return {
        'pipeline_id': str(pipeline_id),
        'summary': {**stats, 'requires_attention': pending_attention},
        'items': [_alert_payload(row, now=now) for row in result.object_list],
        'pagination': {
            'page': page, 'page_size': page_size, 'total': pages.count,
            'total_pages': pages.num_pages, 'has_next': result.has_next(),
            'has_previous': result.has_previous(),
        },
        'last_scan_at': scan.last_checked_at.isoformat() if scan else None,
        'scan_stale': scan is None or scan.last_checked_at < now - timedelta(minutes=10),
        'read_only_get': True,
        'notifications_internal_only': True,
        'posting_or_auto_resolution_enabled': False,
    }


def scan_alerts(*, pipeline_id, now=None):
    """Explicit CLI scan only; no URL route invokes this function.

    Lock order is Pipeline -> AlertIncident, matching other writer boundaries.
    A failure in health/SLA computation writes NOTHING, including resolution.
    """
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise AlertError('Thời gian cần có múi giờ.')
    health = health_snapshot(pipeline_id=pipeline_id, sample_limit=250, now=now)
    sla = review_sla_snapshot(pipeline_id=pipeline_id, page=1, page_size=1, now=now)
    codes = set(health['alerts'])
    if health['status'] not in ('healthy', 'attention'):
        raise AlertError('Health status không hợp lệ, không đối soát cảnh báo.')
    if any(code not in ALERT_CATALOG for code in codes):
        raise AlertError('Health trả mã cảnh báo chưa hỗ trợ, không tự giải quyết cảnh báo.')
    if sla['summary']['overdue'] > 0:
        codes.add('REVIEW_SLA_OVERDUE')
    if sla['summary']['critical'] > 0:
        codes.add('REVIEW_SLA_CRITICAL')
    with transaction.atomic():
        pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
        if pipeline is None:
            raise AlertError('Pipeline không tồn tại.')
        current = {
            row.code: row
            for row in PublishingAlertIncident.objects.select_for_update().filter(
                pipeline_id=pipeline.pk,
            ).order_by('pk')
        }
        created, reopened, resolved = 0, 0, 0
        for code in sorted(codes):
            severity, _title = ALERT_CATALOG[code]
            row = current.get(code)
            if row is None:
                row = PublishingAlertIncident.objects.create(
                    pipeline=pipeline, code=code, severity=severity,
                    first_seen_at=now, last_seen_at=now,
                )
                PublishingAlertEvent.objects.create(incident=row, kind='detected')
                created += 1
                continue
            is_reopen = row.state == 'resolved'
            row.severity = severity
            row.state = 'open'
            row.resolved_at = None
            row.last_seen_at = now
            row.seen_count += 1
            if is_reopen:
                row.first_seen_at = now
                row.acknowledged_at = None
                row.acknowledged_by = None
                row.snoozed_until = None
                reopened += 1
            row.version += 1 if is_reopen else 0
            row.save(update_fields=['severity', 'state', 'resolved_at', 'last_seen_at',
                                    'seen_count', 'first_seen_at', 'acknowledged_at',
                                    'acknowledged_by', 'snoozed_until', 'version', 'updated_at'])
            if is_reopen:
                PublishingAlertEvent.objects.create(incident=row, kind='reopened')
        for code, row in current.items():
            if code in codes or row.state != 'open':
                continue
            row.state = 'resolved'
            row.resolved_at = now
            row.version += 1
            row.save(update_fields=['state', 'resolved_at', 'version', 'updated_at'])
            PublishingAlertEvent.objects.create(incident=row, kind='resolved')
            resolved += 1
        PublishingAlertScan.objects.update_or_create(
            pipeline=pipeline,
            defaults={'last_checked_at': now, 'active_count': len(codes),
                      'critical_count': sum(ALERT_CATALOG[c][0] == 'critical' for c in codes)},
        )
    return {
        'pipeline_id': str(pipeline_id), 'scanned_at': now.isoformat(),
        'active_count': len(codes), 'created': created,
        'reopened': reopened, 'resolved': resolved,
        'report_only': True, 'external_delivery_enabled': False,
    }


@transaction.atomic
def take_alert_action(*, pipeline_id, alert_id, actor, action, expected_version,
                      snooze_minutes=None, now=None):
    if action not in ('acknowledge', 'snooze'):
        raise AlertError('Thao tác không hợp lệ.')
    if type(expected_version) is not int or expected_version < 1:
        raise AlertError('Phiên bản cảnh báo không hợp lệ.')
    if action == 'snooze' and (type(snooze_minutes) is not int
                               or not 15 <= snooze_minutes <= 1440):
        raise AlertError('Thời gian tạm ẩn phải từ 15 đến 1440 phút.')
    now = now or timezone.now()
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise AlertError('Pipeline không tồn tại.')
    if not (actor.is_active and ((actor.is_staff and actor.is_superuser)
                                 or pipeline.ctv_id == actor.pk)):
        raise AlertError('Tài khoản không có quyền trên Pipeline.')
    row = PublishingAlertIncident.objects.select_for_update().filter(
        pk=alert_id, pipeline_id=pipeline.pk,
    ).first()
    if row is None:
        raise AlertError('Không tìm thấy cảnh báo trong Pipeline.')
    if row.version != expected_version:
        raise AlertConflict('Cảnh báo đã thay đổi, vui lòng tải lại.')
    if row.state != 'open':
        raise AlertConflict('Cảnh báo đã hết hiệu lực.')
    if action == 'acknowledge':
        if row.acknowledged_at:
            raise AlertConflict('Cảnh báo đã được xác nhận trước đó.')
        row.acknowledged_at = now
        row.acknowledged_by = actor
        kind = 'acknowledged'
        fields = ['acknowledged_at', 'acknowledged_by']
    else:
        row.snoozed_until = now + timedelta(minutes=snooze_minutes)
        kind = 'snoozed'
        fields = ['snoozed_until']
    row.version += 1
    row.save(update_fields=fields + ['version', 'updated_at'])
    PublishingAlertEvent.objects.create(incident=row, kind=kind, actor=actor)
    return _alert_payload(row, now=now)


def alert_event_history(*, pipeline_id, alert_id, page=1, page_size=20):
    """Read-only, bounded event history; no raw health payloads or secrets."""
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 50:
        raise AlertError('Phân trang lịch sử không hợp lệ.')
    row = PublishingAlertIncident.objects.filter(pk=alert_id, pipeline_id=pipeline_id).first()
    if row is None:
        raise AlertError('Không tìm thấy cảnh báo trong Pipeline.')
    pages = Paginator(row.events.order_by('-recorded_at', '-pk'), page_size)
    result = pages.get_page(page)
    if result.number != page:
        raise AlertError('Trang lịch sử không tồn tại.')
    return {
        'pipeline_id': str(pipeline_id), 'alert_id': str(row.pk),
        'events': [{
            'id': str(event.pk), 'kind': event.kind,
            'recorded_at': event.recorded_at.isoformat(),
        } for event in result.object_list],
        'pagination': {
            'page': page, 'page_size': page_size, 'total': pages.count,
            'total_pages': pages.num_pages, 'has_next': result.has_next(),
        },
        'read_only': True,
    }
