from cryptography.fernet import InvalidToken
from django.db.models import F
from django.http import Http404
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.proxies.crypto import decrypt_proxy_credentials
from modules.proxies.models import ProxyEndpoint
from modules.proxies.probe import check_proxy
from .views import resolve_proxy_pipeline


class ProxyCheckThrottle(UserRateThrottle):
    rate = "6/min"


class ProxyCheckAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [ProxyCheckThrottle]

    def post(self, request, pipeline_id, proxy_id):
        pipeline = resolve_proxy_pipeline(
            request.user,
            pipeline_id,
        )
        if request.data not in ({}, None):
            return Response({
                "success": False,
                "message": "Không nhận URL hoặc tham số kiểm tra.",
            }, status=400)
        proxy = (
            ProxyEndpoint.objects
            .select_related("auth_secret")
            .filter(
                pk=proxy_id,
                pipeline_id=pipeline.pk,
            )
            .first()
        )
        if proxy is None:
            raise Http404("Proxy không tồn tại.")
        if not proxy.is_enabled:
            return Response({
                "success": False,
                "message": "Proxy đang bị tắt.",
            }, status=409)
        # Capture configuration version before network I/O.
        version = proxy.updated_at
        credentials = None
        try:
            secret = getattr(proxy, "auth_secret", None)
            if secret is not None:
                credentials = decrypt_proxy_credentials(
                    secret.ciphertext
                )
        except (InvalidToken, ValueError, RuntimeError):
            return Response({
                "success": False,
                "message": (
                    "Không thể giải mã thông tin Proxy. "
                    "Kiểm tra khóa mã hóa trên server."
                ),
            }, status=503)
        result = check_proxy(
            protocol=proxy.protocol,
            host=proxy.host,
            port=proxy.port,
            credentials=credentials,
        )
        checked_at = timezone.now()
        status_value = (
            ProxyEndpoint.HealthStatus.HEALTHY
            if result.healthy
            else ProxyEndpoint.HealthStatus.FAILED
        )
        # Optimistic concurrency guard:
        # do not overwrite a Proxy edited/deleted
        # while this network check was running.
        updated = ProxyEndpoint.objects.filter(
            pk=proxy.pk,
            pipeline_id=pipeline.pk,
            updated_at=version,
            is_enabled=True,
        ).update(
            health_status=status_value,
            exit_ip=result.exit_ip,
            latency_ms=result.latency_ms,
            last_checked_at=checked_at,
            updated_at=checked_at,
        )
        if updated != 1:
            return Response({
                "success": False,
                "message": (
                    "Proxy đã thay đổi trong lúc kiểm tra. "
                    "Hãy tải lại và thử lại."
                ),
            }, status=409)
        response = Response({
            "success": True,
            "message": result.message,
            "data": {
                "id": str(proxy.pk),
                "health_status": status_value,
                "exit_ip": result.exit_ip,
                "latency_ms": result.latency_ms,
                "last_checked_at": checked_at.isoformat(),
            },
        })
        response["Cache-Control"] = "private, no-store"
        return response
