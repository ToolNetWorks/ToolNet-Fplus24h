"""Read-only scoped CTV pilot readiness; does not authorize Facebook actions."""
import logging
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.pilot_readiness import (
    pilot_readiness_snapshot, PilotReadinessError,
)

logger = logging.getLogger(__name__)


class PilotReadThrottle(UserRateThrottle):
    rate = '12/min'


class PilotQuery(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class PublishingPilotReadinessAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [PilotReadThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = PilotQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            data = pilot_readiness_snapshot(
                pipeline_id=pipeline.pk, limit=query.validated_data['limit'],
            )
        except PilotReadinessError as exc:
            response = Response({'success': False, 'message': str(exc)}, status=400)
            response['Cache-Control'] = 'private, no-store'
            return response
        except Exception:
            logger.exception('Pilot readiness failed for pipeline_id=%s', pipeline.pk)
            response = Response({'success': False, 'message': 'Không đọc được kiểm thử Pilot.'}, status=503)
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response
