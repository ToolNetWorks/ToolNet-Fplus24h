import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.albums.models import Album, AlbumImage
from modules.pipelines.models import Pipeline
from modules.api.v1.albums.image_reorder_views import (
    AlbumImageReorderAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
view = AlbumImageReorderAPIView.as_view()
suffix = uuid.uuid4().hex[:10]
def make_pipeline(label):
    username = f"sort_{label}_{suffix}"
    user = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Sort Pipeline {label} {suffix}",
        ctv=user,
        status="active",
    )
    album = Album.objects.create(
        pipeline=pipeline,
        name=f"Album {label}",
    )
    return pipeline, album, user
def call(pipeline, album, data, user=None):
    request = factory.patch(
        f"/api/v1/pipelines/{pipeline.pk}/"
        f"albums/{album.pk}/images/reorder/",
        data,
        format="json",
    )
    if user is not None:
        force_authenticate(request, user=user)
    return view(
        request,
        pipeline_id=pipeline.pk,
        album_id=album.pk,
    )
def ordered(album):
    return list(
        AlbumImage.objects
        .filter(album=album)
        .order_by("position", "created_at", "id")
        .values_list("id", flat=True)
    )
initial_count = AlbumImage.objects.count()
with transaction.atomic():
    pipeline_a, album_a, ctv_a = make_pipeline("a")
    pipeline_b, album_b, ctv_b = make_pipeline("b")
    images = []
    for i in range(23):
        image = AlbumImage.objects.create(
            album=album_a,
            original_filename=f"image-{i}.webp",
            storage_key=(
                f"pipeline-albums/{pipeline_a.pk}/"
                f"{album_a.pk}/{uuid.uuid4()}.webp"
            ),
            mime_type="image/webp",
            file_size=100,
            width=32,
            height=32,
            sha256="a" * 64,
            position=i + 1,
            upload_status="ready",
        )
        images.append(image)
    response = call(
        pipeline_a,
        album_a,
        {
            "image_id": str(images[19].pk),
            "direction": "down",
        },
        ctv_a,
    )
    assert response.status_code == 200, response.data
    order = ordered(album_a)
    assert order[19] == images[20].pk
    assert order[20] == images[19].pk
    print("MOVE ACROSS PAGE BOUNDARY: PASS")
    response = call(
        pipeline_a,
        album_a,
        {
            "image_id": str(images[0].pk),
            "target_id": str(images[2].pk),
            "placement": "after",
        },
        ctv_a,
    )
    assert response.status_code == 200, response.data
    order = ordered(album_a)
    assert order[2] == images[0].pk
    print("DRAG AND DROP REORDER: PASS")
    response = call(
        pipeline_a,
        album_a,
        {
            "image_id": str(images[0].pk),
            "direction": "up",
        },
        ctv_b,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE REORDER: BLOCKED")
    response = call(
        pipeline_a,
        album_a,
        {
            "image_id": str(images[0].pk),
            "direction": "up",
        },
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS REORDER: BLOCKED")
    response = call(
        pipeline_a,
        album_a,
        {
            "image_id": str(images[0].pk),
            "target_id": str(uuid.uuid4()),
        },
        ctv_a,
    )
    assert response.status_code == 409
    print("UNKNOWN TARGET: BLOCKED")
    response = call(
        pipeline_a,
        album_a,
        {
            "image_id": str(images[0].pk),
            "direction": "up",
            "pipeline_id": str(pipeline_b.pk),
        },
        ctv_a,
    )
    assert response.status_code == 400
    print("FORBIDDEN FIELD: BLOCKED")
    positions = list(
        AlbumImage.objects
        .filter(album=album_a)
        .values_list("position", flat=True)
    )
    assert sorted(positions) == list(range(1, 24))
    print("POSITIONS NORMALIZED: PASS")
    transaction.set_rollback(True)
assert AlbumImage.objects.count() == initial_count
print("DATABASE CHANGES: ROLLED BACK")
print("ALBUM IMAGE REORDER API: PASSED")
