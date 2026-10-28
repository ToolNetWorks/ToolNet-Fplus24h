from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)

from modules.pipelines.models import Pipeline
from modules.api.v1.pipelines.status_views import (
    PipelineStatusAPIView,
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
view = PipelineStatusAPIView.as_view()
url = (
    f"/api/v1/admin/pipelines/"
    f"{pipeline.pk}/status/"
)


def change_status(new_status):
    request = factory.patch(
        url,
        {"status": new_status},
        format="json",
    )
    force_authenticate(request, user=admin)
    return view(
        request,
        pipeline_id=str(pipeline.pk),
    )


with transaction.atomic():
    response = change_status("disabled")
    assert response.status_code == 200, response.data
    pipeline.refresh_from_db()
    pipeline.ctv.refresh_from_db()
    assert pipeline.status == "disabled"
    assert pipeline.ctv.is_active is False
    print("LOCK PIPELINE: PASS")
    print("DISABLE CTV: PASS")

    response = change_status("active")
    assert response.status_code == 200, response.data
    pipeline.refresh_from_db()
    pipeline.ctv.refresh_from_db()
    assert pipeline.status == "active"
    assert pipeline.ctv.is_active is True
    print("UNLOCK PIPELINE: PASS")
    print("ENABLE CTV: PASS")

    response = change_status("invalid")
    assert response.status_code == 400
    print("INVALID STATUS: BLOCKED")

    anonymous = factory.patch(
        url,
        {"status": "disabled"},
        format="json",
    )
    response = view(
        anonymous,
        pipeline_id=str(pipeline.pk),
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")

    transaction.set_rollback(True)

print("DATABASE CHANGES: ROLLED BACK")
print("PIPELINE STATUS API: PASSED")
