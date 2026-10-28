"""Rollback-only Media Selection tests. NO Facebook or R2 network operations.

Do NOT use SQLite to evaluate cross-worker locking; production requires Neon
PostgreSQL and multi-process transaction tests in a later integration phase.
"""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone

from modules.albums.models import Album, AlbumImage
from modules.pipelines.models import Pipeline
from modules.publishing.models import (
    MediaAllocation,
    PipelineAlbumSource,
    PipelineMediaPolicy,
)
from modules.publishing.services.media_selection import (
    MediaSelectionError,
    MediaUnavailable,
    confirm_consumed,
    heartbeat_reserved,
    mark_publishing_started,
    release_reserved,
    reserve_media,
)

assert connection.vendor == "postgresql", "NEON PostgreSQL is required"
User = get_user_model()
suffix = uuid.uuid4().hex[:10]


def make_pipeline(label):
    user = User.objects.create_user(
        username=f"mediaengine_{label}_{suffix}",
        password=f"Test#{suffix}Aa1!",
    )
    return Pipeline.objects.create(
        name=f"Media Engine {label} {suffix}",
        ctv=user,
        status=Pipeline.Status.ACTIVE,
    )


def add_album(pipeline, label, images):
    album = Album.objects.create(pipeline=pipeline, name=f"{label}-{suffix}")
    records = []
    for order in range(1, images + 1):
        image_id = uuid.uuid4()
        records.append(AlbumImage.objects.create(
            id=image_id, album=album,
            original_filename=f"fixture-{order}.webp",
            storage_key=(
                f"pipeline-albums/{pipeline.pk}/{album.pk}/{image_id}.webp"
            ),
            mime_type="image/webp", file_size=1024,
            width=16, height=16,
            sha256="a" * 64, position=order,
            upload_status=AlbumImage.UploadStatus.READY,
        ))
    return album, records


def assert_raises(expected, func, **kwargs):
    try:
        func(**kwargs)
    except expected:
        return
    raise AssertionError(f"{expected.__name__} not raised")


with transaction.atomic():
    pipeline_a = make_pipeline("a")
    pipeline_b = make_pipeline("b")
    album_a, first_two = add_album(pipeline_a, "alpha", 2)
    album_b, last_one = add_album(pipeline_a, "beta", 1)
    album_foreign, foreign = add_album(pipeline_b, "foreign", 1)

    policy = PipelineMediaPolicy.objects.create(
        pipeline=pipeline_a, is_enabled=True,
        album_selection="in_order", image_selection="in_order",
        reuse_policy="no_repeat", images_per_post=2,
    )
    PipelineAlbumSource.objects.create(
        pipeline=pipeline_a, album=album_a, position=1,
    )
    PipelineAlbumSource.objects.create(
        pipeline=pipeline_a, album=album_b, position=2,
    )

    task_a = reserve_media(pipeline_id=pipeline_a.pk, request_key="task-a")
    assert task_a["state"] == "reserved"
    assert task_a["cycle_number"] == 1
    assert len(task_a["images"]) == 2
    assert [row["image_id"] for row in task_a["images"]] == [
        str(item.pk) for item in first_two
    ]
    assert all(row["album_id"] == str(album_a.pk) for row in task_a["images"])
    print("ORDERED ALBUM AND IMAGE SELECTION: PASS")

    again = reserve_media(pipeline_id=pipeline_a.pk, request_key="task-a")
    assert again["id"] == task_a["id"]
    assert again["images"] == task_a["images"]
    assert MediaAllocation.objects.filter(pipeline=pipeline_a).count() == 1
    print("IDEMPOTENT RESERVATION: PASS")

    assert_raises(MediaUnavailable, reserve_media,
                  pipeline_id=pipeline_a.pk, request_key="task-b")
    print("IN-FLIGHT DOUBLE-ALLOCATE: BLOCKED")

    renewed = heartbeat_reserved(pipeline_id=pipeline_a.pk, request_key="task-a")
    assert renewed["state"] == "reserved"
    assert renewed["last_heartbeat_at"]
    print("LEASE HEARTBEAT: PASS")

    released = release_reserved(pipeline_id=pipeline_a.pk, request_key="task-a")
    assert released["state"] == "released"
    assert release_reserved(pipeline_id=pipeline_a.pk, request_key="task-a")["id"] == task_a["id"]
    assert reserve_media(pipeline_id=pipeline_a.pk, request_key="task-a")["state"] == "released"
    print("RELEASE + PERMANENT IDEMPOTENCY KEY: PASS")

    task_b = reserve_media(pipeline_id=pipeline_a.pk, request_key="task-b")
    assert {row["image_id"] for row in task_b["images"]} == {
        str(image.pk) for image in first_two
    }
    assert_raises(MediaSelectionError, confirm_consumed,
                  pipeline_id=pipeline_a.pk, request_key="task-b")
    started = mark_publishing_started(pipeline_id=pipeline_a.pk, request_key="task-b")
    assert started["state"] == "uncertain"
    assert_raises(MediaSelectionError, release_reserved,
                  pipeline_id=pipeline_a.pk, request_key="task-b")
    assert_raises(MediaSelectionError, mark_publishing_started,
                  pipeline_id=pipeline_a.pk, request_key="task-b")
    assert_raises(MediaUnavailable, reserve_media,
                  pipeline_id=pipeline_a.pk, request_key="task-c")
    print("UNCERTAIN FAIL-CLOSED + NO BLIND RETRY: PASS")

    confirmed = confirm_consumed(pipeline_id=pipeline_a.pk, request_key="task-b")
    assert confirmed["state"] == "consumed" and confirmed["finalized_at"]
    assert confirm_consumed(pipeline_id=pipeline_a.pk, request_key="task-b")["id"] == task_b["id"]
    print("CONFIRM CONSUMED: PASS")

    assert_raises(MediaUnavailable, reserve_media,
                  pipeline_id=pipeline_a.pk, request_key="task-c")
    print("NO-REPEAT HISTORY: PASS")

    policy.images_per_post = 1
    policy.save()
    task_c = reserve_media(pipeline_id=pipeline_a.pk, request_key="task-c")
    assert [row["image_id"] for row in task_c["images"]] == [str(last_one[0].pk)]
    release_reserved(pipeline_id=pipeline_a.pk, request_key="task-c")
    print("FILL FROM LOWER-PRIORITY ALBUM: PASS")

    policy.reuse_policy = "cycle"
    policy.images_per_post = 2
    policy.save()
    # First cyclic allocation must still honor consumed history in cycle 1.
    # Only one unused image remains; a new cycle is opened atomically.
    task_cycle = reserve_media(pipeline_id=pipeline_a.pk, request_key="task-cycle")
    assert task_cycle["cycle_number"] == 2
    assert str(last_one[0].pk) in {x["image_id"] for x in task_cycle["images"]}
    assert len({x["image_id"] for x in task_cycle["images"]}) == 2
    assert all(x["image_id"] not in {str(f.pk) for f in foreign} for x in task_cycle["images"])
    print("CYCLE ADVANCE AND UNIQUE IMAGES PER JOB: PASS")

    # In-flight images from another cycle stay protected.
    assert_raises(MediaUnavailable, reserve_media,
                  pipeline_id=pipeline_a.pk, request_key="task-cycle-2")
    release_reserved(pipeline_id=pipeline_a.pk, request_key="task-cycle")
    print("NO CYCLE ADVANCE WHILE ACTIVE: PASS")

    policy.image_selection = "random"
    policy.album_selection = "random"
    policy.save()
    random_task = reserve_media(pipeline_id=pipeline_a.pk, request_key="task-random")
    assert len(random_task["images"]) == 2
    assert len({x["image_id"] for x in random_task["images"]}) == 2
    assert all(x["album_id"] in {str(album_a.pk), str(album_b.pk)} for x in random_task["images"])
    print("RANDOM ALBUM AND IMAGE MODES: PASS")
    release_reserved(pipeline_id=pipeline_a.pk, request_key="task-random")

    assert_raises(MediaSelectionError, reserve_media,
                  pipeline_id=pipeline_a.pk, request_key="../bad")
    print("INVALID REQUEST KEY: BLOCKED")

    PipelineMediaPolicy.objects.create(
        pipeline=pipeline_b, is_enabled=True,
        images_per_post=1, album_selection="in_order",
        image_selection="in_order", reuse_policy="no_repeat",
    )
    PipelineAlbumSource.objects.create(
        pipeline=pipeline_b, album=album_foreign, position=1,
    )
    foreign_task = reserve_media(pipeline_id=pipeline_b.pk, request_key="foreign-job")
    assert foreign_task["images"][0]["image_id"] == str(foreign[0].pk)
    assert foreign_task["images"][0]["image_id"] not in [
        x["image_id"] for x in task_a["images"]
    ]
    print("PIPELINE ISOLATION: PASS")

    MediaAllocation.objects.filter(pk=foreign_task["id"]).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert_raises(MediaSelectionError, heartbeat_reserved,
                  pipeline_id=pipeline_b.pk, request_key="foreign-job")
    assert MediaAllocation.objects.get(pk=foreign_task["id"]).state == "uncertain"
    assert_raises(MediaSelectionError, release_reserved,
                  pipeline_id=pipeline_b.pk, request_key="foreign-job")
    assert_raises(MediaSelectionError, mark_publishing_started,
                  pipeline_id=pipeline_b.pk, request_key="foreign-job")
    assert_raises(MediaUnavailable, reserve_media,
                  pipeline_id=pipeline_b.pk, request_key="foreign-job-2")
    print("EXPIRED LEASE GOES UNCERTAIN, NOT RELEASED: PASS")

    transaction.set_rollback(True)

print("DATABASE CHANGES: ROLLED BACK")
print("MEDIA SELECTION SERVICE: PASSED")
