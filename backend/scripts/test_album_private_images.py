import hashlib
import io
import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.albums.models import Album, AlbumImage
from modules.api.v1.albums.image_list_views import (
    AlbumImageCollectionAPIView,
)
from modules.api.v1.albums.image_content_views import (
    AlbumImageContentAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
list_view = AlbumImageCollectionAPIView.as_view()
content_view = AlbumImageContentAPIView.as_view()
suffix = uuid.uuid4().hex[:10]
original_count = AlbumImage.objects.count()
def make_pipeline(label):
    username = f"img_{label}_{suffix}"
    ctv = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Image Test {label} {suffix}",
        ctv=ctv,
        status="active",
    )
    album = Album.objects.create(
        pipeline=pipeline,
        name=f"Album {label}",
    )
    return pipeline, album, ctv
def call(view, pipeline, album, user=None, image_id=None):
    url = (
        f"/api/v1/pipelines/{pipeline.pk}/"
        f"albums/{album.pk}/images/"
    )
    if image_id:
        url += f"{image_id}/content/"
    request = factory.get(url)
    if user is not None:
        force_authenticate(request, user=user)
    kwargs = {
        "pipeline_id": pipeline.pk,
        "album_id": album.pk,
    }
    if image_id:
        kwargs["image_id"] = image_id
    return view(request, **kwargs)
class FakeR2:
    def __init__(self, data):
        self.data = data
    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.data)}
with transaction.atomic():
    pipeline_a, album_a, ctv_a = make_pipeline("a")
    pipeline_b, album_b, ctv_b = make_pipeline("b")
    data = b"TEST_PRIVATE_IMAGE_BYTES"
    digest = hashlib.sha256(data).hexdigest()
    image_id = uuid.uuid4()
    record = AlbumImage.objects.create(
        id=image_id,
        album=album_a,
        original_filename="sample.webp",
        storage_key=(
            f"pipeline-albums/{pipeline_a.pk}/"
            f"{album_a.pk}/{image_id}.webp"
        ),
        mime_type="image/webp",
        file_size=len(data),
        width=32,
        height=32,
        sha256=digest,
        upload_status="ready",
    )
    response = call(
        list_view,
        pipeline_a,
        album_a,
        ctv_a,
    )
    assert response.status_code == 200, response.data
    assert response.data["pagination"]["total"] == 1
    item = response.data["data"][0]
    assert "storage_key" not in item
    assert "sha256" not in item
    assert "ciphertext" not in item
    assert item["content_url"].endswith(
        f"/images/{record.pk}/content/"
    )
    print("PRIVATE IMAGE LIST: PASS")
    print("STORAGE KEY NOT EXPOSED: PASS")
    response = call(
        list_view,
        pipeline_a,
        album_a,
        ctv_b,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE LIST: BLOCKED")
    response = call(
        content_view,
        pipeline_a,
        album_a,
        ctv_b,
        image_id=record.pk,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE IMAGE: BLOCKED")
    with patch(
        "modules.api.v1.albums.image_content_views.get_r2_client",
        return_value=(FakeR2(data), "test-bucket"),
    ):
        response = call(
            content_view,
            pipeline_a,
            album_a,
            ctv_a,
            image_id=record.pk,
        )
    assert response.status_code == 200
    assert response.content == data
    assert response["Content-Type"] == "image/webp"
    assert response["Cache-Control"] == "private, no-store"
    print("AUTHORIZED IMAGE READ: PASS")
    print("IMAGE INTEGRITY: PASS")
    with patch(
        "modules.api.v1.albums.image_content_views.get_r2_client",
        return_value=(FakeR2(b"TAMPERED"), "test-bucket"),
    ):
        response = call(
            content_view,
            pipeline_a,
            album_a,
            ctv_a,
            image_id=record.pk,
        )
    assert response.status_code == 502
    print("TAMPERED IMAGE: BLOCKED")
    response = call(
        list_view,
        pipeline_a,
        album_a,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS: BLOCKED")
    transaction.set_rollback(True)
assert AlbumImage.objects.count() == original_count
print("DATABASE CHANGES: ROLLED BACK")
print("PRIVATE ALBUM IMAGE API: PASSED")
