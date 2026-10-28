from django.db.models import Count, Q

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication

from modules.pipelines.models import Pipeline
from .permissions import IsSuperAdmin


class AdminOverviewView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        stats = Pipeline.objects.aggregate(
            total_pipelines=Count("pk"),
            active_pipelines=Count(
                "pk",
                filter=Q(status=Pipeline.Status.ACTIVE),
            ),
            disabled_pipelines=Count(
                "pk",
                filter=Q(status=Pipeline.Status.DISABLED),
            ),
            total_ctv=Count("ctv_id", distinct=True),
        )

        return Response({
            "success": True,
            "data": stats,
        })
