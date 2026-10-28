import logging
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import (
    ProtectedError,
    RestrictedError,
)
from django.http import Http404
from rest_framework import serializers
from rest_framework.response import Response
from modules.pipelines.models import Pipeline
from modules.pipelines.delete_services import (
    delete_pipeline_and_ctv,
    get_delete_preview,
)
from .edit_views import PipelineEditAPIView
logger = logging.getLogger(__name__)
class PipelineDeleteSerializer(serializers.Serializer):
    confirm_name = serializers.CharField(
        trim_whitespace=False,
        allow_blank=False,
    )
    confirm_username = serializers.CharField(
        trim_whitespace=False,
        allow_blank=False,
    )
    def validate(self, attrs):
        if set(self.initial_data) != {
            "confirm_name",
            "confirm_username",
        }:
            raise serializers.ValidationError(
                "Dữ liệu xác nhận không hợp lệ."
            )
        return attrs
class PipelineDetailAPIView(PipelineEditAPIView):
    """
    PATCH inherited from PipelineEditAPIView.
    GET performs deletion preflight.
    DELETE removes an empty Pipeline and its CTV.
    """
    def get(self, request, pipeline_id):
        pipeline = (
            Pipeline.objects
            .select_related("ctv")
            .filter(pk=pipeline_id)
            .first()
        )
        if pipeline is None:
            raise Http404("Pipeline không tồn tại.")
        try:
            preview = get_delete_preview(pipeline)
        except (ValidationError, AttributeError):
            return Response({
                "success": False,
                "message": "Không thể kiểm tra quan hệ dữ liệu.",
            }, status=409)
        return Response({
            "success": True,
            "data": preview,
        })
    def delete(self, request, pipeline_id):
        serializer = PipelineDeleteSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        try:
            deleted = delete_pipeline_and_ctv(
                pipeline_id=pipeline_id,
                confirm_name=serializer.validated_data[
                    "confirm_name"
                ],
                confirm_username=serializer.validated_data[
                    "confirm_username"
                ],
            )
        except Pipeline.DoesNotExist as exc:
            raise Http404("Pipeline không tồn tại.") from exc
        except UserDoesNotExist():
            raise Http404("CTV không tồn tại.")
        except (
            ValidationError,
            ProtectedError,
            RestrictedError,
            IntegrityError,
            AttributeError,
        ) as exc:
            if isinstance(exc, ValidationError):
                message = "; ".join(exc.messages)
            else:
                message = (
                    "Không thể xóa vì còn quan hệ dữ liệu "
                    "hoặc ràng buộc database."
                )
            return Response({
                "success": False,
                "message": message,
            }, status=409)
        logger.info(
            "Pipeline and CTV deleted by Admin",
            extra={
                "admin_id": request.user.pk,
                "pipeline_id": deleted["pipeline_id"],
                "ctv_id": deleted["ctv_id"],
            },
        )
        return Response({
            "success": True,
            "message": "Đã xóa Pipeline và CTV.",
            "data": deleted,
        })
def UserDoesNotExist():
    from django.contrib.auth import get_user_model
    return get_user_model().DoesNotExist
