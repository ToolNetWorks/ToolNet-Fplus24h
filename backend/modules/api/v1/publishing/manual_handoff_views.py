"""Explicit human Facebook Group composer handoff; no Facebook requests."""
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.manual_handoff_models import (
    ManualPublishingHandoff as Handoff,
)
from modules.publishing.services.manual_handoff import (
    get_handoff, prepare_handoff, mutate_handoff, list_handoff_queue,
    HandoffError, HandoffConflict,
)


class ManualHandoffThrottle(UserRateThrottle):
    rate = '15/min'


class ManualAction(serializers.Serializer):
    action = serializers.ChoiceField(choices=('prepare', 'open', 'report', 'abandon'))
    expected_version = serializers.IntegerField(min_value=1, required=False)
    outcome = serializers.ChoiceField(choices=(
        'submitted_reported', 'pending_reported',
        'rejected_reported', 'inconclusive',
    ), required=False)
    note = serializers.CharField(max_length=500, allow_blank=True, required=False, default='')

    def validate(self, values):
        raw = self.initial_data
        if not isinstance(raw, dict) or set(raw) - set(self.fields):
            raise serializers.ValidationError('Không nhận dữ liệu ngoài danh sách cho phép.')
        action = values['action']
        if action == 'prepare' and len(raw) != 1:
            raise serializers.ValidationError('Prepare không nhận dữ liệu bổ sung.')
        if action != 'prepare' and 'expected_version' not in values:
            raise serializers.ValidationError('Thiếu expected_version.')
        if action == 'report' and 'outcome' not in values:
            raise serializers.ValidationError('Thiếu trạng thái quan sát.')
        if action != 'report' and ('outcome' in values or 'note' in raw):
            raise serializers.ValidationError('Trạng thái và ghi chú chỉ dành cho report.')
        return values


class ManualHandoffAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [ManualHandoffThrottle]

    def get(self, request, pipeline_id, job_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        try:
            data = get_handoff(pipeline_id=pipeline.pk, job_id=job_id)
        except HandoffError as exc:
            return self._error(str(exc), 404)
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response

    def post(self, request, pipeline_id, job_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        form = ManualAction(data=request.data)
        form.is_valid(raise_exception=True)
        value = form.validated_data
        try:
            if value['action'] == 'prepare':
                existed = Handoff.objects.filter(
                    job__pk=job_id, pipeline=pipeline).exists()
                data = prepare_handoff(pipeline_id=pipeline.pk, job_id=job_id,
                                       actor=request.user)
                status_code = 200 if existed else 201
            else:
                data = mutate_handoff(
                    pipeline_id=pipeline.pk, job_id=job_id,
                    actor=request.user, action=value['action'],
                    expected_version=value['expected_version'],
                    outcome=value.get('outcome', ''), note=value.get('note', ''),
                )
                status_code = 200
        except HandoffConflict as exc:
            return self._error(str(exc), 409)
        except HandoffError as exc:
            return self._error(str(exc), 400)
        response = Response({'success': True, 'data': data},
                            status=status_code)
        response['Cache-Control'] = 'private, no-store'
        return response

    @staticmethod
    def _error(message, status):
        response = Response({'success': False, 'message': message}, status=status)
        response['Cache-Control'] = 'private, no-store'
        return response


class HandoffQueueThrottle(UserRateThrottle):
    rate = '60/min'


class HandoffQueueQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)
    status = serializers.ChoiceField(choices=[
        ('awaiting_ai', 'Chờ AI'),
        ('approved', 'Đã duyệt'),
        ('awaiting_handoff', 'Chờ bàn giao'),
        ('processing', 'Đang xử lý'),
        ('awaiting_verification', 'Chờ xác minh'),
        ('published', 'Thành công'),
        ('failed', 'Thất bại'),
    ], required=False, allow_blank=True)

    def validate(self, attrs):
        raw = self.initial_data
        if not isinstance(raw, dict) or not set(raw).issubset({
            'page', 'page_size', 'status',
        }):
            raise serializers.ValidationError('Chỉ nhận page, page_size, status.')
        return attrs


class HandoffQueueAPIView(APIView):
    """CTV-facing list of all publishing jobs with unified 7-step status.

    Read-only; never exposes claim_token, worker_id, or credentials.
    Only PREPARED handoff can be mutated (via the per-job endpoint).
    """
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [HandoffQueueThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = HandoffQueueQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        val = query.validated_data
        try:
            data = list_handoff_queue(
                pipeline_id=pipeline.pk,
                page=val['page'],
                page_size=val['page_size'],
                status_filter=val.get('status') or None,
            )
        except HandoffError as exc:
            response = Response(
                {'success': False, 'message': str(exc)},
                status=400,
            )
            response['Cache-Control'] = 'private, no-store'
            return response
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response
