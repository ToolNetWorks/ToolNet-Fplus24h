"""DB transaction rollback tests only; does not call Facebook or R2."""
import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from modules.albums.models import Album, AlbumImage
from modules.albums.services.delete_image import (
    ImageDeletionConflict, delete_album_image,
)
from modules.pipelines.models import Pipeline
from modules.publishing.models import MediaAllocation, MediaAllocationItem

User = get_user_model()
suffix = uuid.uuid4().hex[:10]


def sample_pipeline(tag):
    user = User.objects.create_user(
        username=f"mediaalloc_{tag}_{suffix}",
        password=f"Test#{suffix}Aa1!",
    )
    return Pipeline.objects.create(
        name=f"Allocation Test {tag} {suffix}", ctv=user,
        status=Pipeline.Status.ACTIVE,
    )


def sample_image(album):
    image_id = uuid.uuid4()
    return AlbumImage.objects.create(
        id=image_id, album=album,
        original_filename="test.webp",
        storage_key=(
            f"pipeline-albums/{album.pipeline_id}/{album.pk}/{image_id}.webp"
        ),
        mime_type="image/webp", file_size=1024,
        width=20, height=20, sha256="a" * 64,
        position=1, upload_status=AlbumImage.UploadStatus.READY,
    )


with transaction.atomic():
    pipeline_a, pipeline_b = sample_pipeline('a'), sample_pipeline('b')
    album_a = Album.objects.create(pipeline=pipeline_a, name="Source A")
    album_b = Album.objects.create(pipeline=pipeline_b, name="Source B")
    image_a = sample_image(album_a)
    image_b = sample_image(album_b)

    alloc = MediaAllocation.objects.create(
        pipeline=pipeline_a,
        request_key=f"job-{suffix}",
        images_requested=1,
        state=MediaAllocation.State.RESERVED,
        lease_expires_at=timezone.now() + timedelta(minutes=10),
        policy_snapshot={"image_selection": "in_order"},
    )
    item = MediaAllocationItem.objects.create(
        allocation=alloc, image=image_a,
        image_uuid=image_a.pk, album_uuid=album_a.pk, position=1,
    )
    assert item.image_id == image_a.pk
    print("MEDIA ALLOCATION + IMAGE: PASS")

    try:
        MediaAllocation.objects.create(
            pipeline=pipeline_a, request_key=f"job-{suffix}",
            images_requested=1,
            lease_expires_at=timezone.now() + timedelta(minutes=10),
        )
    except ValidationError:
        print("IDEMPOTENCY KEY: UNIQUE PER PIPELINE")
    else:
        raise AssertionError("Duplicate idempotency key accepted")

    try:
        MediaAllocationItem.objects.create(
            allocation=alloc, image=image_b,
            image_uuid=image_b.pk, album_uuid=album_b.pk, position=2,
        )
    except ValidationError:
        print("CROSS-PIPELINE IMAGE: BLOCKED")
    else:
        raise AssertionError("Foreign image accepted")

    try:
        delete_album_image(
            pipeline_id=pipeline_a.pk,
            album_id=album_a.pk,
            image_id=image_a.pk,
        )
    except ImageDeletionConflict:
        print("RESERVED IMAGE R2 DELETE: BLOCKED")
    else:
        raise AssertionError("Reserved image deletion was accepted")

    alloc.state = MediaAllocation.State.UNCERTAIN
    alloc.save()
    try:
        delete_album_image(
            pipeline_id=pipeline_a.pk,
            album_id=album_a.pk,
            image_id=image_a.pk,
        )
    except ImageDeletionConflict:
        print("UNCERTAIN IMAGE R2 DELETE: BLOCKED")
    else:
        raise AssertionError("Uncertain image deletion was accepted")

    alloc.state = MediaAllocation.State.CONSUMED
    alloc.finalized_at = timezone.now()
    alloc.save()
    # The model-level deletion below deliberately avoids all R2 calls.
    saved_image_a_id = image_a.pk
    image_a.delete()
    item.refresh_from_db()
    assert item.image_id is None
    assert item.image_uuid == saved_image_a_id
    assert item.album_uuid == album_a.pk
    print("USAGE HISTORY AFTER IMAGE DELETION: PRESERVED")

    transaction.set_rollback(True)

print("ALL TEST DATA: ROLLED BACK")
print("MEDIA ALLOCATION SCHEMA TEST: PASSED")
