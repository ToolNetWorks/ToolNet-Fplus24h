import socket
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.proxies.probe import (
    ProbeResult,
    ProxyProbeError,
    public_addresses,
)
from modules.api.v1.proxies.check_views import (
    ProxyCheckAPIView,
)

User = get_user_model()
factory = APIRequestFactory()
view = ProxyCheckAPIView.as_view()
suffix = uuid.uuid4().hex[:10]


def make_pipeline(label):
    user = User.objects.create_user(
        username=f"health_{label}_{suffix}",
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Proxy Health {label} {suffix}",
        ctv=user,
        status=Pipeline.Status.ACTIVE,
    )
    return pipeline, user


def check_request(pipeline, proxy, user=None, data=None):
    request = factory.post(
        f"/api/v1/pipelines/{pipeline.pk}/"
        f"proxies/{proxy.pk}/check/",
        data=data or {},
        format="json",
    )
    if user is not None:
        force_authenticate(request, user=user)
    return view(
        request,
        pipeline_id=pipeline.pk,
        proxy_id=proxy.pk,
    )


# DNS rebind / private-IP guard.
with (
    patch(
        "modules.proxies.probe.socket.getaddrinfo",
        return_value=[
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", 8080),
            ),
        ],
    ),
    patch("modules.proxies.probe.socket.socket") as create_socket,
):
    try:
        public_addresses("proxy.example.com", 8080)
    except ProxyProbeError:
        pass
    else:
        raise AssertionError("Private IP was accepted")
    create_socket.assert_not_called()
print("SSRF PRIVATE IP: BLOCKED")

with transaction.atomic():
    pipeline_a, ctv_a = make_pipeline("a")
    pipeline_b, ctv_b = make_pipeline("b")
    proxy = ProxyEndpoint.objects.create(
        pipeline=pipeline_a,
        protocol="http",
        host="8.8.8.8",
        port=8000,
    )
    with patch(
        "modules.api.v1.proxies.check_views.check_proxy",
        return_value=ProbeResult(
            healthy=True,
            exit_ip="1.1.1.1",
            latency_ms=350,
            message="Proxy hoạt động.",
        ),
    ) as mocked:
        response = check_request(
            pipeline_a,
            proxy,
            ctv_a,
        )
        assert response.status_code == 200, response.data
        assert response.data["data"]["health_status"] == "healthy"
        assert response.data["data"]["exit_ip"] == "1.1.1.1"
        assert response.data["data"]["latency_ms"] == 350
        mocked.assert_called_once()
    proxy.refresh_from_db()
    assert proxy.health_status == "healthy"
    assert proxy.exit_ip == "1.1.1.1"
    assert proxy.latency_ms == 350
    assert proxy.last_checked_at is not None
    print("HEALTHY PROXY: PASS")
    print("EXIT IP AND LATENCY: SAVED")

    with patch(
        "modules.api.v1.proxies.check_views.check_proxy",
        return_value=ProbeResult(
            healthy=False,
            exit_ip=None,
            latency_ms=900,
            message="Kết nối thất bại.",
        ),
    ):
        response = check_request(
            pipeline_a,
            proxy,
            ctv_a,
        )
        assert response.status_code == 200
    proxy.refresh_from_db()
    assert proxy.health_status == "failed"
    assert proxy.exit_ip is None
    assert proxy.latency_ms == 900
    print("FAILED PROXY: RECORDED")
    print("STALE EXIT IP: CLEARED")

    response = check_request(
        pipeline_a,
        proxy,
        ctv_b,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE CHECK: BLOCKED")

    response = check_request(
        pipeline_a,
        proxy,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS CHECK: BLOCKED")

    response = check_request(
        pipeline_a,
        proxy,
        ctv_a,
        data={
            "target_url": "http://127.0.0.1",
        },
    )
    assert response.status_code == 400
    print("CUSTOM TEST URL: BLOCKED")

    with patch(
        "modules.api.v1.proxies.check_views.check_proxy",
        return_value=ProbeResult(
            healthy=True,
            exit_ip="1.1.1.1",
            latency_ms=250,
            message="Proxy hoạt động.",
        ),
    ):
        proxy.is_enabled = False
        proxy.save(update_fields=["is_enabled", "updated_at"])
        response = check_request(
            pipeline_a,
            proxy,
            ctv_a,
        )
        assert response.status_code == 409
    print("DISABLED PROXY: BLOCKED")

    proxy.is_enabled = True
    proxy.save(update_fields=["is_enabled", "updated_at"])

    def concurrent_change(**kwargs):
        ProxyEndpoint.objects.filter(
            pk=proxy.pk
        ).update(
            updated_at=timezone.now() + timedelta(seconds=1)
        )
        return ProbeResult(
            healthy=True,
            exit_ip="1.1.1.1",
            latency_ms=100,
            message="Proxy hoạt động.",
        )

    with patch(
        "modules.api.v1.proxies.check_views.check_proxy",
        side_effect=concurrent_change,
    ):
        response = check_request(
            pipeline_a,
            proxy,
            ctv_a,
        )
        assert response.status_code == 409
    print("CONCURRENT UPDATE: PROTECTED")

    transaction.set_rollback(True)

print("DATABASE CHANGES: ROLLED BACK")
print("PROXY HEALTH API: PASSED")
