"""Pipeline-scoped operational health snapshot for the CTV workspace.

Read-only: no systemd inspection, no credentials and no Facebook requests.
Failures never report a healthy status or leak database connection details.
"""
import logging

from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.operations_health import health_snapshot

logger = logging.getLogger(__name__)


class OperationsHealthQuery(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=250, default=100)


class OperationsHealthReadThrottle(UserRateThrottle):
    rate = '12/min'


class OperationsHealthAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [OperationsHealthReadThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = OperationsHealthQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            data = health_snapshot(
                pipeline_id=pipeline.pk,
                sample_limit=query.validated_data['limit'],
            )
        except Exception:
            # Avoid exporting database/DSN details to clients.
            logger.error('Operational health read failed for pipeline_id=%s', pipeline.pk)
            response = Response({
                'success': False,
                'message': 'Không đọc được trạng thái vận hành. Vui lòng thử lại.',
            }, status=503)
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response
