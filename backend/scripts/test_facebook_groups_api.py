from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.facebook_groups.models import FacebookGroup
from modules.api.v1.facebook_groups.views import (
    FacebookGroupCollectionAPIView,
    FacebookGroupDetailAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
collection = FacebookGroupCollectionAPIView.as_view()
detail = FacebookGroupDetailAPIView.as_view()
admin = User.objects.filter(
    is_superuser=True,
    is_staff=True,
    is_active=True,
).first()
assert admin is not None, "Super Admin not found"
suffix = uuid4().hex[:10]
def create_pipeline(number):
    username = f"groups_{number}_{suffix}"
    ctv = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
        email=f"{username}@example.invalid",
    )
    pipeline = Pipeline.objects.create(
        name=f"Group API Test {number} {suffix}",
        ctv=ctv,
        status="active",
    )
    return pipeline, ctv
def call_collection(
    method,
    pipeline,
    user=None,
    data=None,
):
    url = (
        f"/api/v1/pipelines/{pipeline.pk}/"
        "facebook-groups/"
    )
    request = getattr(factory, method)(
        url,
        data=data,
        format="json",
    )
    if user is not None:
        force_authenticate(request, user=user)
    return collection(
        request,
        pipeline_id=pipeline.pk,
    )
def call_detail(
    method,
    pipeline,
    group_id,
    user=None,
    data=None,
):
    url = (
        f"/api/v1/pipelines/{pipeline.pk}/"
        f"facebook-groups/{group_id}/"
    )
    request = getattr(factory, method)(
        url,
        data=data,
        format="json",
    )
    if user is not None:
        force_authenticate(request, user=user)
    return detail(
        request,
        pipeline_id=pipeline.pk,
        group_id=group_id,
    )
initial_count = FacebookGroup.objects.count()
with transaction.atomic():
    pipeline_a, ctv_a = create_pipeline("a")
    pipeline_b, ctv_b = create_pipeline("b")
    group_key = f"group{suffix}"
    payload = {
        "name": "Group thử nghiệm",
        "group_url": (
            f"https://www.facebook.com/groups/{group_key}/"
        ),
        "is_enabled": True,
    }
    response = call_collection(
        "post",
        pipeline_a,
        ctv_a,
        payload,
    )
    assert response.status_code == 201, response.data
    group_id = response.data["data"]["id"]
    print("CTV CREATE GROUP: PASS")
    response = call_collection(
        "get",
        pipeline_a,
        ctv_a,
    )
    assert response.status_code == 200, response.data
    assert response.data["pagination"]["total"] == 1
    assert response.data["data"][0]["id"] == group_id
    print("CTV LIST OWN GROUPS: PASS")
    response = call_detail(
        "get",
        pipeline_a,
        group_id,
        ctv_a,
    )
    assert response.status_code == 200
    print("CTV VIEW GROUP: PASS")
    response = call_detail(
        "patch",
        pipeline_a,
        group_id,
        ctv_a,
        {
            "name": "Group đã cập nhật",
            "is_enabled": False,
        },
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["is_enabled"] is False
    print("UPDATE GROUP: PASS")
    print("DISABLE GROUP: PASS")
    response = call_detail(
        "patch",
        pipeline_a,
        group_id,
        ctv_a,
        {"is_enabled": True},
    )
    assert response.status_code == 200
    assert response.data["data"]["is_enabled"] is True
    print("ENABLE GROUP: PASS")
    response = call_collection(
        "post",
        pipeline_a,
        ctv_a,
        payload,
    )
    assert response.status_code in (400, 409)
    print("DUPLICATE GROUP: BLOCKED")
    response = call_collection(
        "post",
        pipeline_b,
        ctv_a,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE CREATE: BLOCKED")
    response = call_detail(
        "get",
        pipeline_b,
        group_id,
        ctv_b,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE GROUP ACCESS: BLOCKED")
    response = call_detail(
        "patch",
        pipeline_a,
        group_id,
        ctv_a,
        {"pipeline": str(pipeline_b.pk)},
    )
    assert response.status_code == 400
    print("GROUP REASSIGNMENT: BLOCKED")
    response = call_detail(
        "patch",
        pipeline_a,
        group_id,
        ctv_a,
        {"verification_status": "verified"},
    )
    assert response.status_code == 400
    print("FAKE VERIFICATION: BLOCKED")
    response = call_collection(
        "get",
        pipeline_a,
        admin,
    )
    assert response.status_code == 200
    print("ADMIN ACCESS: PASS")
    response = call_collection(
        "get",
        pipeline_a,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    pipeline_a.status = "disabled"
    pipeline_a.save(update_fields=["status"])
    response = call_collection(
        "get",
        pipeline_a,
        ctv_a,
    )
    assert response.status_code == 403
    print("DISABLED PIPELINE: BLOCKED")
    transaction.set_rollback(True)
assert FacebookGroup.objects.count() == initial_count
print("DATABASE CHANGES: ROLLED BACK")
print("FACEBOOK GROUPS API: PASSED")
