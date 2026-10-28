from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.pipelines.models import Pipeline
class AuthLandingAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user
        if not user.is_active:
            return Response({
                "success": False,
                "message": "Tài khoản đã bị vô hiệu hóa.",
            }, status=403)
        if user.is_superuser and user.is_staff:
            response = Response({
                "success": True,
                "data": {
                    "role": "admin",
                    "redirect_to": "/",
                    "pipeline_id": None,
                },
            })
            response["Cache-Control"] = "private, no-store"
            return response
        if user.is_staff or user.is_superuser:
            return Response({
                "success": False,
                "message": "Tài khoản không được cấp quyền Workspace.",
            }, status=403)
        pipeline = Pipeline.objects.filter(
            ctv_id=user.pk,
        ).only(
            "id",
            "status",
        ).first()
        if pipeline is None:
            return Response({
                "success": False,
                "message": "Tài khoản chưa được gắn Pipeline.",
            }, status=403)
        if pipeline.status != Pipeline.Status.ACTIVE:
            return Response({
                "success": False,
                "message": "Pipeline đang bị khóa.",
            }, status=403)
        response = Response({
            "success": True,
            "data": {
                "role": "ctv",
                "redirect_to": "/workspace/",
                "pipeline_id": str(pipeline.pk),
            },
        })
        response["Cache-Control"] = "private, no-store"
        return response
