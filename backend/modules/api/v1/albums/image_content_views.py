import hashlib
import logging
import uuid
from botocore.exceptions import BotoCoreError, ClientError
from django.http import Http404, HttpResponse
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.albums.models import AlbumImage
from modules.albums.services.r2_storage import (
    MAX_OUTPUT_BYTES,
    get_r2_client,
)
from .views import resolve_pipeline
logger = logging.getLogger(__name__)
class AlbumImageContentAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request, pipeline_id, album_id, image_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        image = (
            AlbumImage.objects
            .filter(
                pk=image_id,
                album_id=album_id,
                album__pipeline_id=pipeline.pk,
                upload_status=AlbumImage.UploadStatus.READY,
            )
            .first()
        )
        if image is None:
            raise Http404("Ảnh không tồn tại.")
        key = image.storage_key or ""
        expected_prefix = (
            f"pipeline-albums/{pipeline.pk}/"
            f"{album_id}/"
        )
        # Reject invalid or unexpected storage locations.
        if (
            not key.startswith(expected_prefix)
            or not key.endswith(".webp")
            or image.mime_type != "image/webp"
        ):
            logger.error(
                "Invalid album image storage metadata",
                extra={"image_id": str(image.pk)},
            )
            return Response({
                "success": False,
                "message": "Metadata ảnh không hợp lệ.",
            }, status=409)
        try:
            image_uuid = uuid.UUID(
                key[len(expected_prefix):-5]
            )
            if str(image_uuid) != key[len(expected_prefix):-5]:
                raise ValueError("Noncanonical image UUID")
        except (TypeError, ValueError):
            return Response({
                "success": False,
                "message": "Khóa ảnh không hợp lệ.",
            }, status=409)
        if (
            image.file_size <= 0
            or image.file_size > MAX_OUTPUT_BYTES
        ):
            return Response({
                "success": False,
                "message": "Kích thước ảnh không hợp lệ.",
            }, status=409)
        try:
            client, bucket = get_r2_client()
            result = client.get_object(
                Bucket=bucket,
                Key=key,
            )
            body = result["Body"]
            try:
                content = body.read(MAX_OUTPUT_BYTES + 1)
            finally:
                body.close()
        except ClientError as exc:
            code = exc.response.get(
                "Error", {}
            ).get("Code", "")
            if code in {
                "NoSuchKey",
                "NotFound",
                "404",
            }:
                raise Http404(
                    "File ảnh không tồn tại."
                ) from exc
            logger.exception(
                "R2 image read failed",
                extra={"image_id": str(image.pk)},
            )
            return Response({
                "success": False,
                "message": "Không thể đọc ảnh.",
            }, status=502)
        except (BotoCoreError, OSError, RuntimeError):
            logger.exception(
                "Album image storage error",
                extra={"image_id": str(image.pk)},
            )
            return Response({
                "success": False,
                "message": "Dịch vụ ảnh tạm thời không khả dụng.",
            }, status=502)
        if (
            len(content) != image.file_size
            or hashlib.sha256(content).hexdigest()
            != image.sha256
        ):
            logger.error(
                "Album image integrity mismatch",
                extra={"image_id": str(image.pk)},
            )
            return Response({
                "success": False,
                "message": "Dữ liệu ảnh không toàn vẹn.",
            }, status=502)
        response = HttpResponse(
            content,
            content_type="image/webp",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Disposition"] = (
            f'inline; filename="{image.pk}.webp"'
        )
        return response
