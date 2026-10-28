from django.core.paginator import EmptyPage, Paginator
from django.http import Http404
from rest_framework import serializers
from rest_framework.response import Response
from modules.albums.models import Album, AlbumImage
from .upload_views import AlbumImageUploadAPIView
from .views import resolve_pipeline
class ImageListFilterSerializer(serializers.Serializer):
    page = serializers.IntegerField(
        min_value=1,
        default=1,
    )
    page_size = serializers.IntegerField(
        min_value=1,
        max_value=50,
        default=20,
    )
class AlbumImageCollectionAPIView(AlbumImageUploadAPIView):
    """
    GET: list image metadata.
    POST: upload images (inherited).
    Never expose R2 storage keys.
    """
    def get(self, request, pipeline_id, album_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        album = Album.objects.filter(
            pk=album_id,
            pipeline_id=pipeline.pk,
        ).first()
        if album is None:
            raise Http404("Album không tồn tại.")
        serializer = ImageListFilterSerializer(
            data=request.query_params,
        )
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        queryset = AlbumImage.objects.filter(
            album_id=album.pk,
        ).order_by(
            "position",
            "created_at",
            "id",
        )
        paginator = Paginator(
            queryset,
            params["page_size"],
        )
        try:
            page = paginator.page(params["page"])
        except EmptyPage:
            return Response({
                "success": False,
                "message": "Trang không tồn tại.",
            }, status=400)
        items = []
        for item in page.object_list:
            ready = (
                item.upload_status
                == AlbumImage.UploadStatus.READY
            )
            items.append({
                "id": str(item.pk),
                "album_id": str(item.album_id),
                "original_filename": item.original_filename,
                "mime_type": item.mime_type,
                "file_size": item.file_size,
                "width": item.width,
                "height": item.height,
                "position": item.position,
                "upload_status": item.upload_status,
                "content_url": (
                    f"/api/v1/pipelines/{pipeline.pk}/"
                    f"albums/{album.pk}/images/{item.pk}/content/"
                    if ready
                    else None
                ),
                "created_at": item.created_at.isoformat(),
            })
        response = Response({
            "success": True,
            "data": items,
            "pagination": {
                "page": page.number,
                "page_size": params["page_size"],
                "total": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
            },
        })
        response["Cache-Control"] = "private, no-store"
        return response
