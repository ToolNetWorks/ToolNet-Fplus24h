from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.api.v1.pipelines.password_views import (
    CTVPasswordAPIView,
)
User = get_user_model()
admin = User.objects.filter(
    is_superuser=True,
    is_active=True,
).first()
pipeline = Pipeline.objects.select_related("ctv").first()
assert admin is not None, "Admin not found"
assert pipeline is not None, "Pipeline not found"
original_hash = pipeline.ctv.password
new_password = "ToolNetSecure#2026!"
factory = APIRequestFactory()
view = CTVPasswordAPIView.as_view()
url = (
    f"/api/v1/admin/pipelines/"
    f"{pipeline.pk}/ctv/password/"
)
with transaction.atomic():
    request = factory.post(
        url,
        {
            "new_password": new_password,
            "confirm_password": new_password,
        },
        format="json",
    )
    force_authenticate(request, user=admin)
    response = view(
        request,
        pipeline_id=pipeline.pk,
    )
    assert response.status_code == 200, response.data
    print("ADMIN CHANGE PASSWORD: PASS")
    pipeline.ctv.refresh_from_db()
    assert pipeline.ctv.check_password(new_password)
    assert pipeline.ctv.password != original_hash
    print("PASSWORD HASHED: PASS")
    # Người chưa đăng nhập không được thay đổi.
    request = factory.post(
        url,
        {
            "new_password": new_password,
            "confirm_password": new_password,
        },
        format="json",
    )
    response = view(
        request,
        pipeline_id=pipeline.pk,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    transaction.set_rollback(True)
pipeline.ctv.refresh_from_db()
assert pipeline.ctv.password == original_hash
print("ORIGINAL PASSWORD: PRESERVED")
print("CTV PASSWORD API: PASSED")
