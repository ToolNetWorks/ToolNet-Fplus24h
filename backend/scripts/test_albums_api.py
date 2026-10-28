from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.albums.models import Album
from modules.pipelines.models import Pipeline
from modules.api.v1.albums.views import (
    AlbumCollectionAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
view = AlbumCollectionAPIView.as_view()
admin = User.objects.filter(
    is_superuser=True,
    is_staff=True,
    is_active=True,
).first()
assert admin is not None, "Admin not found"
suffix = uuid4().hex[:10]
initial_count = Album.objects.count()
def make_pipeline(number):
    username = f"album_{number}_{suffix}"
    user = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
        email=f"{username}@example.invalid",
    )
    pipeline = Pipeline.objects.create(
        name=f"Album Pipeline {number} {suffix}",
        ctv=user,
        status="active",
    )
    return pipeline, user
def call(method, pipeline, user=None, data=None):
    url = f"/api/v1/pipelines/{pipeline.pk}/albums/"
    request = getattr(factory, method)(
        url,
        data=data,
        format="json",
    )
    if user is not None:
        force_authenticate(request, user=user)
    return view(
        request,
        pipeline_id=pipeline.pk,
    )
with transaction.atomic():
    pipeline_a, ctv_a = make_pipeline("a")
    pipeline_b, ctv_b = make_pipeline("b")
    response = call(
        "post",
        pipeline_a,
        ctv_a,
        {
            "name": "Album Marketing",
            "description": "Ảnh nội dung bài đăng",
        },
    )
    assert response.status_code == 201, response.data
    assert response.data["data"]["pipeline_id"] == str(
        pipeline_a.pk
    )
    print("CTV CREATE ALBUM: PASS")
    response = call("get", pipeline_a, ctv_a)
    assert response.status_code == 200, response.data
    assert response.data["pagination"]["total"] == 1
    assert response.data["data"][0]["image_count"] == 0
    print("CTV LIST OWN ALBUMS: PASS")
    response = call("get", pipeline_b, ctv_a)
    assert response.status_code == 404
    print("CROSS-PIPELINE LIST: BLOCKED")
    response = call(
        "post",
        pipeline_b,
        ctv_a,
        {"name": "Unauthorized"},
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE CREATE: BLOCKED")
    response = call("get", pipeline_a, admin)
    assert response.status_code == 200
    print("ADMIN ACCESS: PASS")
    response = call("get", pipeline_a)
    assert response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    pipeline_a.status = "disabled"
    pipeline_a.save(update_fields=["status"])
    response = call("get", pipeline_a, ctv_a)
    assert response.status_code == 403
    print("DISABLED PIPELINE: BLOCKED")
    transaction.set_rollback(True)
assert Album.objects.count() == initial_count
print("DATABASE CHANGES: ROLLED BACK")
print("ALBUM API TEST: PASSED")
