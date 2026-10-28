"""Authenticated, tenant-scoped, read-only Facebook Group preflight API."""
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.adapters.facebook_groups import build_group_preflight


class GroupPreflightThrottle(UserRateThrottle):
    rate = "20/min"


class FacebookGroupPreflightAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [GroupPreflightThrottle]

    def get(self, request, pipeline_id, job_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        data = build_group_preflight(
            pipeline_id=pipeline.pk, job_id=job_id,
        )
        response = Response({"success": True, "data": data})
        response["Cache-Control"] = "private, no-store"
        return response
