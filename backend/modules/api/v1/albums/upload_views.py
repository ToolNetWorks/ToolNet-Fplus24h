import logging
import uuid
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import Http404
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.albums.models import Album
from modules.albums.services.batch_upload import (
    AlbumUploadCleanupError,
    AlbumUploadRejected,
    upload_album_batch,
)
from modules.albums.services.r2_storage import (
    ImageValidationError,
    R2StorageError,
)
from .views import resolve_pipeline

logger = logging.getLogger(__name__)
class AlbumImageUploadAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    def post(self, request, pipeline_id, album_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        album_exists = Album.objects.filter(
            pk=album_id,
            pipeline_id=pipeline.pk,
        ).exists()
        if not album_exists:
            raise Http404("Album không tồn tại.")
        files = request.FILES.getlist("files")
        if not 1 <= len(files) <= 5:
            return Response({
                "success": False,
                "message": "Chọn từ 1 đến 5 ảnh.",
            }, status=400)
        try:
            records = upload_album_batch(
                pipeline_id=pipeline.pk,
                album_id=album_id,
                files=files,
            )
        except (
            AlbumUploadRejected,
            ImageValidationError,
            ValidationError,
        ) as exc:
            return Response({
                "success": False,
                "message": str(exc),
            }, status=400)
        except Album.DoesNotExist:
            raise Http404("Album không tồn tại.")
        except AlbumUploadCleanupError:
            logger.error(
                "Album upload requires R2 reconciliation",
                extra={
                    "pipeline_id": str(pipeline.pk),
                    "album_id": str(album_id),
                },
            )
            return Response({
                "success": False,
                "message": (
                    "Upload thất bại. "
                    "Cần kiểm tra dữ liệu lưu trữ."
                ),
            }, status=503)
        except (R2StorageError, DatabaseError):
            logger.exception(
                "Album upload failed",
                extra={
                    "pipeline_id": str(pipeline.pk),
                    "album_id": str(album_id),
                },
            )
            return Response({
                "success": False,
                "message": "Không thể lưu ảnh. Vui lòng thử lại.",
            }, status=502)
        except Exception:
            request_id = uuid.uuid4().hex
            logger.exception(
                "Unexpected album upload error",
                extra={
                    "request_id": request_id,
                    "pipeline_id": str(pipeline.pk),
                    "album_id": str(album_id),
                },
            )
            return Response({
                "success": False,
                "message": "Lỗi không xác định. Vui lòng thử lại.",
                "request_id": request_id,
            }, status=500)
        response = Response({
            "success": True,
            "message": f"Đã upload {len(records)} ảnh.",
            "data": [
                {
                    "id": str(record.pk),
                    "album_id": str(record.album_id),
                    "original_filename": record.original_filename,
                    "mime_type": record.mime_type,
                    "file_size": record.file_size,
                    "width": record.width,
                    "height": record.height,
                    "position": record.position,
                    "upload_status": record.upload_status,
                }
                for record in records
            ],
        }, status=201)
        response["Cache-Control"] = "private, no-store"
        return response
