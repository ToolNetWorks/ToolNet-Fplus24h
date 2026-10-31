import logging

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.api.v1.permissions import IsSuperAdmin
from modules.pipelines.models import Pipeline
from modules.pipelines.services import create_pipeline_with_ctv

from .serializers import PipelineCreateSerializer

logger = logging.getLogger(__name__)


class PipelineCreateAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        serializer = PipelineCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        pipeline = Pipeline(
            name=data["name"],
            status=data["status"],
        )

        try:
            pipeline = create_pipeline_with_ctv(
                pipeline=pipeline,
                username=data["ctv_username"],
                email=data["ctv_email"],
                password=data["ctv_password"],
                admin=request.user,
            )
        except ValidationError as exc:
            errors = (
                exc.message_dict
                if hasattr(exc, "message_dict")
                else exc.messages
            )
            return Response(
                {"success": False, "errors": errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IntegrityError:
            logger.warning(
                "Pipeline creation conflict",
                extra={"admin_id": request.user.pk},
            )
            return Response(
                {
                    "success": False,
                    "message": (
                        "Pipeline hoặc Username đã tồn tại."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        logger.info(
            "Pipeline created",
            extra={
                "admin_id": request.user.pk,
                "pipeline_id": str(pipeline.pk),
            },
        )

        return Response(
            {
                "success": True,
                "data": {
                    "id": str(pipeline.pk),
                    "name": pipeline.name,
                    "status": pipeline.status,
                    "ctv": {
                        "id": pipeline.ctv_id,
                        "username": pipeline.ctv.username,
                        "email": pipeline.ctv.email,
                    },
                },
            },
            status=status.HTTP_201_CREATED,
        )
