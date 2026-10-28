import logging
from django.http import Http404
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.albums.models import Album, AlbumImage
from modules.albums.services.delete_image import (
    ImageDeletionConflict,
    delete_album_image,
)
from modules.albums.services.r2_storage import R2StorageError
from .views import resolve_pipeline
logger = logging.getLogger(__name__)
class AlbumImageDeleteAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    def delete(self, request, pipeline_id, album_id, image_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        if not Album.objects.filter(
            pk=album_id,
            pipeline_id=pipeline.pk,
        ).exists():
            raise Http404("Album không tồn tại.")
        if not AlbumImage.objects.filter(
            pk=image_id,
            album_id=album_id,
            album__pipeline_id=pipeline.pk,
        ).exists():
            raise Http404("Ảnh không tồn tại.")
        try:
            delete_album_image(
                pipeline_id=pipeline.pk,
                album_id=album_id,
                image_id=image_id,
            )
        except (Album.DoesNotExist, AlbumImage.DoesNotExist):
            raise Http404("Ảnh không tồn tại.")
        except ImageDeletionConflict as exc:
            return Response({
                "success": False,
                "message": str(exc),
            }, status=409)
        except R2StorageError:
            return Response({
                "success": False,
                "message": (
                    "Không thể hoàn tất xóa ảnh. "
                    "Vui lòng thử lại."
                ),
            }, status=502)
        response = Response({
            "success": True,
            "message": "Đã xóa ảnh.",
        })
        response["Cache-Control"] = "private, no-store"
        return response
