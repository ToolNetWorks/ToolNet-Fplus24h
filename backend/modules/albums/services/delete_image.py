import logging
import uuid
from django.db import transaction
from modules.albums.models import Album, AlbumImage
from .r2_storage import R2StorageError, get_r2_client
logger = logging.getLogger(__name__)
class ImageDeletionConflict(Exception):
    pass
def validate_storage_key(image, pipeline_id, album_id):
    key = image.storage_key or ""
    prefix = (
        f"pipeline-albums/{pipeline_id}/"
        f"{album_id}/"
    )
    if not key.startswith(prefix) or not key.endswith(".webp"):
        raise ImageDeletionConflict(
            "Đường dẫn lưu trữ ảnh không hợp lệ."
        )
    file_id = key[len(prefix):-5]
    try:
        canonical_id = str(uuid.UUID(file_id))
    except (ValueError, TypeError) as exc:
        raise ImageDeletionConflict(
            "Định danh object không hợp lệ."
        ) from exc
    if file_id != canonical_id:
        raise ImageDeletionConflict(
            "Định danh object không đúng định dạng."
        )
    return key
def delete_album_image(*, pipeline_id, album_id, image_id):
    """
    Phase 1: mark image as deleting.
    Phase 2: delete R2 object.
    Phase 3: delete DB record.
    R2 failure leaves a retryable 'deleting' record.
    """
    with transaction.atomic():
        album = (
            Album.objects
            .select_for_update()
            .get(
                pk=album_id,
                pipeline_id=pipeline_id,
            )
        )
        image = (
            AlbumImage.objects
            .select_for_update()
            .get(
                pk=image_id,
                album_id=album.pk,
            )
        )
        key = validate_storage_key(
            image,
            pipeline_id,
            album_id,
        )
        allowed = {
            AlbumImage.UploadStatus.READY,
            AlbumImage.UploadStatus.DELETING,
        }
        if image.upload_status not in allowed:
            raise ImageDeletionConflict(
                "Ảnh chưa sẵn sàng để xóa."
            )
        if image.upload_status != AlbumImage.UploadStatus.DELETING:
            image.upload_status = AlbumImage.UploadStatus.DELETING
            image.save(
                update_fields=[
                    "upload_status",
                    "updated_at",
                ]
            )
    # No database transaction is held during network I/O.
    try:
        client, bucket = get_r2_client()
        client.delete_object(
            Bucket=bucket,
            Key=key,
        )
    except Exception as exc:
        logger.exception(
            "R2 deletion failed; record retained for retry",
            extra={
                "pipeline_id": str(pipeline_id),
                "album_id": str(album_id),
                "image_id": str(image_id),
            },
        )
        raise R2StorageError(
            "Không thể xóa ảnh trên R2. Có thể thử lại."
        ) from exc
    # The DELETE operation on S3/R2 is idempotent.
    # A second request can safely retry the same object.
    with transaction.atomic():
        Album.objects.select_for_update().get(
            pk=album_id,
            pipeline_id=pipeline_id,
        )
        AlbumImage.objects.filter(
            pk=image_id,
            album_id=album_id,
            storage_key=key,
            upload_status=AlbumImage.UploadStatus.DELETING,
        ).delete()
    return True
