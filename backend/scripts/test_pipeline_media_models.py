import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from modules.pipelines.models import Pipeline
from modules.albums.models import Album
from modules.publishing.models import (
    PipelineMediaPolicy,
    PipelineAlbumSource,
)

User = get_user_model()
suffix = uuid.uuid4().hex[:10]
initial_policies = PipelineMediaPolicy.objects.count()
initial_sources = PipelineAlbumSource.objects.count()


def create_pipeline(label):
    username = f"media_{label}_{suffix}"
    ctv = User.objects.create_user(
        username=username,
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Media Test {label} {suffix}",
        ctv=ctv,
        status=Pipeline.Status.ACTIVE,
    )
    album = Album.objects.create(
        pipeline=pipeline,
        name=f"Album {label}",
    )
    return pipeline, album, ctv


with transaction.atomic():
    pipeline_a, album_a, ctv_a = create_pipeline("a")
    pipeline_b, album_b, ctv_b = create_pipeline("b")
    policy = PipelineMediaPolicy.objects.create(
        pipeline=pipeline_a,
        is_enabled=True,
        album_selection="in_order",
        image_selection="random",
        reuse_policy="no_repeat",
        images_per_post=3,
    )
    assert policy.pipeline_id == pipeline_a.pk
    assert policy.images_per_post == 3
    print("CREATE MEDIA POLICY: PASS")

    source = PipelineAlbumSource.objects.create(
        pipeline=pipeline_a,
        album=album_a,
        position=1,
        is_enabled=True,
    )
    assert source.album.pipeline_id == pipeline_a.pk
    print("CONNECT ALBUM TO PIPELINE: PASS")

    try:
        PipelineAlbumSource.objects.create(
            pipeline=pipeline_a,
            album=album_b,
            position=2,
        )
    except ValidationError:
        print("CROSS-PIPELINE ALBUM: BLOCKED")
    else:
        raise AssertionError(
            "Cross-Pipeline album was accepted"
        )

    try:
        PipelineAlbumSource.objects.create(
            pipeline=pipeline_a,
            album=album_a,
            position=2,
        )
    except ValidationError:
        print("DUPLICATE ALBUM: BLOCKED")
    else:
        raise AssertionError(
            "Duplicate album source was accepted"
        )

    second_album = Album.objects.create(
        pipeline=pipeline_a,
        name="Second Album",
    )
    try:
        PipelineAlbumSource.objects.create(
            pipeline=pipeline_a,
            album=second_album,
            position=1,
        )
    except ValidationError:
        print("DUPLICATE POSITION: BLOCKED")
    else:
        raise AssertionError(
            "Duplicate position was accepted"
        )

    policy.images_per_post = 11
    try:
        policy.full_clean()
    except ValidationError:
        print("IMAGE COUNT LIMIT: ENFORCED")
    else:
        raise AssertionError(
            "Invalid image count was accepted"
        )
    policy.refresh_from_db()
    assert policy.images_per_post == 3
    transaction.set_rollback(True)

assert (
    PipelineMediaPolicy.objects.count()
    == initial_policies
)
assert (
    PipelineAlbumSource.objects.count()
    == initial_sources
)
print("DATABASE CHANGES: ROLLED BACK")
print("PIPELINE MEDIA MODELS: PASSED")
