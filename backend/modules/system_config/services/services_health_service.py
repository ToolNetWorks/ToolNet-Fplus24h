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
    
    Returns simplified health status with color coding, no sensitive information.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    services: List[Dict[str, Any]] = []

    # 1. Django Backend
    django_unit = _check_systemd_unit("toolnet-publisher.service")
    is_django_running = django_unit == "active" or _check_proc_matching("gunicorn config.wsgi")
    
    # Determine status with color mapping
    if is_django_running:
        status = "running"
        color = "healthy"
    elif django_unit == "inactive":
        status = "stopped"
        color = "error"
    else:
        status = "unknown"
        color = "unknown"
    
    services.append({
        "id": "django_backend",
        "name": "Django Backend (Gunicorn)",
        "status": status,
        "color": color,
        "role": "API, Authentication, CRM & Business Logic",
        "systemd_state": django_unit,
        "last_heartbeat": now_iso if is_django_running else None,
        "last_error": None,
        "checked_at": now_iso,
    })

    # 2. Next.js Frontend
    next_unit = _check_systemd_unit("toolnet-publisher-frontend.service")
    frontend_status = "running" if next_unit == "active" else ("stopped" if next_unit == "inactive" else "unknown")
    frontend_color = "healthy" if frontend_status == "running" else ("error" if frontend_status == "stopped" else "unknown")
    frontend_latency = None
    frontend_error = None
    
    try:
        start = time.monotonic()
        req = Request("http://127.0.0.1:3000/login/", headers={"User-Agent": "ToolNet-HealthCheck/1.0"})
        with urlopen(req, timeout=3) as resp:
            frontend_latency = int((time.monotonic() - start) * 1000)
            if resp.status in (200, 307, 308):
                frontend_status = "running"
                frontend_color = "healthy"
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        if next_unit != "active":
            frontend_status = "stopped"
            frontend_color = "error"
            frontend_error = "Không truy vấn được dịch vụ"
        else:
            frontend_status = "error"
            frontend_color = "error"
            frontend_error = "HTTP health probe failed"

    services.append({
        "id": "nextjs_frontend",
        "name": "Next.js Frontend",
        "status": frontend_status,
        "color": frontend_color,
        "role": "Giao diện quản trị Admin, Pipelines & Workspace",
        "systemd_state": next_unit,
        "last_heartbeat": now_iso if frontend_status == "running" else None,
        "last_error": frontend_error,
        "latency_ms": frontend_latency,
        "checked_at": now_iso,
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
        sched_error = "Không truy vấn được dịch vụ"

    sched_running = sched_unit == "active" or is_sched_proc
    if sched_running:
        sched_status = "running"
        sched_color = "healthy"
    elif sched_unit == "inactive":
        sched_status = "stopped"
        sched_color = "error"
    else:
        sched_status = "standby"
        sched_color = "degraded"

    services.append({
        "id": "scheduler_tick",
        "name": "Scheduler Tick Worker",
        "status": sched_status,
        "color": sched_color,
        "role": "Lên lịch tự động, quét slot và điều phối publishing",
        "systemd_state": sched_unit,
        "last_heartbeat": sched_heartbeat or (now_iso if sched_running else None),
        "last_error": sched_error,
        "outcome": sched_outcome,
        "checked_at": now_iso,
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
        caption_error = "Không truy vấn được dịch vụ"

    caption_running = caption_unit == "active" or is_caption_proc
    if caption_running:
        caption_status = "running"
        caption_color = "healthy"
    elif caption_unit == "inactive":
        caption_status = "stopped"
        caption_color = "error"
    else:
        caption_status = "standby"
        caption_color = "degraded"

    services.append({
        "id": "caption_worker",
        "name": "AI Caption Worker",
        "status": caption_status,
        "color": caption_color,
        "role": "Sinh caption tự động qua AI và phê duyệt theo pipeline",
        "systemd_state": caption_unit,
        "last_heartbeat": caption_heartbeat or (now_iso if caption_running else None),
        "last_error": caption_error,
        "checked_at": now_iso,
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
        fb_error = "Không truy vấn được dịch vụ"

    if fb_worker_running:
        fb_status = "running"
        fb_color = "healthy"
    elif fb_heartbeat:
        fb_status = "standby"
        fb_color = "degraded"
    else:
        fb_status = "idle"
        fb_color = "unknown"

    services.append({
        "id": "facebook_publishing_worker",
        "name": "Facebook Publishing Worker",
        "status": fb_status,
        "color": fb_color,
        "role": "Tự động đăng bài ẩn danh lên Facebook Groups qua Browser",
        "systemd_state": "active" if fb_worker_running else "standby",
        "last_heartbeat": fb_heartbeat,
        "last_error": fb_error,
        "last_state": fb_last_state,
        "checked_at": now_iso,
    })

    # 6. Database (Neon PostgreSQL)
    db_stat = get_database_status()
    
    if db_stat["connection_status"] == "connected":
        db_status = "running"
        db_color = "healthy"
    else:
        db_status = "error"
        db_color = "error"

    services.append({
        "id": "neon_database",
        "name": "Neon PostgreSQL Database",
        "status": db_status,
        "color": db_color,
        "role": "Kho lưu trữ dữ liệu chính",
        "systemd_state": db_stat["connection_status"],
        "last_heartbeat": now_iso if db_status == "running" else None,
        "last_error": db_stat.get("last_error") or None,
        "latency_ms": db_stat.get("latency_ms"),
        "database_size": db_stat.get("database_size"),
        "migrations_pending": db_stat.get("migrations_pending", 0),
        "checked_at": now_iso,
    })

    # 7. Cloudflare R2
    r2_test = test_r2_connection()
    
    if r2_test.get("success"):
        r2_status = "running"
        r2_color = "healthy"
    else:
        r2_status = "error"
        r2_color = "error"

    services.append({
        "id": "cloudflare_r2",
        "name": "Cloudflare R2 Object Storage",
        "status": r2_status,
        "color": r2_color,
        "role": "Lưu trữ hình ảnh bài đăng",
        "systemd_state": "accessible" if r2_test.get("success") else "unreachable",
        "last_heartbeat": now_iso if r2_status == "running" else None,
        "last_error": r2_test.get("error") or None,
        "latency_ms": r2_test.get("latency_ms"),
        "read_ok": r2_test.get("read_ok", False),
        "write_ok": r2_test.get("write_ok", False),
        "checked_at": now_iso,
    })

    return {
        "checked_at": now_iso,
        "services": services,
    }
