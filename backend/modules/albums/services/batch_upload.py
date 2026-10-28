import logging
from pathlib import Path
from django.db import transaction
from django.db.models import Max
from modules.albums.models import Album, AlbumImage
from modules.pipelines.models import Pipeline
from .r2_storage import (
    ImageValidationError,
    build_storage_key,
    get_r2_client,
    upload_album_image,
)
logger = logging.getLogger(__name__)
MAX_FILES = 5
MAX_FILE_SIZE = 10 * 1024 * 1024
class AlbumUploadRejected(ValueError):
    pass
class AlbumUploadCleanupError(RuntimeError):
    pass
def validate_batch(files):
    if not 1 <= len(files) <= MAX_FILES:
        raise AlbumUploadRejected(
            "Mỗi lần chỉ được upload từ 1 đến 5 ảnh."
        )
    for file in files:
        if (
            file.size <= 0
            or file.size > MAX_FILE_SIZE
        ):
            raise AlbumUploadRejected(
                "Mỗi ảnh phải có dung lượng tối đa 10 MB."
            )
def upload_album_batch(*, pipeline_id, album_id, files):
    validate_batch(files)
    client, bucket = get_r2_client()
    attempted_keys = []
    created_records = []
    try:
        with transaction.atomic():
            pipeline = (
                Pipeline.objects
                .select_for_update()
                .get(pk=pipeline_id)
            )
            if pipeline.status != Pipeline.Status.ACTIVE:
                raise AlbumUploadRejected(
                    "Pipeline đang bị khóa."
                )
            album = (
                Album.objects
                .select_for_update()
                .get(
                    pk=album_id,
                    pipeline_id=pipeline.pk,
                )
            )
            if not album.is_enabled:
                raise AlbumUploadRejected(
                    "Album đang bị tắt."
                )
            last_position = (
                AlbumImage.objects
                .filter(album_id=album.pk)
                .aggregate(value=Max("position"))
                ["value"]
                or 0
            )
            for index, file in enumerate(files, start=1):
                key = build_storage_key(
                    pipeline_id=pipeline.pk,
                    album_id=album.pk,
                )
                # Track before PUT to handle an ambiguous R2 response.
                attempted_keys.append(key)
                stored = upload_album_image(
                    pipeline_id=pipeline.pk,
                    album_id=album.pk,
                    fileobj=file,
                    client=client,
                    bucket=bucket,
                    storage_key=key,
                )
                filename = Path(
                    file.name.replace("\\", "/")
                ).name[:255]
                record = AlbumImage(
                    album=album,
                    original_filename=filename,
                    storage_key=stored.storage_key,
                    mime_type=stored.mime_type,
                    file_size=stored.file_size,
                    width=stored.width,
                    height=stored.height,
                    sha256=stored.sha256,
                    position=last_position + index,
                    upload_status=AlbumImage.UploadStatus.READY,
                )
                record.full_clean()
                record.save()
                created_records.append(record)
            return created_records
    except Exception:
        cleanup_failed = []
        for key in reversed(attempted_keys):
            try:
                client.delete_object(
                    Bucket=bucket,
                    Key=key,
                )
            except Exception:
                cleanup_failed.append(key)
                logger.exception(
                    "R2 album upload cleanup failed",
                    extra={
                        "pipeline_id": str(pipeline_id),
                        "album_id": str(album_id),
                        "object_key": key,
                    },
                )
        if cleanup_failed:
            raise AlbumUploadCleanupError(
                "Upload thất bại và có object R2 cần dọn thủ công."
            ) from None
        raise
