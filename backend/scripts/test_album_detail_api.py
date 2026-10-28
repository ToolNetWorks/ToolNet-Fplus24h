from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.albums.models import Album
from modules.pipelines.models import Pipeline
from modules.api.v1.albums.detail_views import (
    AlbumDetailAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
view = AlbumDetailAPIView.as_view()
admin = User.objects.filter(
    is_superuser=True,
    is_staff=True,
    is_active=True,
).first()
assert admin is not None, "Super Admin not found"
suffix = uuid4().hex[:10]
initial_count = Album.objects.count()
def make_pipeline(number):
    username = f"album_detail_{number}_{suffix}"
    ctv = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
        email=f"{username}@example.invalid",
    )
    pipeline = Pipeline.objects.create(
        name=f"Album Detail Test {number} {suffix}",
        ctv=ctv,
        status="active",
    )
    return pipeline, ctv
def call(method, pipeline, album_id, user=None, data=None):
    url = (
        f"/api/v1/pipelines/{pipeline.pk}/"
        f"albums/{album_id}/"
    )
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
        album_id=album_id,
    )
with transaction.atomic():
    pipeline_a, ctv_a = make_pipeline("a")
    pipeline_b, ctv_b = make_pipeline("b")
    album = Album.objects.create(
        pipeline=pipeline_a,
        name="Album Marketing",
    )
    response = call(
        "get",
        pipeline_a,
        album.pk,
        ctv_a,
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["image_count"] == 0
    print("CTV VIEW OWN ALBUM: PASS")
    response = call(
        "patch",
        pipeline_a,
        album.pk,
        ctv_a,
        {
            "name": "Album đã chỉnh sửa",
            "description": "Thư viện hình ảnh",
            "is_enabled": False,
        },
    )
    assert response.status_code == 200, response.data
    album.refresh_from_db()
    assert album.name == "Album đã chỉnh sửa"
    assert album.description == "Thư viện hình ảnh"
    assert album.is_enabled is False
    assert album.pipeline_id == pipeline_a.pk
    print("UPDATE ALBUM: PASS")
    print("DISABLE ALBUM: PASS")
    print("PIPELINE OWNERSHIP: PRESERVED")
    response = call(
        "patch",
        pipeline_a,
        album.pk,
        ctv_a,
        {"is_enabled": True},
    )
    assert response.status_code == 200
    assert response.data["data"]["is_enabled"] is True
    print("ENABLE ALBUM: PASS")
    response = call(
        "patch",
        pipeline_a,
        album.pk,
        ctv_a,
        {"pipeline": str(pipeline_b.pk)},
    )
    assert response.status_code == 400
    print("ALBUM REASSIGNMENT: BLOCKED")
    response = call(
        "patch",
        pipeline_a,
        album.pk,
        ctv_a,
        {"storage_key": "unauthorized"},
    )
    assert response.status_code == 400
    print("STORAGE METADATA EDIT: BLOCKED")
    response = call(
        "get",
        pipeline_a,
        album.pk,
        ctv_b,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE ACCESS: BLOCKED")
    response = call(
        "patch",
        pipeline_a,
        album.pk,
        ctv_b,
        {"name": "Unauthorized"},
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE EDIT: BLOCKED")
    response = call(
        "get",
        pipeline_a,
        album.pk,
        admin,
    )
    assert response.status_code == 200
    print("ADMIN ACCESS: PASS")
    response = call(
        "get",
        pipeline_a,
        album.pk,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    pipeline_a.status = "disabled"
    pipeline_a.save(update_fields=["status"])
    response = call(
        "get",
        pipeline_a,
        album.pk,
        ctv_a,
    )
    assert response.status_code == 403
    print("DISABLED PIPELINE: BLOCKED")
    transaction.set_rollback(True)
assert Album.objects.count() == initial_count
print("DATABASE CHANGES: ROLLED BACK")
print("ALBUM DETAIL API: PASSED")
