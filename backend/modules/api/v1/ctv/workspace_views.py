from django.db.models import Count, Q
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
class CTVWorkspaceAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user
        if (
            not user.is_active
            or user.is_staff
            or user.is_superuser
        ):
            return Response(
                {
                    "success": False,
                    "message": "Không có quyền truy cập Workspace CTV.",
                },
                status=403,
            )
        pipeline = (
            Pipeline.objects
            .select_related("ctv")
            .filter(ctv_id=user.pk)
            .first()
        )
        if pipeline is None:
            return Response(
                {
                    "success": False,
                    "message": "Tài khoản chưa được cấp Pipeline.",
                },
                status=403,
            )
        if pipeline.status != Pipeline.Status.ACTIVE:
            return Response(
                {
                    "success": False,
                    "message": "Pipeline đã bị khóa.",
                },
                status=403,
            )
        account_stats = (
            FacebookAccount.objects
            .filter(pipeline_id=pipeline.pk)
            .aggregate(
                total=Count("id"),
                connected=Count(
                    "id",
                    filter=Q(
                        connection_status=(
                            FacebookAccount
                            .ConnectionStatus.CONNECTED
                        )
                    ),
                ),
            )
        )
        response = Response({
            "success": True,
            "data": {
                "pipeline": {
                    "id": str(pipeline.pk),
                    "name": pipeline.name,
                    "status": pipeline.status,
                },
                "ctv": {
                    "id": user.pk,
                    "username": user.username,
                    "email": user.email,
                },
                "stats": {
                    "facebook_accounts": account_stats["total"],
                    "connected_accounts": account_stats["connected"],
                },
            },
        })
        response["Cache-Control"] = "private, no-store"
        return response
