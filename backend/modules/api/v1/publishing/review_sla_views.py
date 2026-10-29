"""Read-only aging of review cases, isolated per CTV Pipeline."""
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.review_sla import review_sla_snapshot, SLAQueryError


class ReviewSLAQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)
    filter_by = serializers.ChoiceField(
        choices=['all', 'overdue', 'critical', 'awaiting'], default='all',
    )


class ReviewSLAReadThrottle(UserRateThrottle):
    rate = '60/min'


class ReviewSLAAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReviewSLAReadThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = ReviewSLAQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            result = review_sla_snapshot(pipeline_id=pipeline.pk, **query.validated_data)
        except SLAQueryError as exc:
            response = Response({'success': False, 'message': str(exc)}, status=400)
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': result})
        response['Cache-Control'] = 'private, no-store'
        return response
