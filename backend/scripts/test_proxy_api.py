import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.facebook_accounts.models import FacebookAccount
from modules.pipelines.models import Pipeline
from modules.proxies.crypto import decrypt_proxy_credentials
from modules.proxies.models import ProxyEndpoint, ProxyAuthSecret
from modules.api.v1.proxies.views import (
    ProxyListCreateAPIView,
    ProxyBulkAPIView,
    ProxyDetailAPIView,
)

User = get_user_model()
factory = APIRequestFactory()
collection_view = ProxyListCreateAPIView.as_view()
bulk_view = ProxyBulkAPIView.as_view()
detail_view = ProxyDetailAPIView.as_view()
suffix = uuid.uuid4().hex[:10]
initial_count = ProxyEndpoint.objects.count()


def make_pipeline(label):
    username = f"proxy_api_{label}_{suffix}"
    ctv = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Proxy API Test {label} {suffix}",
        ctv=ctv,
        status="active",
    )
    return pipeline, ctv


def request(method, pipeline, user=None, data=None, proxy_id=None, bulk=False):
    path = f"/api/v1/pipelines/{pipeline.pk}/proxies/"
    if proxy_id:
        path += f"{proxy_id}/"
    elif bulk:
        path += "bulk/"
    if method == "get":
        req = factory.get(path)
    else:
        req = getattr(factory, method)(
            path,
            data=data,
            format="json",
        )
    if user:
        force_authenticate(req, user=user)
    view = (
        detail_view if proxy_id
        else bulk_view if bulk
        else collection_view
    )
    kwargs = {"pipeline_id": pipeline.pk}
    if proxy_id:
        kwargs["proxy_id"] = proxy_id
    return view(req, **kwargs)


with transaction.atomic():
    pipeline_a, ctv_a = make_pipeline("a")
    pipeline_b, ctv_b = make_pipeline("b")
    account_a = FacebookAccount.objects.create(
        pipeline=pipeline_a,
        label="Facebook A",
    )
    account_b = FacebookAccount.objects.create(
        pipeline=pipeline_a,
        label="Facebook B",
    )
    other_account = FacebookAccount.objects.create(
        pipeline=pipeline_b,
        label="Other Facebook",
    )
    response = request(
        "post",
        pipeline_a,
        ctv_a,
        {
            "host": "8.8.8.8",
            "port": 8000,
            "protocol": "http",
            "account_id": str(account_a.pk),
            "username": "proxyuser",
            "password": "example-password",
        },
    )
    assert response.status_code == 201, response.data
    proxy_id = response.data["data"]["id"]
    assert response.data["data"]["has_auth"] is True
    assert "password" not in response.data["data"]
    assert "username" not in response.data["data"]
    secret = ProxyAuthSecret.objects.get(
        proxy_id=proxy_id
    )
    assert "example-password" not in secret.ciphertext
    decrypted = decrypt_proxy_credentials(
        secret.ciphertext
    )
    assert decrypted == {
        "username": "proxyuser",
        "password": "example-password",
    }
    print("PROXY CREATE: PASS")
    print("CREDENTIAL ENCRYPTION: PASS")
    print("SECRET NOT EXPOSED: PASS")

    response = request(
        "post",
        pipeline_a,
        ctv_a,
        {
            "items": [
                {
                    "host": "1.1.1.1",
                    "port": 1080,
                    "protocol": "socks5",
                },
                {
                    "host": "8.8.4.4",
                    "port": 8080,
                    "protocol": "http",
                },
            ],
        },
        bulk=True,
    )
    assert response.status_code == 201, response.data
    assert response.data["data"]["created"] == 2
    print("BULK IMPORT: PASS")

    before = ProxyEndpoint.objects.filter(
        pipeline=pipeline_a
    ).count()
    response = request(
        "post",
        pipeline_a,
        ctv_a,
        {
            "items": [
                {
                    "host": "9.9.9.9",
                    "port": 9000,
                },
                {
                    "host": "8.8.8.8",
                    "port": 8000,
                    "protocol": "http",
                },
            ],
        },
        bulk=True,
    )
    assert response.status_code in (400, 409), response.data
    assert ProxyEndpoint.objects.filter(
        pipeline=pipeline_a
    ).count() == before
    print("BULK ATOMIC ROLLBACK: PASS")

    second = ProxyEndpoint.objects.get(
        pipeline=pipeline_a,
        host="1.1.1.1",
    )
    response = request(
        "patch",
        pipeline_a,
        ctv_a,
        {
            "account_id": str(account_b.pk),
        },
        proxy_id=second.pk,
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["account"]["id"] == str(
        account_b.pk
    )
    print("ASSIGN FACEBOOK ACCOUNT: PASS")

    response = request(
        "patch",
        pipeline_a,
        ctv_a,
        {
            "account_id": str(other_account.pk),
        },
        proxy_id=second.pk,
    )
    assert response.status_code == 400
    print("CROSS-PIPELINE ASSIGNMENT: BLOCKED")

    response = request(
        "patch",
        pipeline_a,
        ctv_a,
        {
            "account_id": str(account_a.pk),
        },
        proxy_id=second.pk,
    )
    assert response.status_code in (400, 409)
    print("DUPLICATE ACCOUNT ASSIGNMENT: BLOCKED")

    response = request(
        "get",
        pipeline_b,
        ctv_a,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE LIST: BLOCKED")

    response = request(
        "get",
        pipeline_a,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS ACCESS: BLOCKED")

    response = request(
        "delete",
        pipeline_a,
        ctv_a,
        proxy_id=second.pk,
    )
    assert response.status_code == 200
    assert not ProxyEndpoint.objects.filter(
        pk=second.pk
    ).exists()
    print("PROXY DELETE: PASS")

    transaction.set_rollback(True)

assert ProxyEndpoint.objects.count() == initial_count
print("DATABASE CHANGES: ROLLED BACK")
print("PROXY API TEST: PASSED")
