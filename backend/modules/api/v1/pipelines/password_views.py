import logging
from django.core.exceptions import ValidationError
from django.http import Http404
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.api.v1.permissions import IsSuperAdmin
from modules.pipelines.models import Pipeline
from modules.pipelines.password_services import change_ctv_password
from .password_serializers import CTVPasswordSerializer
logger = logging.getLogger(__name__)
class CTVPasswordAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]
    def post(self, request, pipeline_id):
        try:
            pipeline = Pipeline.objects.select_related(
                "ctv"
            ).get(pk=pipeline_id)
        except Pipeline.DoesNotExist as exc:
            raise Http404("Pipeline không tồn tại.") from exc
        if pipeline.ctv.is_staff or pipeline.ctv.is_superuser:
            return Response(
                {
                    "success": False,
                    "message": "Tài khoản CTV không hợp lệ.",
                },
                status=409,
            )
        serializer = CTVPasswordSerializer(
            data=request.data,
            context={"ctv": pipeline.ctv},
        )
        serializer.is_valid(raise_exception=True)
        try:
            change_ctv_password(
                pipeline_id=pipeline_id,
                new_password=serializer.validated_data["new_password"],
                admin=request.user,
            )
        except ValidationError:
            return Response(
                {
                    "success": False,
                    "message": "Không thể đổi mật khẩu tài khoản này.",
                },
                status=409,
            )
        logger.info(
            "CTV password changed by Admin",
            extra={
                "admin_id": request.user.pk,
                "pipeline_id": str(pipeline_id),
            },
        )
        return Response({
            "success": True,
            "message": "Đổi mật khẩu CTV thành công.",
        })
