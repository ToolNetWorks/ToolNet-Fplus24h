from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.facebook_publishing.models import RulesReview
from modules.facebook_publishing.services.rules_review import decide_review, review_payload, RulesReviewConflict


class RulesThrottle(UserRateThrottle):
    rate = '30/min'


class RulesDecision(serializers.Serializer):
    digest = serializers.RegexField(r'^[0-9a-f]{64}$')
    decision = serializers.ChoiceField(choices=('approve', 'reject'))
    consent = serializers.BooleanField(default=False)
    answers = serializers.ListField(child=serializers.CharField(max_length=500), max_length=10, default=list)

    def validate(self, attrs):
        if not isinstance(self.initial_data, dict) or set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError('Dữ liệu không hợp lệ.')
        return attrs


def no_store(data, status=200):
    response = Response(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


class RulesReviewAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [RulesThrottle]

    def get(self, request, pipeline_id, job_id=None):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        rows = RulesReview.objects.filter(worker_job__pipeline=pipeline,
            state__in=[RulesReview.State.PENDING, RulesReview.State.APPROVED,
                       RulesReview.State.SUBMITTING]).select_related(
                           'worker_job__account', 'worker_job__group').order_by('-created_at')
        if job_id is not None:
            rows = rows.filter(worker_job__job_id=job_id)
        rows = rows[:50]
        return no_store({'success': True, 'data': [review_payload(row) for row in rows]})

    def post(self, request, pipeline_id, job_id=None):
        if job_id is None:
            return no_store({'success': False, 'message': 'Thiếu Job.'}, 405)
        pipeline = resolve_pipeline(request.user, pipeline_id)
        form = RulesDecision(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            state = decide_review(pipeline_id=pipeline.pk, job_id=job_id,
                                  actor=request.user, **form.validated_data)
        except RulesReviewConflict as exc:
            return no_store({'success': False, 'message': str(exc)}, 409)
        return no_store({'success': True, 'data': {'state': state}})
