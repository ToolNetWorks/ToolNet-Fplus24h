import logging
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.api.v1.permissions import IsSuperAdmin
from modules.pipelines.models import Pipeline
from modules.pipelines.edit_services import (
    update_pipeline_and_ctv,
)
from .edit_serializers import PipelineEditSerializer
logger = logging.getLogger(__name__)
class PipelineEditAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]
    def patch(self, request, pipeline_id):
        pipeline = (
            Pipeline.objects
            .select_related("ctv")
            .filter(pk=pipeline_id)
            .first()
        )
        if pipeline is None:
            raise Http404("Pipeline không tồn tại.")
        if pipeline.ctv.is_staff or pipeline.ctv.is_superuser:
            return Response({
                "success": False,
                "message": "Tài khoản CTV không hợp lệ.",
            }, status=409)
        serializer = PipelineEditSerializer(
            data=request.data,
            context={"pipeline": pipeline},
        )
        serializer.is_valid(raise_exception=True)
        try:
            updated = update_pipeline_and_ctv(
                pipeline_id=pipeline.pk,
                changes=serializer.validated_data,
            )
        except ValidationError as exc:
            return Response({
                "success": False,
                "message": "; ".join(exc.messages),
            }, status=400)
        except IntegrityError:
            return Response({
                "success": False,
                "message": "Tên Pipeline hoặc username đã tồn tại.",
            }, status=409)
        logger.info(
            "Pipeline and CTV updated",
            extra={
                "admin_id": request.user.pk,
                "pipeline_id": str(updated.pk),
            },
        )
        return Response({
            "success": True,
            "message": "Cập nhật thông tin thành công.",
            "data": {
                "id": str(updated.pk),
                "name": updated.name,
                "status": updated.status,
                "ctv": {
                    "id": updated.ctv.pk,
                    "username": updated.ctv.username,
                    "email": updated.ctv.email,
                },
            },
        })
