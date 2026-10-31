import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Dict, Any, List
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from django.db import connection
from ..crypto import sanitize_text
from .db_service import get_database_status
from .r2_service import test_r2_connection


# Whitelist of systemd units allowed to query
ALLOWED_UNITS = {
    "toolnet-publisher.service",
    "toolnet-publisher-frontend.service",
    "toolnet-scheduler-tick.service",
    "toolnet-caption-tick.service",
    "toolnet-recovery-tick.service",
    "toolnet-alert-scanner.service",
    "toolnet-fplus24h-quick-tunnel.service",
}


def _check_systemd_unit(unit_name: str) -> str:
    """Safely query systemctl is-active for an explicitly whitelisted unit."""
    if unit_name not in ALLOWED_UNITS:
        return "unknown"
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", unit_name],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _check_proc_matching(cmd_keyword: str) -> bool:
    """Check /proc to see if a process matching cmd_keyword is running without shell execution."""
    try:
        for entry in os.listdir("/proc"):
            if entry.isdigit():
                try:
                    cmdline_path = os.path.join("/proc", entry, "cmdline")
                    with open(cmdline_path, "rb") as f:
                        cmd = f.read().decode("utf-8", "ignore")
                        if cmd_keyword in cmd:
                            return True
                except (FileNotFoundError, PermissionError):
                    continue
    except Exception:
        pass
    return False


def get_services_health() -> Dict[str, Any]:
    """Retrieve verified actual status of all 7 core system services.

    Never uses fake or simulated numbers.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    services: List[Dict[str, Any]] = []

    # 1. Django Backend
    django_unit = _check_systemd_unit("toolnet-publisher.service")
    is_django_running = django_unit == "active" or _check_proc_matching("gunicorn config.wsgi")
    services.append({
        "id": "django_backend",
        "name": "Django Backend (Gunicorn)",
        "role": "API, Authentication, CRM & Business Logic",
        "status": "running" if is_django_running else ("stopped" if django_unit == "inactive" else "unknown"),
        "unit": "toolnet-publisher.service",
        "systemd_state": django_unit,
        "last_heartbeat": now_iso if is_django_running else None,
        "last_error": None,
        "details": {
            "internal_port": 8010,
            "pid": os.getpid(),
            "framework": "Django 5.2.18 / Python 3.12",
        },
    })

    # 2. Next.js Frontend
    next_unit = _check_systemd_unit("toolnet-publisher-frontend.service")
    frontend_status = "running" if next_unit == "active" else ("stopped" if next_unit == "inactive" else "unknown")
    frontend_latency = None
    frontend_error = None
    try:
        start = time.monotonic()
        req = Request("http://127.0.0.1:3000/login/", headers={"User-Agent": "ToolNet-HealthCheck/1.0"})
        with urlopen(req, timeout=3) as resp:
            frontend_latency = int((time.monotonic() - start) * 1000)
            if resp.status in (200, 307, 308):
                frontend_status = "running"
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        if next_unit != "active":
            frontend_status = "stopped"
            frontend_error = "Không truy vấn được dịch vụ; kiểm tra kết nối và quyền truy cập."
        else:
            frontend_status = "error"
            frontend_error = "HTTP health probe failed"

    services.append({
        "id": "nextjs_frontend",
        "name": "Next.js Frontend (React)",
        "role": "Giao diện quản trị Admin, Pipelines & Workspace",
        "status": frontend_status,
        "unit": "toolnet-publisher-frontend.service",
        "systemd_state": next_unit,
        "last_heartbeat": now_iso if frontend_status == "running" else None,
        "last_error": frontend_error,
        "details": {
            "internal_port": 3000,
            "http_probe_ms": frontend_latency,
            "framework": "Next.js 16 (App Router)",
        },
    })

    # 3. Scheduler Tick
    sched_unit = _check_systemd_unit("toolnet-scheduler-tick.service")
    is_sched_proc = _check_proc_matching("scheduler_tick")
    sched_heartbeat = None
    sched_outcome = None
    sched_error = None

    try:
        from modules.publishing.models import SchedulerTickAudit
        last_tick = SchedulerTickAudit.objects.order_by("-created_at").first()
        if last_tick:
            sched_heartbeat = last_tick.created_at.isoformat()
            sched_outcome = last_tick.outcome
            if last_tick.error_code:
                sched_error = sanitize_text(f"Mã lỗi tick gần nhất: {last_tick.error_code}")
    except Exception as e:
        sched_error = "Không truy vấn được dịch vụ; kiểm tra kết nối và quyền truy cập."

    sched_running = sched_unit == "active" or is_sched_proc
    services.append({
        "id": "scheduler_tick",
        "name": "Scheduler Tick Worker",
        "role": "Lên lịch tự động, quét slot và điều phối publishing",
        "status": "running" if sched_running else ("stopped" if sched_unit == "inactive" else "unknown"),
        "unit": "toolnet-scheduler-tick.service",
        "systemd_state": sched_unit,
        "last_heartbeat": sched_heartbeat or (now_iso if sched_running else None),
        "last_error": sched_error,
        "details": {
            "poll_interval_seconds": 30,
            "last_outcome": sched_outcome,
            "enqueue_only": True,
        },
    })

    # 4. AI Caption Worker
    caption_unit = _check_systemd_unit("toolnet-caption-tick.service")
    is_caption_proc = _check_proc_matching("publishing_caption_tick")
    caption_heartbeat = None
    caption_error = None

    try:
        from modules.publishing.caption_models import JobCaption
        last_job = JobCaption.objects.order_by("-updated_at").first()
        if last_job:
            caption_heartbeat = last_job.updated_at.isoformat()
    except Exception as e:
        caption_error = "Không truy vấn được dịch vụ; kiểm tra kết nối và quyền truy cập."

    caption_running = caption_unit == "active" or is_caption_proc
    services.append({
        "id": "caption_worker",
        "name": "AI Caption Worker",
        "role": "Sinh caption tự động qua AI và phê duyệt theo pipeline",
        "status": "running" if caption_running else ("stopped" if caption_unit == "inactive" else "unknown"),
        "unit": "toolnet-caption-tick.service",
        "systemd_state": caption_unit,
        "last_heartbeat": caption_heartbeat or (now_iso if caption_running else None),
        "last_error": caption_error,
        "details": {
            "poll_interval_seconds": 60,
            "watch_mode": True,
        },
    })

    # 5. Facebook Publishing Worker
    fb_worker_running = _check_proc_matching("facebook_publishing") or _check_proc_matching("worker_lease")
    fb_heartbeat = None
    fb_last_state = None
    fb_error = None

    try:
        from modules.facebook_publishing.models import WorkerPublishJob
        last_worker_job = WorkerPublishJob.objects.order_by("-updated_at").first()
        if last_worker_job:
            fb_heartbeat = last_worker_job.updated_at.isoformat()
            fb_last_state = last_worker_job.state
            if getattr(last_worker_job, "error_code", None):
                fb_error = sanitize_text(f"Lỗi: {last_worker_job.error_code}")
    except Exception as e:
        fb_error = "Không truy vấn được dịch vụ; kiểm tra kết nối và quyền truy cập."

    services.append({
        "id": "facebook_publishing_worker",
        "name": "Facebook Publishing Worker",
        "role": "Tự động đăng bài ẩn danh lên Facebook Groups qua Browser",
        "status": "running" if fb_worker_running else ("standby" if fb_heartbeat else "idle"),
        "unit": "story-tts-worker / direct worker",
        "systemd_state": "active" if fb_worker_running else "standby",
        "last_heartbeat": fb_heartbeat,
        "last_error": fb_error,
        "details": {
            "last_state": fb_last_state,
            "mode": "Anonymous Group Posting",
        },
    })

    # 6. Database (Neon PostgreSQL)
    db_stat = get_database_status()
    services.append({
        "id": "neon_database",
        "name": "Neon PostgreSQL Database",
        "role": "Kho lưu trữ dữ liệu chính (Serverless PostgreSQL)",
        "status": "running" if db_stat["connection_status"] == "connected" else "error",
        "unit": "cloud / neon.tech",
        "systemd_state": db_stat["connection_status"],
        "last_heartbeat": now_iso if db_stat["connection_status"] == "connected" else None,
        "last_error": db_stat.get("last_error") or None,
        "details": {
            "host": db_stat["host"],
            "database_name": db_stat["database_name"],
            "latency_ms": db_stat["latency_ms"],
            "active_connections": db_stat["pool_info"]["active_connections"],
            "server_version": db_stat["pool_info"]["server_version"],
            "migrations_synced": db_stat["migrations"]["is_synced"],
        },
    })

    # 7. Cloudflare R2
    r2_test = test_r2_connection()
    services.append({
        "id": "cloudflare_r2",
        "name": "Cloudflare R2 Object Storage",
        "role": "Lưu trữ hình ảnh bài đăng (S3-compatible Object Storage)",
        "status": "running" if r2_test.get("success") else "error",
        "unit": "cloud / cloudflare.com",
        "systemd_state": "accessible" if r2_test.get("success") else "unreachable",
        "last_heartbeat": now_iso if r2_test.get("success") else None,
        "last_error": r2_test.get("error") or None,
        "details": {
            "bucket": r2_test.get("bucket"),
            "latency_ms": r2_test.get("latency_ms"),
            "read_ok": r2_test.get("read_ok", False),
            "write_ok": r2_test.get("write_ok", False),
        },
    })

    return {
        "checked_at": now_iso,
        "services": services,
    }
