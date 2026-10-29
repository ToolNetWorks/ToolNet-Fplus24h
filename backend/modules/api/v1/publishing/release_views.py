"""Tenant-isolated, read-only release evidence; never a production deploy API."""
import logging
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.release_readiness import release_snapshot

logger = logging.getLogger(__name__)


class ReleaseReadThrottle(UserRateThrottle):
    scope = 'release_read'
    rate = '2/min'


class PipelineReleaseReadinessAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReleaseReadThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        if request.query_params:
            response = Response({'success': False, 'message': 'Không nhận tham số tùy ý.'}, status=400)
            response['Cache-Control'] = 'private, no-store'
            return response
        try:
            snapshot = release_snapshot(pipeline_id=pipeline.pk, limit=50,
                                        include_performance=True)
        except Exception:
            logger.error('Release readiness query failed for pipeline_id=%s', pipeline.pk)
            response = Response({'success': False, 'message': 'Không thể đánh giá nghiệm thu.'}, status=503)
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': snapshot})
        response['Cache-Control'] = 'private, no-store'
        return response
