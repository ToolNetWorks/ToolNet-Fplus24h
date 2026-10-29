"""CTV-scoped review case API. Evidence is not publication verification."""
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.review_models import PublishingReviewCase
from modules.publishing.services.review_cases import (
    list_cases, get_case, open_case, take_action, CaseError, CaseConflict,
)


class ReviewWriteThrottle(UserRateThrottle):
    rate = '15/min'


class ReviewReadThrottle(UserRateThrottle):
    rate = '60/min'


class CaseListQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)
    status = serializers.ChoiceField(choices=PublishingReviewCase.Status.choices, required=False)
    job_id = serializers.UUIDField(required=False)


class CreateCaseSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()

    def validate(self, attrs):
        if not isinstance(self.initial_data, dict) or set(self.initial_data) != {'job_id'}:
            raise serializers.ValidationError('Chỉ nhận job_id.')
        return attrs


class CaseActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=(
        'assign_me', 'unassign', 'add_evidence', 'request_verification', 'close',
    ))
    expected_version = serializers.IntegerField(min_value=1)
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False, default='')
    evidence_url = serializers.URLField(max_length=1000, allow_blank=True, required=False, default='')

    def validate(self, attrs):
        if not isinstance(self.initial_data, dict) or not set(self.initial_data).issubset(self.fields):
            raise serializers.ValidationError('Trường thao tác hồ sơ không hợp lệ.')
        return attrs


def reply(data, code=200):
    response = Response({'success': True, 'data': data}, status=code)
    response['Cache-Control'] = 'private, no-store'
    return response


def failure(exc):
    return Response({'success': False, 'message': str(exc)}, status=(
        409 if isinstance(exc, CaseConflict) else 400
    ))


class ReviewCaseListCreateAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReviewWriteThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = CaseListQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            data = list_cases(pipeline_id=pipeline.pk, **query.validated_data)
        except CaseError as exc:
            return failure(exc)
        return reply(data)

    def post(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        form = CreateCaseSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            data, created = open_case(
                pipeline_id=pipeline.pk, job_id=form.validated_data['job_id'],
                actor=request.user,
            )
        except CaseError as exc:
            return failure(exc)
        return reply(data, 201 if created else 200)


class ReviewCaseDetailAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReviewReadThrottle]

    def get(self, request, pipeline_id, case_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        try:
            return reply(get_case(pipeline_id=pipeline.pk, case_id=case_id))
        except CaseError:
            return Response({'success': False, 'message': 'Không tìm thấy hồ sơ.'}, status=404)


class ReviewCaseActionAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReviewWriteThrottle]

    def post(self, request, pipeline_id, case_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        form = CaseActionSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            data = take_action(
                pipeline_id=pipeline.pk, case_id=case_id,
                actor=request.user, **form.validated_data,
            )
        except CaseError as exc:
            return failure(exc)
        return reply(data)
