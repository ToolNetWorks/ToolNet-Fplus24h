from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.api.v1.pipelines.edit_views import (
    PipelineEditAPIView,
)
User = get_user_model()
admin = User.objects.filter(
    is_superuser=True,
    is_active=True,
).first()
pipeline = Pipeline.objects.select_related("ctv").first()
assert admin is not None, "Admin not found"
assert pipeline is not None, "Pipeline not found"
original_name = pipeline.name
original_username = pipeline.ctv.username
original_email = pipeline.ctv.email
original_ctv_id = pipeline.ctv_id
suffix = uuid4().hex[:12]
new_name = f"Pipeline Edit Test {suffix}"
new_username = f"ctv_test_{suffix}"
new_email = f"ctv_{suffix}@example.invalid"
factory = APIRequestFactory()
view = PipelineEditAPIView.as_view()
url = f"/api/v1/admin/pipelines/{pipeline.pk}/"
with transaction.atomic():
    request = factory.patch(
        url,
        {
            "name": new_name,
            "ctv_username": new_username,
            "ctv_email": new_email,
        },
        format="json",
    )
    force_authenticate(request, user=admin)
    response = view(
        request,
        pipeline_id=pipeline.pk,
    )
    assert response.status_code == 200, response.data
    pipeline.refresh_from_db()
    pipeline.ctv.refresh_from_db()
    assert pipeline.name == new_name
    assert pipeline.ctv.username == new_username
    assert pipeline.ctv.email == new_email
    print("UPDATE PIPELINE: PASS")
    print("UPDATE USERNAME: PASS")
    print("UPDATE EMAIL: PASS")
    assert pipeline.ctv_id == original_ctv_id
    print("PIPELINE-CTV RELATION: PRESERVED")
    invalid_request = factory.patch(
        url,
        {"ctv_id": admin.pk},
        format="json",
    )
    force_authenticate(invalid_request, user=admin)
    invalid_response = view(
        invalid_request,
        pipeline_id=pipeline.pk,
    )
    assert invalid_response.status_code == 400
    print("CTV REASSIGNMENT: BLOCKED")
    anonymous_request = factory.patch(
        url,
        {"name": "Unauthorized"},
        format="json",
    )
    anonymous_response = view(
        anonymous_request,
        pipeline_id=pipeline.pk,
    )
    assert anonymous_response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    transaction.set_rollback(True)
pipeline.refresh_from_db()
pipeline.ctv.refresh_from_db()
assert pipeline.name == original_name
assert pipeline.ctv.username == original_username
assert pipeline.ctv.email == original_email
print("DATABASE CHANGES: ROLLED BACK")
print("PIPELINE EDIT API: PASSED")
