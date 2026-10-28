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
from modules.api.v1.albums.image_delete_views import (
    AlbumImageDeleteAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
view = AlbumImageDeleteAPIView.as_view()
suffix = uuid.uuid4().hex[:10]
initial_count = AlbumImage.objects.count()
class FakeR2:
    def __init__(self):
        self.calls = 0
        self.fail = True
    def delete_object(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Simulated R2 failure")
        assert kwargs["Bucket"] == "test-bucket"
def make_pipeline(label):
    username = f"delete_{label}_{suffix}"
    user = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Delete Test {label} {suffix}",
        ctv=user,
        status="active",
    )
    album = Album.objects.create(
        name=f"Delete Album {label}",
        pipeline=pipeline,
    )
    return pipeline, album, user
def delete_request(pipeline, album, image, user=None):
    request = factory.delete(
        f"/api/v1/pipelines/{pipeline.pk}/"
        f"albums/{album.pk}/images/{image.pk}/"
    )
    if user is not None:
        force_authenticate(request, user=user)
    return view(
        request,
        pipeline_id=pipeline.pk,
        album_id=album.pk,
        image_id=image.pk,
    )
with transaction.atomic():
    pipeline_a, album_a, ctv_a = make_pipeline("a")
    pipeline_b, album_b, ctv_b = make_pipeline("b")
    image_id = uuid.uuid4()
    object_uuid = uuid.uuid4()
    image = AlbumImage.objects.create(
        id=image_id,
        album=album_a,
        original_filename="test.webp",
        storage_key=(
            f"pipeline-albums/{pipeline_a.pk}/"
            f"{album_a.pk}/{object_uuid}.webp"
        ),
        mime_type="image/webp",
        file_size=100,
        width=32,
        height=32,
        sha256="a" * 64,
        upload_status="ready",
    )
    fake = FakeR2()
    with patch(
        "modules.albums.services.delete_image.get_r2_client",
        return_value=(fake, "test-bucket"),
    ):
        response = delete_request(
            pipeline_a,
            album_a,
            image,
            ctv_b,
        )
        assert response.status_code == 404
        assert fake.calls == 0
        print("CROSS-PIPELINE DELETE: BLOCKED")
        response = delete_request(
            pipeline_a,
            album_a,
            image,
        )
        assert response.status_code in (401, 403)
        assert fake.calls == 0
        print("ANONYMOUS DELETE: BLOCKED")
        response = delete_request(
            pipeline_a,
            album_a,
            image,
            ctv_a,
        )
        assert response.status_code == 502
        assert fake.calls == 1
        image.refresh_from_db()
        assert image.upload_status == "deleting"
        print("R2 FAILURE: DETECTED")
        print("DELETING RECORD: RETAINED")
        fake.fail = False
        response = delete_request(
            pipeline_a,
            album_a,
            image,
            ctv_a,
        )
        assert response.status_code == 200
        assert response.data["success"] is True
        assert fake.calls == 2
        assert not AlbumImage.objects.filter(
            pk=image.pk
        ).exists()
        print("R2 RETRY: PASS")
        print("DATABASE RECORD REMOVED: PASS")
    transaction.set_rollback(True)
assert AlbumImage.objects.count() == initial_count
print("DATABASE CHANGES: ROLLED BACK")
print("IMAGE DELETION API: PASSED")
