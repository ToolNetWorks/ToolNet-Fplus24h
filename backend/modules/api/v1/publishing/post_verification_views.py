"""CTV-facing observation ledger. NEVER accepts trusted publication verification."""
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.verification_models import PostVerificationObservation
from modules.publishing.services.post_verification import (
    job_verification_snapshot, record_observation,
    VerificationError, VerificationConflict,
)


class VerificationThrottle(UserRateThrottle):
    rate = '20/min'


class VerificationQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)


class ObservationRequest(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    source = serializers.ChoiceField(choices=PostVerificationObservation.Source.choices)
    outcome = serializers.ChoiceField(choices=PostVerificationObservation.Outcome.choices)
    note = serializers.CharField(min_length=10, max_length=1000)
    evidence_url = serializers.URLField(max_length=800, allow_blank=True, required=False, default='')

    def validate(self, attrs):
        if not isinstance(self.initial_data, dict) or not set(self.initial_data).issubset(self.fields):
            # Explicitly disallow unknown/undocumented fields such as tokens,
            # force_published, facebook_payload, raw_har or visibility_proof.
            raise serializers.ValidationError('Chỉ nhận trường quan sát đã định nghĩa.')
        return attrs


def response(data, status=200):
    res = Response({'success': True, 'data': data}, status=status)
    res['Cache-Control'] = 'private, no-store'
    return res


def reject(exc):
    res = Response({'success': False, 'message': str(exc)}, status=(
        409 if isinstance(exc, VerificationConflict) else 400
    ))
    res['Cache-Control'] = 'private, no-store'
    return res


class PublishingJobVerificationAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [VerificationThrottle]

    def get(self, request, pipeline_id, job_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = VerificationQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            return response(job_verification_snapshot(
                pipeline_id=pipeline.pk, job_id=job_id, **query.validated_data,
            ))
        except VerificationError as exc:
            return reject(exc)

    def post(self, request, pipeline_id, job_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        form = ObservationRequest(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            entry, created = record_observation(
                pipeline_id=pipeline.pk, job_id=job_id,
                actor=request.user, **form.validated_data,
            )
        except VerificationError as exc:
            return reject(exc)
        return response(entry, 201 if created else 200)
