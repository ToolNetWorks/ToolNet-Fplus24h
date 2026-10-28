import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.proxies.models import ProxyEndpoint

User = get_user_model()
suffix = uuid.uuid4().hex[:10]
initial_count = ProxyEndpoint.objects.count()


def make_pipeline(label):
    username = f"proxy_{label}_{suffix}"
    user = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Proxy Test {label} {suffix}",
        ctv=user,
        status="active",
    )
    return pipeline


with transaction.atomic():
    pipeline_a = make_pipeline("a")
    pipeline_b = make_pipeline("b")
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
        label="Facebook Other",
    )
    proxy_a = ProxyEndpoint.objects.create(
        pipeline=pipeline_a,
        account=account_a,
        protocol="http",
        host="8.8.8.8",
        port=8000,
    )
    assert proxy_a.account_id == account_a.pk
    print("ONE ACCOUNT ONE PROXY: PASS")

    try:
        ProxyEndpoint.objects.create(
            pipeline=pipeline_a,
            account=account_a,
            protocol="http",
            host="1.1.1.1",
            port=9000,
        )
    except ValidationError:
        print("MULTIPLE PROXIES PER ACCOUNT: BLOCKED")
    else:
        raise AssertionError(
            "Account accepted multiple proxies"
        )

    try:
        ProxyEndpoint.objects.create(
            pipeline=pipeline_a,
            account=account_b,
            protocol="http",
            host="8.8.8.8",
            port=8000,
        )
    except ValidationError:
        print("DUPLICATE PROXY ENDPOINT: BLOCKED")
    else:
        raise AssertionError(
            "Duplicate endpoint was accepted"
        )

    try:
        ProxyEndpoint.objects.create(
            pipeline=pipeline_a,
            account=other_account,
            protocol="socks5",
            host="1.1.1.1",
            port=1080,
        )
    except ValidationError:
        print("CROSS-PIPELINE ASSIGNMENT: BLOCKED")
    else:
        raise AssertionError(
            "Cross-Pipeline assignment was accepted"
        )

    try:
        ProxyEndpoint.objects.create(
            pipeline=pipeline_a,
            protocol="http",
            host="127.0.0.1",
            port=8080,
        )
    except ValidationError:
        print("LOOPBACK PROXY: BLOCKED")
    else:
        raise AssertionError(
            "Loopback was accepted"
        )

    proxy_b = ProxyEndpoint.objects.create(
        pipeline=pipeline_a,
        account=account_b,
        protocol="socks5",
        host="1.1.1.1",
        port=1080,
    )
    assert proxy_b.health_status == "untested"
    assert proxy_b.exit_ip is None
    print("SOCKS5 SUPPORT: PASS")
    print("UNTESTED STATUS: CORRECT")

    transaction.set_rollback(True)

assert ProxyEndpoint.objects.count() == initial_count
print("DATABASE CHANGES: ROLLED BACK")
print("PROXY MODELS TEST: PASSED")
