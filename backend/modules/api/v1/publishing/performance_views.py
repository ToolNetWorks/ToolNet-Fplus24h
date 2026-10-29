"""One-shot bounded performance inspection; tenant-scoped, read-only."""
import logging
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.performance_stability import performance_snapshot

logger = logging.getLogger(__name__)


class PerformanceReadThrottle(UserRateThrottle):
    # Never auto-poll; keeps resource-heavy repeated DB scans bounded.
    rate = '3/min'


class PipelinePerformanceAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [PerformanceReadThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        # Do not accept arbitrary iterations or thresholds from HTTP clients.
        if request.query_params:
            response = Response({'success': False, 'message': 'Không nhận tham số tùy ý.'}, status=400)
            response['Cache-Control'] = 'private, no-store'
            return response
        try:
            data = performance_snapshot(pipeline_id=pipeline.pk, repeats=1, limit=25)
        except Exception:
            logger.error('Performance inspection failed for pipeline_id=%s', pipeline.pk)
            response = Response({'success': False, 'message': 'Không thể kiểm tra hiệu năng.'}, status=503)
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response
