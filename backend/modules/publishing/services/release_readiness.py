"""Step 9.7.20: conservative, read-only release acceptance evidence.

One Pipeline per assessment. No Meta API, browser, R2 network, credential access,
Job mutation or auto-approval. External operational sign-off is always required;
internal database checks cannot certify Facebook publication or VPS health.
"""
from time import monotonic
from django.utils import timezone
from modules.pipelines.models import Pipeline
from modules.publishing.services.operations_health import health_snapshot
from modules.publishing.services.security_audit import security_snapshot
from modules.publishing.services.pilot_readiness import pilot_readiness_snapshot
from modules.publishing.services.worker_reliability import worker_guard_snapshot
from modules.publishing.services.performance_stability import performance_snapshot


class ReleaseReadinessError(ValueError):
    pass


# Catalog is immutable server-side. No arbitrary client-supplied flags or text.
EXTERNAL_CHECKS = (
    ('VPS_SERVICES_AND_HTTP', 'Kiểm tra systemd, HTTP/HTTPS và login CTV/Admin trực tiếp trên VPS'),
    ('BACKUP_AND_RESTORE', 'Kiểm tra bản sao lưu và phục hồi thử trên môi trường riêng'),
    ('REAL_GROUP_PILOT', 'CTV thử đăng một bài hợp lệ trên Facebook và lưu bằng chứng đối soát độc lập'),
    ('OPERATOR_APPROVAL', 'Người phụ trách ký duyệt phát hành sau khi xem bằng chứng'),
)


def _check(code, status, description):
    return {'code': code, 'status': status, 'description': description}


def _run_probe(label, fn):
    """Convert failures to a stable code, not database error strings or credentials."""
    try:
        return fn(), None
    except Exception:
        return None, 'CHECK_FAILED_' + label


def release_snapshot(*, pipeline_id, limit=50, include_performance=True, now=None):
    """Conservative acceptance assessment, never returns release_approved=True.

    'blocked' means a known finding, incomplete scan, or failed inspection.
    'pending_operator_signoff' means internal checks alone passed but external
    acceptance is still required. Neither outcome automatically deploys code.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ReleaseReadinessError('limit phải từ 1 đến 100.')
    if type(include_performance) is not bool:
        raise ReleaseReadinessError('include_performance phải là boolean.')
    now = timezone.now() if now is None else now
    if timezone.is_naive(now):
        raise ReleaseReadinessError('now phải có múi giờ.')
    pipeline = Pipeline.objects.filter(pk=pipeline_id).values('id', 'status').first()
    if pipeline is None:
        raise ReleaseReadinessError('Pipeline không tồn tại.')
    t0 = monotonic()
    checks = []
    errors = []
    checks.append(_check('PIPELINE_ACTIVE',
                         'pass' if pipeline['status'] == Pipeline.Status.ACTIVE else 'blocked',
                         'Pipeline đang hoạt động' if pipeline['status'] == Pipeline.Status.ACTIVE
                         else 'Pipeline đang khóa hoặc không hoạt động'))

    ops, err = _run_probe('OPERATIONS', lambda: health_snapshot(
        pipeline_id=pipeline_id, sample_limit=limit, now=now,
    ))
    if err:
        errors.append(err)
    checks.append(_check('OPERATIONS_HEALTH',
                         'pass' if ops and ops.get('status') == 'healthy'
                         and ops.get('database', {}).get('connected') is True else 'blocked',
                         'Không có cảnh báo vận hành trong dữ liệu Neon' if ops and ops.get('status') == 'healthy'
                         else 'Operations Health lỗi hoặc có cảnh báo'))
    checks.append(_check('INTEGRITY_COMPLETE',
                         'pass' if ops and ops.get('integrity', {}).get('complete') is True
                         and ops.get('integrity', {}).get('status') == 'consistent' else 'blocked',
                         'Kiểm toán tính nhất quán hoàn tất và không có lỗi' if ops and ops.get('integrity', {}).get('complete') is True
                         and ops.get('integrity', {}).get('status') == 'consistent'
                         else 'Kiểm toán dữ liệu có lỗi hoặc chưa quét đầy đủ'))

    security, err = _run_probe('SECURITY', lambda: security_snapshot(
        pipeline_id=pipeline_id, limit=limit,
    ))
    if err:
        errors.append(err)
    checks.append(_check('TENANT_SECURITY',
                         'pass' if security and security.get('complete') is True
                         and security.get('status') == 'consistent' else 'blocked',
                         'Không phát hiện lỗi cách ly Pipeline trong kiểm toán' if security and security.get('complete') is True
                         and security.get('status') == 'consistent'
                         else 'Kiểm toán bảo mật có lỗi hoặc chưa đầy đủ'))

    worker, err = _run_probe('WORKER', lambda: worker_guard_snapshot(
        pipeline_id=pipeline_id, limit=limit, now=now,
    ))
    if err:
        errors.append(err)
    worker_clean = bool(worker and not worker.get('truncated')
                        and worker.get('summary', {}).get('expired_or_missing_lease') == 0)
    checks.append(_check('WORKER_LEASES', 'pass' if worker_clean else 'blocked',
                         'Không có Worker lease hết hạn hoặc thiếu' if worker_clean
                         else 'Có Worker lease bất thường hoặc kiểm tra chưa đầy đủ'))

    pilot, err = _run_probe('PILOT', lambda: pilot_readiness_snapshot(
        pipeline_id=pipeline_id, limit=limit, now=now,
    ))
    if err:
        errors.append(err)
    pilot_complete = bool(pilot and pilot.get('truncated') is False)
    checks.append(_check('PILOT_SCAN_COMPLETE', 'pass' if pilot_complete else 'blocked',
                         'Dữ liệu Pilot được quét đầy đủ' if pilot_complete
                         else 'Chưa có hoặc chưa quét đầy đủ dữ liệu Pilot'))
    verified = pilot.get('summary', {}).get('verified', 0) if pilot else 0
    review = pilot.get('summary', {}).get('awaiting_review', 0) if pilot else 0
    blocked_jobs = pilot.get('summary', {}).get('blocked', 0) if pilot else 0
    pilot_verified = bool(pilot_complete and verified >= 1 and review == 0 and blocked_jobs == 0)
    checks.append(_check('INDEPENDENT_POST_EVIDENCE', 'pass' if pilot_verified else 'blocked',
                         'Có bản ghi đăng đã đối soát độc lập, không còn Job bất thường' if pilot_verified
                         else 'Chưa có bằng chứng đã xác minh độc lập hoặc còn Job cần xem xét'))

    performance = None
    if include_performance:
        performance, err = _run_probe('PERFORMANCE', lambda: performance_snapshot(
            pipeline_id=pipeline_id, repeats=1, limit=min(limit, 25), now=now,
        ))
        if err:
            errors.append(err)
    perf_ok = bool(performance and performance.get('status') == 'pass'
                   and performance.get('load_test_performed') is False)
    checks.append(_check('PERFORMANCE_BASELINE',
                         'pass' if perf_ok else 'blocked' if include_performance else 'not_checked',
                         'Kiểm tra hiệu năng tuần tự trong ngưỡng tham khảo' if perf_ok
                         else 'Chưa đo được hoặc baseline chưa đạt; không chứng minh khả năng tải đồng thời'))

    checks.extend(_check(code, 'manual_required', description) for code, description in EXTERNAL_CHECKS)
    blocking_count = sum(c['status'] in ('blocked', 'not_checked') for c in checks)
    state = 'blocked' if blocking_count or errors else 'pending_operator_signoff'
    return {
        'pipeline_id': str(pipeline_id),
        'checked_at': now.isoformat(),
        'status': state,
        'release_approved': False,
        'automatic_facebook_posting_enabled': False,
        'external_signoff_recorded': False,
        'read_only': True,
        'checks': checks,
        'summary': {
            'total': len(checks), 'passed': sum(c['status'] == 'pass' for c in checks),
            'blocked': blocking_count,
            'manual_required': len(EXTERNAL_CHECKS), 'probe_errors': len(errors),
            'verified_pilot_records': verified if pilot_complete else 0,
        },
        'errors': errors,
        'duration_ms': round((monotonic() - t0) * 1000, 1),
        'notes': [
            'Không được coi trạng thái healthy hoặc reported_pending là bài đã đăng công khai.',
            'Kiểm tra ứng dụng và Neon không xác nhận trạng thái systemd, HTTPS, backup hoặc khả năng đăng Facebook.',
            'Không tự deploy, gửi request Facebook, xác nhận published, giải phóng ảnh hoặc thay đổi Pipeline.',
        ],
    }
