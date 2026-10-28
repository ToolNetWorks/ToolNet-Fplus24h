from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.api.v1.pipelines.delete_views import (
    PipelineDetailAPIView,
)
User = get_user_model()
admin = User.objects.filter(
    is_superuser=True,
    is_active=True,
).first()
pipeline = Pipeline.objects.select_related("ctv").first()
assert admin is not None, "Admin not found"
assert pipeline is not None, "Pipeline not found"
factory = APIRequestFactory()
view = PipelineDetailAPIView.as_view()
url = f"/api/v1/admin/pipelines/{pipeline.pk}/"
request = factory.get(url)
force_authenticate(request, user=admin)
response = view(
    request,
    pipeline_id=pipeline.pk,
)
assert response.status_code == 200, response.data
preview = response.data["data"]
print("DELETE PREVIEW: PASS")
print("CAN DELETE:", preview["can_delete"])
print("BLOCKERS:", preview["blockers"])
anonymous = factory.delete(
    url,
    {
        "confirm_name": pipeline.name,
        "confirm_username": pipeline.ctv.username,
    },
    format="json",
)
response = view(
    anonymous,
    pipeline_id=pipeline.pk,
)
assert response.status_code in (401, 403)
print("ANONYMOUS: BLOCKED")
wrong_request = factory.delete(
    url,
    {
        "confirm_name": "WRONG PIPELINE",
        "confirm_username": pipeline.ctv.username,
    },
    format="json",
)
force_authenticate(wrong_request, user=admin)
response = view(
    wrong_request,
    pipeline_id=pipeline.pk,
)
assert response.status_code == 409
print("WRONG CONFIRMATION: BLOCKED")
with transaction.atomic():
    request = factory.delete(
        url,
        {
            "confirm_name": pipeline.name,
            "confirm_username": pipeline.ctv.username,
        },
        format="json",
    )
    force_authenticate(request, user=admin)
    response = view(
        request,
        pipeline_id=pipeline.pk,
    )
    if preview["can_delete"]:
        assert response.status_code == 200, response.data
        print("DELETE TRANSACTION: PASS")
    else:
        assert response.status_code == 409, response.data
        print("RELATED DATA: PROTECTED")
    transaction.set_rollback(True)
assert Pipeline.objects.filter(pk=pipeline.pk).exists()
assert User.objects.filter(pk=pipeline.ctv_id).exists()
print("PIPELINE: PRESERVED")
print("CTV: PRESERVED")
print("DATABASE CHANGES: ROLLED BACK")
print("PIPELINE DELETE API: PASSED")
