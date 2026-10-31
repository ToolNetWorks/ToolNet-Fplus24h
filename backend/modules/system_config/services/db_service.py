import time
from typing import Dict, Any, Optional

from django.conf import settings
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from ..crypto import sanitize_text


def _extract_region_from_host(host: str) -> str:
    if not host:
        return ""
    parts = host.split(".")
    for i, p in enumerate(parts):
        if p in ("aws", "neon") and i > 0:
            return ".".join(parts[max(0, i - 1):i + 1])
    return "Neon Cloud"


def get_database_status() -> Dict[str, Any]:
    """Retrieve actual connection, pool stats, and migration status for primary Neon database.
    Returns only essential metrics for dashboard display - no sensitive infrastructure details.
    """
    db_config = settings.DATABASES.get("default", {})
    host = db_config.get("HOST", "")
    region = _extract_region_from_host(host)

    start = time.monotonic()
    connection_status = "unknown"
    latency_ms = None
    server_version = ""
    active_connections = 0
    max_connections = 0
    database_size = "Unknown"
    error_msg = ""

    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.execute("SELECT version();" if connection.vendor == "postgresql" else "SELECT sqlite_version();")
            row = cur.fetchone()
            if row:
                server_version = row[0].split("\n")[0]

            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();")
            row = cur.fetchone()
            if row:
                active_connections = int(row[0])

            cur.execute("SHOW max_connections;")
            row = cur.fetchone()
            if row:
                try:
                    max_connections = int(row[0])
                except Exception:
                    max_connections = str(row[0])

            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()));")
            row = cur.fetchone()
            if row:
                database_size = str(row[0])

        latency_ms = int((time.monotonic() - start) * 1000)
        connection_status = "connected"
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        connection_status = "error"
        error_msg = "Không truy vấn được dịch vụ; kiểm tra kết nối và quyền truy cập."

    # Migration inspection - use Django's migrate --plan equivalent check
    migration_info = {
        "total_migrations": 0,
        "applied_migrations": 0,
        "pending_migrations": 0,
        "is_synced": True,
    }
    try:
        loader = MigrationLoader(connection)
        total = len(loader.graph.nodes)
        applied = len(loader.applied_migrations)
        pending = max(0, total - applied)
        migration_info = {
            "total_migrations": total,
            "applied_migrations": applied,
            "pending_migrations": pending,
            "is_synced": pending == 0,
        }
    except Exception as e:
        migration_info["error"] = "Không truy vấn được dịch vụ; kiểm tra kết nối và quyền truy cập."

    # Return only dashboard-essential data - no host, database_name, user, port, engine, pool internals
    return {
        "provider": "Neon PostgreSQL",
        "region": region,
        "connection_status": connection_status,
        "latency_ms": latency_ms,
        "last_error": error_msg,
        "database_size": database_size,
        "migrations_pending": migration_info.get("pending_migrations", 0),
        "migrations_synced": migration_info.get("is_synced", True),
        "checked_at": time.time(),
    }


def test_database_connection(test_url: Optional[str] = None) -> Dict[str, Any]:
    """Test connecting to current database or an alternative database URL without altering production."""
    start = time.monotonic()

    if not test_url or not test_url.strip():
        # Test current default connection
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.execute("SELECT version();" if connection.vendor == "postgresql" else "SELECT sqlite_version();")
                ver = cur.fetchone()[0].split("\n")[0]
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": True,
                "latency_ms": latency_ms,
                "server_version": ver,
                "message": "Kết nối thành công đến database hiện tại.",
            }
        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": "Không truy vấn được dịch vụ; kiểm tra kết nối và quyền truy cập.",
            }

    # Test an alternative URL safely
    try:
        parsed_config = dj_database_url.parse(
            test_url.strip(),
            conn_max_age=0,
            ssl_require=True,
        )
        if not parsed_config.get("NAME"):
            return {
                "success": False,
                "error": "Chuỗi kết nối không hợp lệ (thiếu Database Name).",
            }

        # Import psycopg / psycopg2 driver directly to test cursor without registering in django
        import psycopg

        conn_params = {
            "dbname": parsed_config["NAME"],
            "user": parsed_config.get("USER"),
            "password": parsed_config.get("PASSWORD"),
            "host": parsed_config.get("HOST"),
            "port": parsed_config.get("PORT") or 5432,
            "sslmode": "require",
            "connect_timeout": 5,
        }
        with psycopg.connect(**conn_params) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.execute("SELECT version();" if connection.vendor == "postgresql" else "SELECT sqlite_version();")
                ver = cur.fetchone()[0].split("\n")[0]
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": True,
            "latency_ms": latency_ms,
            "server_version": ver,
            "message": "Kết nối thử nghiệm thành công (không áp dụng vào production).",
        }
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "latency_ms": latency_ms,
            "error": "Không truy vấn được dịch vụ; kiểm tra kết nối và quyền truy cập.",
        }
