from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.api.v1.facebook_accounts.list_views import (
    FacebookAccountListAPIView,
)
User = get_user_model()
admin = User.objects.filter(
    is_superuser=True,
    is_active=True,
).first()
assert admin is not None, "Super Admin not found"
factory = APIRequestFactory()
view = FacebookAccountListAPIView.as_view()
suffix = uuid4().hex[:10]
def create_pipeline(number):
    username = f"fb_list_{number}_{suffix}"
    ctv = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
        email=f"{username}@example.invalid",
    )
    pipeline = Pipeline.objects.create(
        name=f"FB List Test {number} {suffix}",
        ctv=ctv,
        status="active",
    )
    FacebookAccount.objects.create(
        pipeline=pipeline,
        label=f"Facebook {number}",
    )
    return pipeline, ctv
def get_list(pipeline, user=None):
    request = factory.get(
        f"/api/v1/pipelines/{pipeline.pk}/facebook-accounts/"
    )
    if user:
        force_authenticate(request, user=user)
    return view(request, pipeline_id=pipeline.pk)
with transaction.atomic():
    pipeline_a, ctv_a = create_pipeline("a")
    pipeline_b, ctv_b = create_pipeline("b")
    response = get_list(pipeline_a, admin)
    assert response.status_code == 200, response.data
    assert response.data["pagination"]["total"] == 1
    print("ADMIN LIST: PASS")
    response = get_list(pipeline_a, ctv_a)
    assert response.status_code == 200, response.data
    assert len(response.data["data"]) == 1
    print("CTV OWN PIPELINE: PASS")
    account = response.data["data"][0]
    assert account["label"] == "Facebook a"
    assert account["pipeline_id"] == str(pipeline_a.pk)
    assert "ciphertext" not in account
    assert "cookies" not in account
    assert "cookie_secret" not in account
    print("COOKIE SECRET NOT EXPOSED: PASS")
    response = get_list(pipeline_b, ctv_a)
    assert response.status_code == 404
    print("CROSS-PIPELINE ACCESS: BLOCKED")
    response = get_list(pipeline_b, ctv_b)
    assert response.status_code == 200
    assert response.data["data"][0]["label"] == "Facebook b"
    print("SECOND CTV ISOLATION: PASS")
    response = get_list(pipeline_a)
    assert response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    pipeline_a.status = "disabled"
    pipeline_a.save(update_fields=["status"])
    response = get_list(pipeline_a, ctv_a)
    assert response.status_code == 403
    print("DISABLED PIPELINE: BLOCKED")
    response = get_list(pipeline_a, admin)
    assert response.status_code == 200
    print("ADMIN CAN VIEW DISABLED PIPELINE: PASS")
    transaction.set_rollback(True)
print("DATABASE CHANGES: ROLLED BACK")
print("FACEBOOK ACCOUNT LIST API: PASSED")
