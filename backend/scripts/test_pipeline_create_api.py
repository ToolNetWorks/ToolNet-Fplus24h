from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)

from modules.api.v1.pipelines.views import (
    PipelineCreateAPIView,
)
from modules.pipelines.models import Pipeline

admin = get_user_model().objects.filter(
    is_superuser=True,
    is_active=True,
).first()

if admin is None:
    raise SystemExit("ERROR: Admin not found")

username = f"test_{uuid4().hex[:12]}"
pipeline_name = f"Pipeline {username}"

factory = APIRequestFactory()

with transaction.atomic():
    request = factory.post(
        "/api/v1/admin/pipelines/",
        {
            "name": pipeline_name,
            "status": "active",
            "ctv_username": username,
            "ctv_email": f"{username}@example.test",
            "ctv_password": "SecureTest#2026!",
            "ctv_password_confirm": "SecureTest#2026!",
        },
        format="json",
    )

    force_authenticate(request, user=admin)
    response = PipelineCreateAPIView.as_view()(
        request
    )

    print("CREATE HTTP:", response.status_code)

    if response.status_code != 201:
        print("ERROR:", response.data)
        raise RuntimeError("Pipeline creation failed")

    pipeline = Pipeline.objects.get(
        name=pipeline_name
    )

    assert pipeline.ctv.username == username
    assert pipeline.ctv.check_password(
        "SecureTest#2026!"
    )
    assert not pipeline.ctv.is_staff
    assert not pipeline.ctv.is_superuser

    print("PIPELINE CREATED: PASS")
    print("CTV ACCOUNT CREATED: PASS")
    print("PASSWORD HASHED: PASS")
    print("RELATION 1:1: PASS")

    transaction.set_rollback(True)

print("TEST DATA ROLLED BACK: PASS")
print("PIPELINE CREATE API: PASSED")
