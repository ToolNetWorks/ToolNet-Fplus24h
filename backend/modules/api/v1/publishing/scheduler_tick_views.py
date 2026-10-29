"""Read-only CTV status endpoint. No background tick execution over HTTP."""
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.scheduler_tick import pipeline_tick_status


class SchedulerTickReadThrottle(UserRateThrottle):
    rate = '60/min'


class SchedulerTickStatusAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [SchedulerTickReadThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        result = pipeline_tick_status(pipeline_id=pipeline.pk)
        response = Response({'success': True, 'data': result})
        response['Cache-Control'] = 'private, no-store'
        return response
