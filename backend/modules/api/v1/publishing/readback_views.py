"""Read-only, tenant-isolated publication readback audit endpoint.

POST/PUT/DELETE intentionally not implemented. No readback execution here.
"""
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.authorized_readback import readback_snapshot, ReadbackError


class ReadbackReadThrottle(UserRateThrottle):
    rate = '60/min'


class ReadbackQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)


class PublishingJobReadbackAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReadbackReadThrottle]

    def get(self, request, pipeline_id, job_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = ReadbackQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            data = readback_snapshot(
                pipeline_id=pipeline.pk, job_id=job_id, **query.validated_data,
            )
        except ReadbackError as exc:
            response = Response({'success': False, 'message': str(exc)}, status=404)
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response
