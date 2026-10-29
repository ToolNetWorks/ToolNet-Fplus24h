"""Read-only tenant-scoped reconciliation API; never confirms Facebook posting."""
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.reconciliation import reconciliation_snapshot


class ReconciliationReadThrottle(UserRateThrottle):
    rate = '60/min'


class ReconciliationQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)


class PublishingReconciliationAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReconciliationReadThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        params = ReconciliationQuery(data=request.query_params)
        params.is_valid(raise_exception=True)
        try:
            data = reconciliation_snapshot(
                pipeline_id=pipeline.pk, **params.validated_data,
            )
        except ValueError as exc:
            return Response({'success': False, 'message': str(exc)}, status=400)
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response
