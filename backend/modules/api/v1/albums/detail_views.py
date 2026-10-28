from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import Http404
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.albums.models import Album
from .views import resolve_pipeline, album_to_dict
class AlbumUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=200,
        trim_whitespace=True,
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
    )
    is_enabled = serializers.BooleanField(
        required=False,
    )
    def validate(self, attrs):
        allowed = {
            "name",
            "description",
            "is_enabled",
        }
        if not isinstance(self.initial_data, dict):
            raise serializers.ValidationError(
                "Dữ liệu phải là JSON object."
            )
        keys = set(self.initial_data)
        if not keys or not keys.issubset(allowed):
            raise serializers.ValidationError(
                "Chỉ cho phép sửa tên, mô tả và trạng thái Album."
            )
        return attrs
class AlbumDetailAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    def get_album(self, request, pipeline_id, album_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        album = (
            Album.objects
            .filter(
                pk=album_id,
                pipeline_id=pipeline.pk,
            )
            .annotate(image_count=Count("images"))
            .first()
        )
        if album is None:
            raise Http404("Album không tồn tại.")
        return album
    def get(self, request, pipeline_id, album_id):
        album = self.get_album(
            request,
            pipeline_id,
            album_id,
        )
        response = Response({
            "success": True,
            "data": album_to_dict(album),
        })
        response["Cache-Control"] = "private, no-store"
        return response
    def patch(self, request, pipeline_id, album_id):
        # Check Pipeline ownership before validating changes.
        self.get_album(
            request,
            pipeline_id,
            album_id,
        )
        serializer = AlbumUpdateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                album = (
                    Album.objects
                    .select_for_update()
                    .get(
                        pk=album_id,
                        pipeline_id=pipeline_id,
                    )
                )
                for field, value in (
                    serializer.validated_data.items()
                ):
                    setattr(album, field, value)
                album.full_clean()
                album.save()
        except Album.DoesNotExist:
            raise Http404("Album không tồn tại.")
        except DjangoValidationError as exc:
            return Response({
                "success": False,
                "message": "Dữ liệu Album không hợp lệ.",
                "errors": (
                    exc.message_dict
                    if hasattr(exc, "message_dict")
                    else {"non_field_errors": exc.messages}
                ),
            }, status=400)
        except IntegrityError:
            return Response({
                "success": False,
                "message": "Không thể cập nhật Album.",
            }, status=409)
        album = (
            Album.objects
            .filter(pk=album.pk)
            .annotate(image_count=Count("images"))
            .get()
        )
        response = Response({
            "success": True,
            "message": "Đã cập nhật Album.",
            "data": album_to_dict(album),
        })
        response["Cache-Control"] = "private, no-store"
        return response
