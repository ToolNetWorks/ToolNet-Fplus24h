from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.albums.models import Album
from modules.pipelines.models import Pipeline
class AlbumCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
    )
    is_enabled = serializers.BooleanField(default=True)
class AlbumFilterSerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(
        min_value=1,
        max_value=50,
        default=10,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        trim_whitespace=True,
    )
    enabled = serializers.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enabled"].default_empty_html = serializers.empty
def resolve_pipeline(user, pipeline_id):
    if not user.is_active:
        raise PermissionDenied("Tài khoản đã bị khóa.")
    if user.is_superuser and user.is_staff:
        pipeline = Pipeline.objects.filter(
            pk=pipeline_id
        ).first()
    elif not user.is_staff and not user.is_superuser:
        pipeline = Pipeline.objects.filter(
            pk=pipeline_id,
            ctv_id=user.pk,
        ).first()
    else:
        raise PermissionDenied("Không đủ quyền.")
    if pipeline is None:
        raise Http404("Pipeline không tồn tại.")
    if not user.is_superuser:
        if pipeline.status != Pipeline.Status.ACTIVE:
            raise PermissionDenied("Pipeline đang bị khóa.")
    return pipeline
def album_to_dict(album):
    return {
        "id": str(album.pk),
        "pipeline_id": str(album.pipeline_id),
        "name": album.name,
        "description": album.description,
        "is_enabled": album.is_enabled,
        "image_count": getattr(album, "image_count", 0),
        "created_at": album.created_at.isoformat(),
        "updated_at": album.updated_at.isoformat(),
    }
class AlbumCollectionAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        filters = AlbumFilterSerializer(
            data=request.query_params
        )
        filters.is_valid(raise_exception=True)
        params = filters.validated_data
        base_queryset = Album.objects.filter(
            pipeline_id=pipeline.pk
        )
        summary = base_queryset.aggregate(
            total=Count("id"),
            enabled=Count("id", filter=Q(is_enabled=True)),
            disabled=Count("id", filter=Q(is_enabled=False)),
        )
        queryset = base_queryset
        search = params.get("search", "")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(description__icontains=search)
            )
        if "enabled" in params:
            queryset = queryset.filter(
                is_enabled=params["enabled"]
            )
        queryset = (
            queryset
            .annotate(image_count=Count("images"))
            .order_by("-created_at", "-id")
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
        response = Response({
            "success": True,
            "data": [
                album_to_dict(album)
                for album in page.object_list
            ],
            "summary": summary,
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
    def post(self, request, pipeline_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        serializer = AlbumCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                album = Album(
                    pipeline=pipeline,
                    **serializer.validated_data,
                )
                album.full_clean()
                album.save()
        except DjangoValidationError:
            return Response({
                "success": False,
                "message": "Thông tin Album không hợp lệ.",
            }, status=400)
        return Response({
            "success": True,
            "message": "Đã tạo Album.",
            "data": album_to_dict(album),
        }, status=201)
