import io
import time
import uuid
from typing import Dict, Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.db.models import Count, Sum

from ..models import StorageConfig, SystemConfigAuditLog
from ..crypto import sanitize_text, mask_secret
from modules.albums.models import AlbumImage
from modules.albums.services.r2_storage import read_r2_config


def get_active_r2_config_dict() -> Dict[str, Any]:
    """Retrieve active R2 configuration from database or fallback to environment."""
    db_config = StorageConfig.objects.filter(is_active=True).first()
    if db_config and db_config.bucket_name and db_config.access_key_id:
        secret = db_config.get_secret_key()
        if secret:
            return {
                "source": "database",
                "account_id": db_config.account_id,
                "endpoint_url": db_config.endpoint_url or f"https://{db_config.account_id}.r2.cloudflarestorage.com",
                "bucket_name": db_config.bucket_name,
                "access_key_id": db_config.get_access_key(),
                "secret_access_key": secret,
                "is_active": db_config.is_active,
                "last_tested_at": db_config.last_tested_at,
                "last_status": db_config.last_status,
                "last_latency_ms": db_config.last_latency_ms,
            }

    # Fallback to .env config
    env_cfg = read_r2_config()
    endpoint = env_cfg.get("endpoint", "")
    # Try extract account_id from endpoint (https://<account_id>.r2.cloudflarestorage.com)
    account_id = ""
    if ".r2.cloudflarestorage.com" in endpoint:
        try:
            account_id = endpoint.split("://")[1].split(".r2.")[0]
        except Exception:
            pass

    return {
        "source": "environment",
        "account_id": account_id,
        "endpoint_url": endpoint,
        "bucket_name": env_cfg.get("bucket", ""),
        "access_key_id": env_cfg.get("access_key", ""),
        "secret_access_key": env_cfg.get("secret_key", ""),
        "is_active": True,
        "last_tested_at": None,
        "last_status": "untested",
        "last_latency_ms": None,
    }


def get_r2_status() -> Dict[str, Any]:
    """Return R2 configuration (secrets redacted) and real storage statistics."""
    cfg = get_active_r2_config_dict()

    # Image statistics from database
    agg = AlbumImage.objects.aggregate(
        total_images=Count("id"),
        total_bytes=Sum("file_size"),
    )
    total_images = agg.get("total_images") or 0
    total_bytes = agg.get("total_bytes") or 0

    if total_bytes >= 1024 * 1024 * 1024:
        size_display = f"{total_bytes / (1024 * 1024 * 1024):.2f} GB"
    elif total_bytes >= 1024 * 1024:
        size_display = f"{total_bytes / (1024 * 1024):.2f} MB"
    elif total_bytes >= 1024:
        size_display = f"{total_bytes / 1024:.2f} KB"
    else:
        size_display = f"{total_bytes} B"

    return {
        "source": cfg["source"],
        "account_id": cfg["account_id"],
        "endpoint_url": cfg["endpoint_url"],
        "bucket_name": cfg["bucket_name"],
        "has_access_key": bool(cfg["access_key_id"]),
        "override_exists": StorageConfig.objects.exists(),
        "override_active": StorageConfig.objects.filter(is_active=True).exists(),
        "has_secret": bool(cfg.get("secret_access_key")),
        "secret_status": "Đã cấu hình" if cfg.get("secret_access_key") else "Chưa cấu hình",
        "is_active": cfg["is_active"],
        "last_tested_at": cfg["last_tested_at"],
        "last_status": cfg["last_status"],
        "last_latency_ms": cfg["last_latency_ms"],
        "storage_stats": {
            "total_images": total_images,
            "total_bytes": total_bytes,
            "total_size_display": size_display,
        },
    }


def test_r2_connection(
    config_dict: Optional[Dict[str, str]] = None,
    test_read_write: bool = False,
) -> Dict[str, Any]:
    """Test connection to Cloudflare R2 bucket.

    If test_read_write is True, writes a temporary probe file and immediately deletes it.
    Does NOT leave any orphaned objects or touch existing images.
    """
    if config_dict and config_dict.get("bucket_name"):
        endpoint = config_dict.get("endpoint_url", "").strip()
        access_key = config_dict.get("access_key_id", "").strip()
        secret_key = config_dict.get("secret_access_key", "").strip()
        bucket = config_dict.get("bucket_name", "").strip()
        account_id = config_dict.get("account_id", "").strip()

        if not endpoint and account_id:
            endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    else:
        active = get_active_r2_config_dict()
        endpoint = active["endpoint_url"]
        access_key = active["access_key_id"]
        secret_key = active["secret_access_key"]
        bucket = active["bucket_name"]

    if not endpoint or not access_key or not secret_key or not bucket:
        return {
            "success": False,
            "error": "Thiếu thông tin kết nối R2 (endpoint, access key, secret key, hoặc bucket).",
        }

    start = time.monotonic()
    probe_key = None
    read_ok = False
    write_ok = False

    try:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=6,
                read_timeout=15,
                retries={"max_attempts": 1},
            ),
        )

        # 1. Test head bucket
        client.head_bucket(Bucket=bucket)

        # 2. Test read/write probe if requested
        if test_read_write:
            probe_key = f".probe/test_probe_{uuid.uuid4().hex[:12]}.tmp"
            test_content = b"TOOLNET_R2_PROBE_OK"

            # Write probe
            client.put_object(
                Bucket=bucket,
                Key=probe_key,
                Body=test_content,
                ContentType="text/plain",
            )
            write_ok = True

            # Read back probe
            resp = client.get_object(Bucket=bucket, Key=probe_key)
            body = resp["Body"].read()
            if body == test_content:
                read_ok = True
            else:
                read_ok = False
        else:
            read_ok = True
            write_ok = None

        if probe_key:
            client.delete_object(Bucket=bucket, Key=probe_key)
            probe_key = None
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": bool(read_ok and (write_ok if test_read_write else True)),
            "latency_ms": latency_ms,
            "bucket": bucket,
            "read_ok": read_ok,
            "write_ok": write_ok,
            "message": "Kết nối và kiểm tra quyền R2 thành công.",
        }

    except ClientError as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        err_code = e.response.get("Error", {}).get("Code", "ClientError")
        err_msg = e.response.get("Error", {}).get("Message", str(e))
        return {
            "success": False,
            "latency_ms": latency_ms,
            "error": f"R2 request failed ({err_code})",
        }
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "latency_ms": latency_ms,
            "error": "R2 connection failed",
        }
    finally:
        # Guarantee cleanup of probe key
        if probe_key:
            try:
                client.delete_object(Bucket=bucket, Key=probe_key)
            except Exception:
                import logging
                logging.getLogger(__name__).error("R2 temporary probe cleanup failed; manual cleanup required for probe namespace")
