"""CTV read-only view of worker lease anomalies, scoped to one Pipeline."""
import logging
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.worker_reliability import worker_guard_snapshot, WorkerGuardError

logger = logging.getLogger(__name__)


class WorkerGuardQuery(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=50, default=20)


class WorkerGuardThrottle(UserRateThrottle):
    rate = '12/min'


class WorkerGuardAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [WorkerGuardThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = WorkerGuardQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            data = worker_guard_snapshot(
                pipeline_id=pipeline.pk, **query.validated_data,
            )
        except WorkerGuardError as exc:
            response = Response({'success': False, 'message': str(exc)}, status=400)
            response['Cache-Control'] = 'private, no-store'
            return response
        except Exception:
            logger.error('Worker guard snapshot failed pipeline=%s', pipeline.pk)
            response = Response({'success': False, 'message': 'Không thể đọc trạng thái Worker.'}, status=503)
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response
