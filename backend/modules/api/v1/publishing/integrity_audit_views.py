"""CTV-read-only, per-Pipeline integrity audit; never returns secrets."""
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.integrity_audit import (
    integrity_snapshot, IntegrityAuditError,
)


class IntegrityAuditThrottle(UserRateThrottle):
    rate = '12/min'


class AuditQuery(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=500, default=100)


class PublishingIntegrityAuditAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [IntegrityAuditThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = AuditQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            audit = integrity_snapshot(
                pipeline_id=pipeline.pk, sample_limit=query.validated_data['limit'],
            )
        except IntegrityAuditError as exc:
            response = Response({'success': False, 'message': str(exc)}, status=400)
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': audit})
        response['Cache-Control'] = 'private, no-store'
        return response
