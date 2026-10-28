from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.api.v1.ctv.session_views import AuthLandingAPIView
User = get_user_model()
admin = User.objects.filter(
    is_superuser=True,
    is_staff=True,
    is_active=True,
).first()
pipeline = Pipeline.objects.select_related("ctv").first()
assert admin is not None, "Super Admin not found"
assert pipeline is not None, "Pipeline not found"
ctv = pipeline.ctv
factory = APIRequestFactory()
view = AuthLandingAPIView.as_view()
def check(user=None):
    request = factory.get("/api/v1/auth/landing/")
    if user is not None:
        force_authenticate(request, user=user)
    return view(request)
with transaction.atomic():
    pipeline.status = "active"
    pipeline.save(update_fields=["status"])
    ctv.is_active = True
    ctv.save(update_fields=["is_active"])
    admin_response = check(admin)
    assert admin_response.status_code == 200
    assert admin_response.data["data"]["role"] == "admin"
    assert admin_response.data["data"]["redirect_to"] == "/"
    print("ADMIN -> DASHBOARD: PASS")
    ctv_response = check(ctv)
    assert ctv_response.status_code == 200
    assert ctv_response.data["data"]["role"] == "ctv"
    assert ctv_response.data["data"]["redirect_to"] == "/workspace/"
    assert (
        ctv_response.data["data"]["pipeline_id"]
        == str(pipeline.pk)
    )
    print("CTV -> WORKSPACE: PASS")
    print("PIPELINE BINDING: PASS")
    anonymous_response = check()
    assert anonymous_response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    pipeline.status = "disabled"
    pipeline.save(update_fields=["status"])
    assert check(ctv).status_code == 403
    print("DISABLED PIPELINE: BLOCKED")
    pipeline.status = "active"
    pipeline.save(update_fields=["status"])
    ctv.is_active = False
    ctv.save(update_fields=["is_active"])
    assert check(ctv).status_code == 403
    print("DISABLED CTV: BLOCKED")
    transaction.set_rollback(True)
print("DATABASE CHANGES: ROLLED BACK")
print("AUTH LANDING API: PASSED")
