import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import APIRequestFactory, force_authenticate
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.api.v1.facebook_accounts.list_views import (
    FacebookAccountListAPIView,
)

User = get_user_model()
factory = APIRequestFactory()
view = FacebookAccountListAPIView.as_view()
suffix = uuid.uuid4().hex[:10]


def make_pipeline(label):
    username = f"ctv_table_{label}_{suffix}"
    user = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Account Table {label} {suffix}",
        ctv=user,
        status="active",
    )
    return pipeline, user


def request_accounts(pipeline, user, params=""):
    url = (
        f"/api/v1/pipelines/{pipeline.pk}/"
        f"facebook-accounts/?page=1&page_size=25{params}"
    )
    request = factory.get(url)
    if user is not None:
        force_authenticate(request, user=user)
    return view(request, pipeline_id=pipeline.pk)


with transaction.atomic():
    pipeline_a, ctv_a = make_pipeline("a")
    pipeline_b, ctv_b = make_pipeline("b")
    uid = "100" + str(uuid.uuid4().int)[:12]
    FacebookAccount.objects.create(
        pipeline=pipeline_a,
        label="Facebook Connected",
        facebook_user_id=uid,
        connection_status="connected",
    )
    FacebookAccount.objects.create(
        pipeline=pipeline_a,
        label="Facebook Pending",
        connection_status="not_connected",
    )
    FacebookAccount.objects.create(
        pipeline=pipeline_b,
        label="Other CTV Facebook",
        connection_status="connected",
    )

    response = request_accounts(pipeline_a, ctv_a)
    assert response.status_code == 200, response.data
    assert response.data["summary"]["total"] == 2
    assert response.data["summary"]["connected"] == 1
    assert response.data["summary"]["not_connected"] == 1
    assert response.data["pagination"]["total"] == 2
    print("PIPELINE SUMMARY: PASS")

    items = response.data["data"]
    assert any(
        item["facebook_user_id"] == uid
        for item in items
    )
    assert any(
        item["facebook_user_id"] is None
        for item in items
    )
    print("VERIFIED UID FIELD: PASS")
    print("UNVERIFIED UID REMAINS EMPTY: PASS")

    response = request_accounts(
        pipeline_a,
        ctv_a,
        "&status=connected",
    )
    assert response.status_code == 200
    assert response.data["pagination"]["total"] == 1
    assert response.data["summary"]["total"] == 2
    print("STATUS FILTER: PASS")
    print("FULL PIPELINE SUMMARY: PASS")

    response = request_accounts(
        pipeline_a,
        ctv_a,
        f"&search={uid}",
    )
    assert response.status_code == 200
    assert response.data["pagination"]["total"] == 1
    print("UID SEARCH: PASS")

    response = request_accounts(pipeline_b, ctv_a)
    assert response.status_code == 404
    print("CROSS-PIPELINE ACCESS: BLOCKED")

    response = request_accounts(pipeline_a, None)
    assert response.status_code in (401, 403)
    print("ANONYMOUS ACCESS: BLOCKED")

    transaction.set_rollback(True)

print("TEST DATA: ROLLED BACK")
print("CTV ACCOUNT TABLE API: PASSED")
