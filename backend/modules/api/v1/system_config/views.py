import json
import logging
from typing import Dict, Any

from django.core.paginator import Paginator
from django.db import transaction
from modules.system_config.serializers import AIProviderSerializer, StorageConfigSerializer
from django.utils import timezone
from rest_framework import status, serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.api.v1.permissions import IsSuperAdmin
from modules.system_config.models import (
    AIProvider,
    AIProviderType,
    AIProviderKey,
    StorageConfig,
    SystemConfigAuditLog,
)
from modules.system_config.crypto import sanitize_text, mask_secret
from modules.system_config.services.db_service import (
    get_database_status,
    test_database_connection,
)
from modules.system_config.services.r2_service import (
    get_r2_status,
    test_r2_connection,
    get_active_r2_config_dict,
)
from modules.system_config.services.ai_unified_service import (
    ensure_default_provider_initialized,
    test_provider_connection,
)
from modules.system_config.services.services_health_service import get_services_health

logger = logging.getLogger(__name__)


def _get_client_ip(request) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _log_audit(request, section: str, action: str, target_id: str = "", target_name: str = "", details: Dict[str, Any] = None):
    user = request.user
    SystemConfigAuditLog.objects.create(
        actor_id=user.id if user and user.is_authenticated else None,
        actor_username=user.username if user and user.is_authenticated else "unknown",
        actor_email=user.email if user and user.is_authenticated else "",
        section=section,
        action=action,
        target_id=str(target_id),
        target_name=str(target_name),
        details=details or {},
        ip_address=_get_client_ip(request),
    )

class ConfigAPIView(APIView):
    def dispatch(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().dispatch(request, *args, **kwargs)
        except Exception:
            logger.error("System configuration operation failed; transaction rolled back")
            return __import__("django.http", fromlist=["JsonResponse"]).JsonResponse({"error": "Không thể thực hiện thao tác cấu hình. Vui lòng thử lại."}, status=503)


# ==============================================================================
# TAB 1: DATABASE
# ==============================================================================

class DatabaseConfigAPIView(ConfigAPIView):
    """GET current Database status & pool metrics. POST to test connection."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        status_data = get_database_status()
        return Response(status_data, status=status.HTTP_200_OK)

    def post(self, request):
        test_url = serializers.CharField(required=False, allow_blank=True, max_length=4096).run_validation(request.data.get("database_url", ""))
        result = test_database_connection(test_url)
        _log_audit(
            request,
            section="database",
            action="test_connection",
            target_name=result.get("database_name", "Current DB"),
            details={
                "success": result.get("success"),
                "latency_ms": result.get("latency_ms"),
                "is_custom_url": bool(test_url),
            },
        )
        return Response(result, status=status.HTTP_200_OK)


# ==============================================================================
# TAB 2: CLOUDFLARE R2
# ==============================================================================

class R2ConfigAPIView(ConfigAPIView):
    """Manage Cloudflare R2 credentials with safe testing and encryption."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        data = get_r2_status()
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        validator = StorageConfigSerializer(data=request.data)
        validator.is_valid(raise_exception=True)
        account_id = str(request.data.get("account_id", "")).strip()
        endpoint_url = str(request.data.get("endpoint_url", "")).strip()
        bucket_name = str(request.data.get("bucket_name", "")).strip()
        access_key_id = str(request.data.get("access_key_id", "")).strip()
        secret_access_key = str(request.data.get("secret_access_key", "")).strip()

        if not access_key_id:
            access_key_id = get_active_r2_config_dict()["access_key_id"]
        if not bucket_name or not access_key_id:
            return Response(
                {"error": "Bucket Name và Access Key ID không được để trống."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        storage_config = StorageConfig.objects.first()
        if not storage_config:
            storage_config = StorageConfig()

        # If secret_access_key is empty, keep existing secret
        existing_secret = storage_config.get_secret_key() or get_active_r2_config_dict()["secret_access_key"]
        final_secret = secret_access_key if secret_access_key else existing_secret

        if not final_secret:
            return Response(
                {"error": "Secret Access Key chưa được cung cấp."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Test connection with these credentials before saving
        test_payload = {
            "account_id": account_id,
            "endpoint_url": endpoint_url,
            "bucket_name": bucket_name,
            "access_key_id": access_key_id,
            "secret_access_key": final_secret,
        }
        test_result = test_r2_connection(test_payload, test_read_write=True)
        if not test_result.get("success"):
            return Response(
                {
                    "error": f"Kiểm thử kết nối R2 thất bại trước khi lưu: {test_result.get('error')}",
                    "test_result": test_result,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        storage_config.account_id = account_id
        storage_config.endpoint_url = endpoint_url
        storage_config.bucket_name = bucket_name
        storage_config.set_access_key(access_key_id)
        storage_config.set_secret_key(final_secret)
        storage_config.is_active = True
        storage_config.last_tested_at = timezone.now()
        storage_config.last_status = "ok"
        storage_config.last_latency_ms = test_result.get("latency_ms")
        storage_config.last_error_message = ""
        storage_config.save()

        _log_audit(
            request,
            section="r2",
            action="update_credentials",
            target_id=str(storage_config.id),
            target_name=bucket_name,
            details={
                "bucket_name": bucket_name,
                "account_id": account_id,
                "has_endpoint": bool(endpoint_url),
                "key_updated": bool(secret_access_key),
                "latency_ms": test_result.get("latency_ms"),
            },
        )

        return Response(get_r2_status(), status=status.HTTP_200_OK)

    def patch(self, request):
        field = serializers.BooleanField()
        active = field.run_validation(request.data.get("is_active"))
        cfg = StorageConfig.objects.first()
        if not cfg:
            return Response({"error": "Chưa có cấu hình R2 riêng."}, status=400)
        cfg.is_active = active
        cfg.save(update_fields=["is_active", "updated_at"])
        _log_audit(request, "r2", "toggle_override", cfg.id, cfg.bucket_name, {"is_active": active})
        return Response(get_r2_status())

    def delete(self, request):
        StorageConfig.objects.all().delete()
        _log_audit(request, "r2", "reset_to_env")
        return Response(get_r2_status())


class R2TestAPIView(ConfigAPIView):
    """Test R2 connection and read/write permissions."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        raw_config = None
        if request.data.get("bucket_name"):
            validator = StorageConfigSerializer(data=request.data)
            validator.is_valid(raise_exception=True)
            raw_config = {**get_active_r2_config_dict(), **dict(request.data)}
            for key in ("access_key_id", "secret_access_key"):
                if not request.data.get(key):
                    raw_config[key] = get_active_r2_config_dict()[key]
        test_read_write = serializers.BooleanField().run_validation(request.data.get("test_read_write", True))
        result = test_r2_connection(raw_config, test_read_write=test_read_write)

        _log_audit(
            request,
            section="r2",
            action="test_connection",
            target_name=result.get("bucket", "Active R2 Bucket"),
            details={
                "success": result.get("success"),
                "read_ok": result.get("read_ok"),
                "write_ok": result.get("write_ok"),
                "latency_ms": result.get("latency_ms"),
            },
        )
        return Response(result, status=status.HTTP_200_OK)


class R2ResetToEnvAPIView(ConfigAPIView):
    """Delete database override and revert to .env R2 configuration."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        StorageConfig.objects.all().delete()
        _log_audit(
            request,
            section="r2",
            action="reset_to_env",
            target_name="Reverted to .env configuration",
            details={},
        )
        return Response(get_r2_status(), status=status.HTTP_200_OK)


# ==============================================================================
# TAB 3: API PROVIDERS
# ==============================================================================

def _serialize_provider(provider: AIProvider) -> Dict[str, Any]:
    return {
        "id": str(provider.id),
        "name": provider.name,
        "provider_type": provider.provider_type,
        "provider_type_display": provider.get_provider_type_display(),
        "base_url": provider.base_url,
        "default_model": provider.default_model,
        "models": provider.available_models or [provider.default_model],
        "is_active": provider.is_active,
        "is_default": provider.is_default,
        "priority": provider.priority,
        "timeout_seconds": provider.timeout_seconds,
        "has_api_key": provider.has_api_key,
        "api_key_masked": "••••••••" if provider.has_api_key else "",
        "last_tested_at": provider.last_tested_at.isoformat() if provider.last_tested_at else None,
        "last_status": provider.last_status,
        "last_error_message": "Provider connection failed" if provider.last_error_message else "",
        "last_latency_ms": provider.last_latency_ms,
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


class AIProviderListCreateAPIView(ConfigAPIView):
    """GET list of all AI providers. POST create new provider."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        providers = AIProvider.objects.all().order_by("priority", "-is_default", "created_at")
        return Response(
            [_serialize_provider(p) for p in providers],
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = AIProviderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        _log_audit(request, "ai_providers", "create_provider", provider.id, provider.name, {"key_updated": True})
        return Response(_serialize_provider(provider), status=201)


class AIProviderDetailAPIView(ConfigAPIView):
    """GET, PUT, DELETE a specific AI provider."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def _get_provider(self, provider_id: str) -> AIProvider:
        try:
            return AIProvider.objects.get(id=provider_id)
        except (AIProvider.DoesNotExist, ValueError):
            return None

    def get(self, request, provider_id):
        provider = self._get_provider(provider_id)
        if not provider:
            return Response({"error": "Không tìm thấy Provider."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_provider(provider), status=status.HTTP_200_OK)

    def put(self, request, provider_id):
        provider = self._get_provider(provider_id)
        if not provider:
            return Response({"error": "Không tìm thấy Provider."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AIProviderSerializer(provider, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        _log_audit(request, "ai_providers", "update_provider", provider.id, provider.name, {"key_updated": bool(request.data.get("api_key"))})
        return Response(_serialize_provider(provider))

    patch = put

    def delete(self, request, provider_id):
        provider = self._get_provider(provider_id)
        if not provider:
            return Response({"error": "Không tìm thấy Provider."}, status=status.HTTP_404_NOT_FOUND)

        name = provider.name
        was_default = provider.is_default
        provider.delete()

        # The environment provider becomes primary until an admin selects a new default.

        _log_audit(
            request,
            section="ai_providers",
            action="delete_provider",
            target_id=str(provider_id),
            target_name=name,
            details={"was_default": was_default},
        )

        return Response({"message": f"Đã xóa Provider {name}."}, status=status.HTTP_200_OK)


class AIProviderTestAPIView(ConfigAPIView):
    """Test connection of an existing saved AI provider."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def post(self, request, provider_id):
        try:
            provider = AIProvider.objects.get(id=provider_id)
        except (AIProvider.DoesNotExist, ValueError):
            return Response({"error": "Không tìm thấy Provider."}, status=status.HTTP_404_NOT_FOUND)

        api_key = provider.get_api_key()

        if not api_key:
            return Response({"error": "Provider chưa có API Key."}, status=status.HTTP_400_BAD_REQUEST)

        result = test_provider_connection(
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            api_key=api_key,
            model=provider.default_model,
            timeout=provider.timeout_seconds,
        )

        provider.last_tested_at = timezone.now()
        provider.last_status = "ok" if result.get("success") else "error"
        provider.last_latency_ms = result.get("latency_ms")
        provider.last_error_message = result.get("error", "")
        provider.save(update_fields=["last_tested_at", "last_status", "last_latency_ms", "last_error_message"])

        _log_audit(
            request,
            section="ai_providers",
            action="test_provider",
            target_id=str(provider.id),
            target_name=provider.name,
            details={
                "success": result.get("success"),
                "latency_ms": result.get("latency_ms"),
                "error": result.get("error"),
            },
        )

        return Response(result, status=status.HTTP_200_OK)


class AIProviderAdHocTestAPIView(ConfigAPIView):
    """Test connection with uncommitted parameters before saving."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        provider_type = str(request.data.get("provider_type", "openai_compatible")).strip()
        base_url = str(request.data.get("base_url", "")).strip()
        api_key = str(request.data.get("api_key", "")).strip()
        model = str(request.data.get("model", "")).strip()

        if not base_url or not api_key or not model:
            return Response(
                {"error": "Base URL, API Key và Model là bắt buộc để kiểm thử."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = test_provider_connection(
            provider_type=provider_type,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=25,
        )

        _log_audit(
            request,
            section="ai_providers",
            action="test_adhoc_provider",
            target_name=f"{provider_type} / {model}",
            details={
                "success": result.get("success"),
                "latency_ms": result.get("latency_ms"),
                "base_url": base_url,
            },
        )

        return Response(result, status=status.HTTP_200_OK)


class AIProviderSetDefaultAPIView(ConfigAPIView):
    """Set provider as system default."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def post(self, request, provider_id):
        try:
            provider = AIProvider.objects.get(id=provider_id)
        except (AIProvider.DoesNotExist, ValueError):
            return Response({"error": "Không tìm thấy Provider."}, status=status.HTTP_404_NOT_FOUND)

        if not provider.is_active:
            return Response({"error": "Hãy bật Provider trước khi chọn mặc định."}, status=400)
        AIProvider.objects.filter(is_default=True).update(is_default=False)
        provider.is_default = True
        provider.save(update_fields=["is_default"])

        _log_audit(
            request,
            section="ai_providers",
            action="set_default_provider",
            target_id=str(provider.id),
            target_name=provider.name,
            details={"is_default": True},
        )

        return Response(_serialize_provider(provider), status=status.HTTP_200_OK)


class AIProviderRotateKeyAPIView(ConfigAPIView):
    """Explicitly rotate or revoke the API key of a provider."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def post(self, request, provider_id):
        try:
            provider = AIProvider.objects.get(id=provider_id)
        except (AIProvider.DoesNotExist, ValueError):
            return Response({"error": "Không tìm thấy Provider."}, status=status.HTTP_404_NOT_FOUND)

        new_key = str(request.data.get("new_api_key", "")).strip()
        action_type = str(request.data.get("action", "rotate")).strip()  # rotate or revoke

        if action_type == "revoke":
            provider.api_key_encrypted = ""
            provider.keys.update(is_active=False)
            provider.save(update_fields=["api_key_encrypted"])
            msg = f"Đã thu hồi API Key của Provider {provider.name}."
        else:
            if not new_key:
                return Response(
                    {"error": "Vui lòng nhập API Key mới để rotate."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            provider.set_api_key(new_key)
            managed = provider.keys.order_by("priority", "id").first() or AIProviderKey(provider=provider, name="Primary Key")
            managed.set_secret(new_key); managed.is_active = True; managed.last_status = "untested"; managed.save()
            provider.save(update_fields=["api_key_encrypted"])
            msg = f"Đã cập nhật API Key mới cho Provider {provider.name}."

        _log_audit(
            request,
            section="ai_providers",
            action=f"{action_type}_key",
            target_id=str(provider.id),
            target_name=provider.name,
            details={"action": action_type},
        )

        return Response({"message": msg, "provider": _serialize_provider(provider)}, status=status.HTTP_200_OK)


# ==============================================================================
# TAB 4: SYSTEM SERVICES
# ==============================================================================

class ServicesHealthAPIView(ConfigAPIView):
    """GET live health metrics for all 7 system services."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        data = get_services_health()
        return Response(data, status=status.HTTP_200_OK)


# ==============================================================================
# AUDIT LOG
# ==============================================================================

class SystemConfigAuditLogAPIView(ConfigAPIView):
    """Paginated list of system configuration audit logs."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        try:
            page_num = max(1, int(request.query_params.get("page", 1)))
            page_size = max(1, min(int(request.query_params.get("page_size", 20)), 100))
        except ValueError:
            return Response({"error": "Phân trang không hợp lệ."}, status=400)
        section = request.query_params.get("section", "").strip()

        qs = SystemConfigAuditLog.objects.all().order_by("-created_at")
        if section:
            qs = qs.filter(section=section)

        paginator = Paginator(qs, page_size)
        try:
            page = paginator.page(page_num)
        except Exception:
            page = paginator.page(1)

        logs_data = []
        for log in page:
            logs_data.append({
                "id": str(log.id),
                "actor_username": log.actor_username,
                "actor_email": log.actor_email,
                "section": log.section,
                "action": log.action,
                "target_id": log.target_id,
                "target_name": log.target_name,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat(),
            })

        return Response({
            "results": logs_data,
            "count": paginator.count,
            "total_pages": paginator.num_pages,
            "current_page": page.number,
            "page_size": page_size,
        }, status=status.HTTP_200_OK)
