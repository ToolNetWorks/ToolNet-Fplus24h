from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.albums.models import Album
from modules.pipelines.models import Pipeline
from .views import resolve_pipeline


class AlbumBulkThrottle(UserRateThrottle):
    rate = "15/min"


class AlbumBulkSerializer(serializers.Serializer):
    album_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        min_length=1,
        max_length=50,
    )
    is_enabled = serializers.BooleanField()

    def validate(self, attrs):
        raw = self.initial_data
        if not isinstance(raw, dict):
            raise serializers.ValidationError(
                "Dữ liệu phải là JSON object."
            )
        if set(raw) != {"album_ids", "is_enabled"}:
            raise serializers.ValidationError(
                "Chỉ chấp nhận album_ids và is_enabled."
            )
        if type(raw["is_enabled"]) is not bool:
            raise serializers.ValidationError({
                "is_enabled": "Giá trị phải là boolean."
            })
        ids = attrs["album_ids"]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError({
                "album_ids": "Không được chọn Album trùng lặp."
            })
        return attrs


class AlbumBulkStatusAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [AlbumBulkThrottle]

    def post(self, request, pipeline_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        serializer = AlbumBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["album_ids"]
        enabled = serializer.validated_data["is_enabled"]
        with transaction.atomic():
            locked_pipeline = (
                Pipeline.objects
                .select_for_update()
                .filter(pk=pipeline.pk)
                .first()
            )
            if locked_pipeline is None:
                return Response({
                    "success": False,
                    "message": "Pipeline không tồn tại.",
                }, status=404)
            if (
                not request.user.is_superuser
                and locked_pipeline.status != Pipeline.Status.ACTIVE
            ):
                return Response({
                    "success": False,
                    "message": "Pipeline đã bị khóa.",
                }, status=403)
            albums = list(
                Album.objects
                .select_for_update()
                .filter(
                    pk__in=ids,
                    pipeline_id=pipeline.pk,
                )
                .order_by("pk")
            )
            if len(albums) != len(ids):
                return Response({
                    "success": False,
                    "message": (
                        "Có Album không thuộc Pipeline hoặc "
                        "không tồn tại. Không có thay đổi."
                    ),
                }, status=404)
            changed_ids = [
                album.pk
                for album in albums
                if album.is_enabled != enabled
            ]
            if changed_ids:
                Album.objects.filter(
                    pipeline_id=pipeline.pk,
                    pk__in=changed_ids,
                ).update(
                    is_enabled=enabled,
                    updated_at=timezone.now(),
                )
        response = Response({
            "success": True,
            "message": (
                "Đã bật các Album được chọn."
                if enabled
                else "Đã tắt các Album được chọn."
            ),
            "data": {
                "selected_count": len(ids),
                "updated_count": len(changed_ids),
                "is_enabled": enabled,
            },
        })
        response["Cache-Control"] = "private, no-store"
        return response
