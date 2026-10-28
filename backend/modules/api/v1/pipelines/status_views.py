import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.api.v1.permissions import IsSuperAdmin
from modules.pipelines.models import Pipeline

logger = logging.getLogger(__name__)


class PipelineStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=Pipeline.Status.choices
    )

    def validate(self, attrs):
        if set(self.initial_data.keys()) != {"status"}:
            raise serializers.ValidationError(
                "Chỉ cho phép cập nhật trạng thái."
            )

        return attrs


class PipelineStatusAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    @transaction.atomic
    def patch(self, request, pipeline_id):
        serializer = PipelineStatusSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            pk = Pipeline._meta.pk.to_python(pipeline_id)
        except (ValidationError, ValueError, TypeError):
            return Response(
                {
                    "success": False,
                    "message": "Pipeline không tồn tại.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        pipeline = (
            Pipeline.objects
            .select_for_update()
            .select_related("ctv")
            .filter(pk=pk)
            .first()
        )

        if pipeline is None:
            return Response(
                {
                    "success": False,
                    "message": "Pipeline không tồn tại.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        ctv = pipeline.ctv

        if ctv is None or ctv.is_staff or ctv.is_superuser:
            return Response(
                {
                    "success": False,
                    "message": "Tài khoản CTV không hợp lệ.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        new_status = serializer.validated_data["status"]
        new_active = new_status == Pipeline.Status.ACTIVE
        old_status = pipeline.status

        if pipeline.status != new_status:
            pipeline.status = new_status
            pipeline.save(update_fields=["status"])

        if ctv.is_active != new_active:
            ctv.is_active = new_active
            ctv.save(update_fields=["is_active"])

        logger.info(
            "Pipeline status changed",
            extra={
                "admin_id": request.user.pk,
                "pipeline_id": str(pipeline.pk),
                "old_status": old_status,
                "new_status": new_status,
            },
        )

        return Response({
            "success": True,
            "message": (
                "Đã kích hoạt Pipeline."
                if new_active
                else "Đã khóa Pipeline và CTV."
            ),
            "data": {
                "id": str(pipeline.pk),
                "name": pipeline.name,
                "status": pipeline.status,
                "ctv": {
                    "id": ctv.pk,
                    "username": ctv.username,
                    "is_active": ctv.is_active,
                },
            },
        })
