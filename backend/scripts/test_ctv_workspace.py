from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.api.v1.ctv.workspace_views import (
    CTVWorkspaceAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
view = CTVWorkspaceAPIView.as_view()
pipeline = Pipeline.objects.select_related("ctv").first()
admin = User.objects.filter(
    is_superuser=True,
    is_active=True,
).first()
assert pipeline is not None, "Pipeline not found"
assert admin is not None, "Admin not found"
ctv = pipeline.ctv
def call_api(user=None):
    request = factory.get("/api/v1/ctv/workspace/")
    if user is not None:
        force_authenticate(request, user=user)
    return view(request)
with transaction.atomic():
    pipeline.status = Pipeline.Status.ACTIVE
    pipeline.save(update_fields=["status"])
    ctv.is_active = True
    ctv.save(update_fields=["is_active"])
    response = call_api(ctv)
    assert response.status_code == 200, response.data
    assert response.data["success"] is True
    data = response.data["data"]
    assert data["pipeline"]["id"] == str(pipeline.pk)
    assert data["ctv"]["id"] == ctv.pk
    assert isinstance(
        data["stats"]["facebook_accounts"],
        int,
    )
    assert "cookies" not in str(response.data)
    assert "ciphertext" not in str(response.data)
    print("CTV OWN WORKSPACE: PASS")
    print("PIPELINE OWNERSHIP: PASS")
    print("FACEBOOK STATISTICS: PASS")
    print("COOKIE SECRET NOT EXPOSED: PASS")
    response = call_api(admin)
    assert response.status_code == 403
    print("ADMIN CANNOT USE CTV WORKSPACE: PASS")
    response = call_api()
    assert response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    pipeline.status = Pipeline.Status.DISABLED
    pipeline.save(update_fields=["status"])
    response = call_api(ctv)
    assert response.status_code == 403
    print("DISABLED PIPELINE: BLOCKED")
    pipeline.status = Pipeline.Status.ACTIVE
    pipeline.save(update_fields=["status"])
    ctv.is_active = False
    ctv.save(update_fields=["is_active"])
    response = call_api(ctv)
    assert response.status_code == 403
    print("DISABLED CTV: BLOCKED")
    transaction.set_rollback(True)
print("DATABASE CHANGES: ROLLED BACK")
print("CTV WORKSPACE API: PASSED")
