"""Database-backed image reservations for the future publisher.

Only privileged backend workers should call this service after verifying the
calling job's pipeline. No Facebook, R2, network I/O or public endpoints here.

Lock order for modifications: Pipeline -> Album(s) -> Allocation / Image.
The Pipeline row lock serializes reservations, policy updates, and cycle changes.
The Album locks coordinate with upload/delete to avoid R2 deletion races.
"""

import re
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, Max, OuterRef
from django.utils import timezone

from modules.albums.models import Album, AlbumImage
from modules.pipelines.models import Pipeline
from modules.publishing.models import (
    MediaAllocation,
    MediaAllocationItem,
    PipelineAlbumSource,
    PipelineMediaPolicy,
)


DEFAULT_LEASE_SECONDS = 600
MAX_LEASE_SECONDS = 3600
ALLOWED_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ACTIVE_STATES = (
    MediaAllocation.State.RESERVED,
    MediaAllocation.State.UNCERTAIN,
)


class MediaSelectionError(Exception):
    """Invalid request or transition; caller should not retry unchanged."""


class MediaUnavailable(MediaSelectionError):
    """Cannot fulfill this reservation with current media/policy/state."""


def _key(value):
    if not isinstance(value, str) or not ALLOWED_KEY.fullmatch(value):
        raise MediaSelectionError("request_key phải dài 1–128 ký tự an toàn.")
    return value


def _lease(value):
    if type(value) is not int or not 60 <= value <= MAX_LEASE_SECONDS:
        raise MediaSelectionError("lease_seconds phải từ 60 đến 3600.")
    return value


def _pipeline(pipeline_id):
    # Never lock allocations before taking this lock.
    pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline_id).first()
    if pipeline is None:
        raise MediaSelectionError("Pipeline không tồn tại.")
    return pipeline


def _allocation(pipeline_id, request_key):
    allocation = (
        MediaAllocation.objects.select_for_update()
        .filter(pipeline_id=pipeline_id, request_key=request_key)
        .first()
    )
    if allocation is None:
        raise MediaSelectionError("Không tìm thấy tác vụ cấp phát.")
    return allocation


def _expire_reservations(pipeline_id, now):
    # Conservative fail-closed behavior: never release an expired lease.
    # The publisher must verify whether a post was made before reconciliation.
    return (
        MediaAllocation.objects.filter(
            pipeline_id=pipeline_id,
            state=MediaAllocation.State.RESERVED,
            lease_expires_at__lte=now,
        ).update(state=MediaAllocation.State.UNCERTAIN, updated_at=now)
    )


def allocation_payload(allocation):
    """Snapshot identifiers only; never expose R2 storage keys or credentials."""
    items = list(
        allocation.items.order_by("position", "id")
        .values("image_uuid", "album_uuid", "position")
    )
    return {
        "id": str(allocation.pk),
        "pipeline_id": str(allocation.pipeline_id),
        "request_key": allocation.request_key,
        "state": allocation.state,
        "images_requested": allocation.images_requested,
        "cycle_number": allocation.cycle_number,
        "policy_version": allocation.policy_version,
        "policy_snapshot": allocation.policy_snapshot,
        "lease_expires_at": allocation.lease_expires_at.isoformat(),
        "last_heartbeat_at": (
            allocation.last_heartbeat_at.isoformat()
            if allocation.last_heartbeat_at else None
        ),
        "finalized_at": (
            allocation.finalized_at.isoformat() if allocation.finalized_at else None
        ),
        "images": [
            {
                "image_id": str(row["image_uuid"]),
                "album_id": str(row["album_uuid"]),
                "position": row["position"],
            }
            for row in items
        ],
    }


def _ordered_candidates(pipeline_id, album_id, *, cycle_number, reuse_policy):
    """Return an indexed, lazily evaluated queryset of eligible ready images."""
    used_states = [MediaAllocation.State.CONSUMED]
    if reuse_policy == PipelineMediaPolicy.ReusePolicy.NO_REPEAT:
        consumed = MediaAllocationItem.objects.filter(
            image_uuid=OuterRef("pk"),
            allocation__pipeline_id=pipeline_id,
            allocation__state__in=used_states,
        )
    else:
        consumed = MediaAllocationItem.objects.filter(
            image_uuid=OuterRef("pk"),
            allocation__pipeline_id=pipeline_id,
            allocation__state__in=used_states,
            allocation__cycle_number=cycle_number,
        )

    in_flight = MediaAllocationItem.objects.filter(
        image_uuid=OuterRef("pk"),
        allocation__pipeline_id=pipeline_id,
        allocation__state__in=ACTIVE_STATES,
    )
    return (
        AlbumImage.objects.filter(
            album_id=album_id,
            album__pipeline_id=pipeline_id,
            upload_status=AlbumImage.UploadStatus.READY,
        )
        .annotate(_in_flight=Exists(in_flight), _consumed=Exists(consumed))
        .filter(_in_flight=False, _consumed=False)
        .order_by("position", "created_at", "pk")
    )


def _choose_images(pipeline_id, sources, cycle, policy, quantity, exclude_ids=None):
    """Choose without replacement; random selection uses bounded-memory sampling."""
    exclude_ids = set(exclude_ids or ())
    sources = list(sources)
    if policy.album_selection == PipelineMediaPolicy.SelectionMode.RANDOM:
        secrets.SystemRandom().shuffle(sources)

    chosen = []
    for source in sources:
        remaining = quantity - len(chosen)
        if remaining <= 0:
            break
        queryset = _ordered_candidates(
            pipeline_id, source.album_id,
            cycle_number=cycle, reuse_policy=policy.reuse_policy,
        )
        if exclude_ids:
            queryset = queryset.exclude(pk__in=exclude_ids)
        if policy.image_selection == PipelineMediaPolicy.SelectionMode.IN_ORDER:
            selected = list(queryset[:remaining])
        else:
            # Reservoir sampling is uniform within the source Album, without
            # loading potentially thousands of image records into memory.
            selected = []
            for index, image in enumerate(queryset.iterator(chunk_size=512)):
                if index < remaining:
                    selected.append(image)
                else:
                    candidate_index = secrets.randbelow(index + 1)
                    if candidate_index < remaining:
                        selected[candidate_index] = image
            secrets.SystemRandom().shuffle(selected)
        chosen.extend(selected)
    return chosen


@transaction.atomic
def expire_stale_reservations(*, pipeline_id):
    """Persist fail-closed expiry transitions in their OWN transaction.

    Do not call this inside another transaction that may later be rolled back.
    """
    pipeline = _pipeline(pipeline_id)
    return _expire_reservations(pipeline.pk, timezone.now())


def reserve_media(*, pipeline_id, request_key, lease_seconds=DEFAULT_LEASE_SECONDS):
    request_key = _key(request_key)
    lease_seconds = _lease(lease_seconds)
    expire_stale_reservations(pipeline_id=pipeline_id)
    return _reserve_media_tx(
        pipeline_id=pipeline_id, request_key=request_key,
        lease_seconds=lease_seconds,
    )


@transaction.atomic
def _reserve_media_tx(*, pipeline_id, request_key, lease_seconds):
    """Idempotently reserve exactly policy.images_per_post images.

    An existing request_key returns the original allocation even if settings
    changed, including when it has been released/consumed. Keys must never be
    reused for a different publishing job.
    """
    request_key = _key(request_key)
    lease_seconds = _lease(lease_seconds)
    now = timezone.now()
    pipeline = _pipeline(pipeline_id)
    _expire_reservations(pipeline.pk, now)

    existing = MediaAllocation.objects.filter(
        pipeline_id=pipeline.pk, request_key=request_key,
    ).first()
    if existing is not None:
        if (existing.state == MediaAllocation.State.RESERVED and
                existing.lease_expires_at <= now):
            existing.state = MediaAllocation.State.UNCERTAIN
            existing.save(update_fields=["state", "updated_at"])
        return allocation_payload(existing)

    if pipeline.status != Pipeline.Status.ACTIVE:
        raise MediaUnavailable("Pipeline đang bị khóa.")

    policy = PipelineMediaPolicy.objects.filter(pipeline_id=pipeline.pk).first()
    if policy is None or not policy.is_enabled:
        raise MediaUnavailable("Nguồn ảnh của Pipeline chưa được bật.")
    quantity = policy.images_per_post
    if not 1 <= quantity <= 10:
        raise MediaSelectionError("Số ảnh mỗi bài không hợp lệ.")

    sources = list(
        PipelineAlbumSource.objects.filter(
            pipeline_id=pipeline.pk, is_enabled=True, album__is_enabled=True
        ).select_related("album").order_by("position", "pk")
    )
    if not sources:
        raise MediaUnavailable("Không có Album nguồn đang bật.")

    # All selected albums are locked in canonical order BEFORE reading images.
    # Image deletion locks the album first; this prevents selection/deletion races.
    ids = [row.album_id for row in sources]
    locked_albums = list(
        Album.objects.select_for_update()
        .filter(pk__in=ids, pipeline_id=pipeline.pk, is_enabled=True)
        .order_by("pk")
    )
    if len(locked_albums) != len(ids):
        raise MediaUnavailable("Album nguồn đang thay đổi, hãy thử lại.")

    current_cycle = (
        MediaAllocation.objects.filter(pipeline_id=pipeline.pk)
        .aggregate(highest=Max("cycle_number"))["highest"] or 1
    )
    if current_cycle >= 2147483647:
        raise MediaSelectionError("Số vòng sử dụng ảnh đã đạt giới hạn.")

    images = _choose_images(pipeline.pk, sources, current_cycle, policy, quantity)
    cycle = current_cycle
    if len(images) < quantity:
        if policy.reuse_policy == PipelineMediaPolicy.ReusePolicy.NO_REPEAT:
            raise MediaUnavailable("Không còn đủ ảnh chưa từng sử dụng.")
        # Never roll a cycle while earlier jobs still have in-flight images.
        in_flight = MediaAllocation.objects.filter(
            pipeline_id=pipeline.pk, state__in=ACTIVE_STATES,
        ).exists()
        if in_flight:
            raise MediaUnavailable("Chưa đủ ảnh; còn tác vụ chờ hoàn tất/đối soát.")
        cycle = current_cycle + 1
        # Carry forward never-used images from the old cycle FIRST.
        # Otherwise a high-priority album with >= quantity images could
        # starve lower-priority albums forever at every cycle rollover.
        supplemental = _choose_images(
            pipeline.pk, sources, cycle, policy, quantity - len(images),
            exclude_ids={image.pk for image in images},
        )
        images.extend(supplemental)
        if len(images) < quantity:
            raise MediaUnavailable("Không đủ ảnh READY để bắt đầu vòng mới.")

    snapshot = {
        "album_selection": policy.album_selection,
        "image_selection": policy.image_selection,
        "reuse_policy": policy.reuse_policy,
        "images_per_post": quantity,
        "source_album_ids": [str(source.album_id) for source in sources],
    }

    allocation = MediaAllocation.objects.create(
        pipeline=pipeline,
        request_key=request_key,
        images_requested=quantity,
        cycle_number=cycle,
        policy_snapshot=snapshot,
        policy_version=policy.updated_at.isoformat(),
        state=MediaAllocation.State.RESERVED,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        last_heartbeat_at=now,
    )
    for position, image in enumerate(images, start=1):
        MediaAllocationItem.objects.create(
            allocation=allocation,
            image=image,
            image_uuid=image.pk,
            album_uuid=image.album_id,
            position=position,
        )
    return allocation_payload(allocation)


def heartbeat_reserved(*, pipeline_id, request_key, lease_seconds=DEFAULT_LEASE_SECONDS):
    request_key = _key(request_key)
    lease_seconds = _lease(lease_seconds)
    expire_stale_reservations(pipeline_id=pipeline_id)
    result, error = _heartbeat_tx(
        pipeline_id=pipeline_id, request_key=request_key,
        lease_seconds=lease_seconds,
    )
    if error:
        raise MediaSelectionError(error)
    return result


@transaction.atomic
def _heartbeat_tx(*, pipeline_id, request_key, lease_seconds):
    pipeline = _pipeline(pipeline_id)
    now = timezone.now()
    allocation = _allocation(pipeline.pk, request_key)
    if (allocation.state == MediaAllocation.State.RESERVED and
            allocation.lease_expires_at <= now):
        allocation.state = MediaAllocation.State.UNCERTAIN
        allocation.save(update_fields=["state", "updated_at"])
    if allocation.state != MediaAllocation.State.RESERVED:
        return None, "Chỉ gia hạn được tác vụ đang giữ chỗ, chưa hết hạn."
    allocation.lease_expires_at = now + timedelta(seconds=lease_seconds)
    allocation.last_heartbeat_at = now
    allocation.save(update_fields=["lease_expires_at", "last_heartbeat_at", "updated_at"])
    return allocation_payload(allocation), None


def mark_publishing_started(*, pipeline_id, request_key):
    """Must succeed exactly once BEFORE making an external publishing call.

    Retry with status uncertain is deliberately forbidden. The caller must
    reconcile the external publication result before doing anything else.
    """
    request_key = _key(request_key)
    expire_stale_reservations(pipeline_id=pipeline_id)
    result, error = _mark_started_tx(pipeline_id=pipeline_id, request_key=request_key)
    if error:
        raise MediaSelectionError(error)
    return result


@transaction.atomic
def _mark_started_tx(*, pipeline_id, request_key):
    pipeline = _pipeline(pipeline_id)
    now = timezone.now()
    allocation = _allocation(pipeline.pk, request_key)
    if (allocation.state == MediaAllocation.State.RESERVED and
            allocation.lease_expires_at <= now):
        allocation.state = MediaAllocation.State.UNCERTAIN
        allocation.save(update_fields=["state", "updated_at"])
    if allocation.state != MediaAllocation.State.RESERVED:
        return None, "Tác vụ đã đăng/hết hạn hoặc đã hủy; không thử lại mù."
    if pipeline.status != Pipeline.Status.ACTIVE:
        return None, "Pipeline đang bị khóa."
    if not PipelineMediaPolicy.objects.filter(
        pipeline_id=pipeline.pk, is_enabled=True,
    ).exists():
        return None, "Chính sách nguồn ảnh đã bị tắt."
    allocation.state = MediaAllocation.State.UNCERTAIN
    allocation.save(update_fields=["state", "updated_at"])
    return allocation_payload(allocation), None


@transaction.atomic
def confirm_consumed(*, pipeline_id, request_key):
    """Only after independently verifying external publication succeeded."""
    request_key = _key(request_key)
    pipeline = _pipeline(pipeline_id)
    allocation = _allocation(pipeline.pk, request_key)
    if allocation.state == MediaAllocation.State.CONSUMED:
        return allocation_payload(allocation)
    if allocation.state != MediaAllocation.State.UNCERTAIN:
        raise MediaSelectionError("Chưa đánh dấu bắt đầu đăng hoặc đã hủy.")
    allocation.state = MediaAllocation.State.CONSUMED
    allocation.finalized_at = timezone.now()
    allocation.save(update_fields=["state", "finalized_at", "updated_at"])
    return allocation_payload(allocation)


def release_reserved(*, pipeline_id, request_key):
    """Release only if the job NEVER attempted external publication."""
    request_key = _key(request_key)
    expire_stale_reservations(pipeline_id=pipeline_id)
    result, error = _release_tx(pipeline_id=pipeline_id, request_key=request_key)
    if error:
        raise MediaSelectionError(error)
    return result


@transaction.atomic
def _release_tx(*, pipeline_id, request_key):
    pipeline = _pipeline(pipeline_id)
    now = timezone.now()
    allocation = _allocation(pipeline.pk, request_key)
    if allocation.state == MediaAllocation.State.RELEASED:
        return allocation_payload(allocation), None
    if (allocation.state == MediaAllocation.State.RESERVED and
            allocation.lease_expires_at <= now):
        allocation.state = MediaAllocation.State.UNCERTAIN
        allocation.save(update_fields=["state", "updated_at"])
    if allocation.state != MediaAllocation.State.RESERVED:
        return None, "Không được tự giải phóng ảnh đã thử đăng hoặc hết hạn."
    allocation.state = MediaAllocation.State.RELEASED
    allocation.finalized_at = now
    allocation.save(update_fields=["state", "finalized_at", "updated_at"])
    return allocation_payload(allocation), None
