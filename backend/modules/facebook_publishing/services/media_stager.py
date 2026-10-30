"""Media staging for the Facebook Publishing Worker.

Downloads images from Cloudflare R2 to a local temp file for browser upload,
then deletes the temp file after processing. Never leaves temp images on disk.
"""
import hashlib
import os
import tempfile
from dataclasses import dataclass
from typing import List, Optional

from django.core.exceptions import ValidationError

from modules.albums.models import AlbumImage
from modules.albums.services.r2_storage import read_r2_config
from modules.facebook_publishing.services.config import WorkerSettings


@dataclass(frozen=True)
class StagedImage:
    image_id: str
    album_id: str
    temp_path: str
    file_size: int
    mime_type: str
    sha256: str
    width: int
    height: int


class MediaStagingError(Exception):
    pass


class MediaStager:
    """Download images from R2 to local temp files for browser upload."""

    def __init__(self, settings: WorkerSettings):
        self._settings = settings
        self._temp_files: List[str] = []

    def _get_r2_client(self):
        import boto3
        cfg = read_r2_config()
        if not cfg['bucket'] or not cfg['access_key'] or not cfg['secret_key']:
            raise MediaStagingError('R2 configuration is incomplete.')
        client = boto3.client(
            's3',
            endpoint_url=cfg['endpoint_url'],
            aws_access_key_id=cfg['access_key'],
            aws_secret_access_key=cfg['secret_key'],
            config=cfg['botocore_config'],
            region_name=cfg['region'],
        )
        return client, cfg['bucket']

    def stage_image(self, *, pipeline_id, image_id):
        """Download a single AlbumImage to a temp file."""
        image = AlbumImage.objects.filter(
            pk=image_id, album__pipeline_id=pipeline_id,
            upload_status=AlbumImage.UploadStatus.READY,
            storage_key__isnull=False,
        ).first()
        if image is None:
            raise MediaStagingError(
                f'AlbumImage {image_id} not found, not READY, or not in Pipeline {pipeline_id}.'
            )
        if not image.storage_key:
            raise MediaStagingError(f'AlbumImage {image_id} has no storage key.')

        client, bucket = self._get_r2_client()

        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix='.webp',
            prefix=f'fbpub-{image_id.hex[:8]}-',
        )
        try:
            with os.fdopen(tmp_fd, 'wb') as f:
                client.download_fileobj(bucket, image.storage_key, f)
            file_size = os.path.getsize(tmp_path)
            actual_sha = hashlib.sha256(open(tmp_path, 'rb').read()).hexdigest()
            if actual_sha != image.sha256:
                raise MediaStagingError(
                    f'SHA256 mismatch for image {image_id}.'
                )
            staged = StagedImage(
                image_id=str(image.pk),
                album_id=str(image.album_id),
                temp_path=tmp_path,
                file_size=file_size,
                mime_type='image/webp',
                sha256=actual_sha,
                width=image.width,
                height=image.height,
            )
            self._temp_files.append(tmp_path)
            return staged
        except Exception:
            self._safe_delete(tmp_path)
            raise

    def stage_all(self, *, pipeline_id, image_ids):
        """Stage multiple images."""
        staged = []
        for image_id in image_ids:
            staged.append(self.stage_image(
                pipeline_id=pipeline_id, image_id=image_id,
            ))
        return staged

    def _safe_delete(self, path):
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
            if path in self._temp_files:
                self._temp_files.remove(path)

    def cleanup(self):
        """Delete all temp images downloaded from R2."""
        for path in list(self._temp_files):
            self._safe_delete(path)
        self._temp_files.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
        return False
