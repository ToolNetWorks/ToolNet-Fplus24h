"""Tenant-scoped alert inbox. GET is read-only; actions never alter jobs."""
import logging

from django.http import Http404
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.operational_alerts import (
    AlertError, AlertConflict, list_alerts, take_alert_action,
)

logger = logging.getLogger(__name__)


class AlertQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)
    state = serializers.ChoiceField(choices=['open', 'resolved', 'all'], default='open')


class AlertActionBody(serializers.Serializer):
    action = serializers.ChoiceField(choices=['acknowledge', 'snooze'])
    expected_version = serializers.IntegerField(min_value=1)
    snooze_minutes = serializers.IntegerField(min_value=15, max_value=1440,
                                              required=False)

    def validate(self, attrs):
        if attrs['action'] == 'snooze' and 'snooze_minutes' not in attrs:
            raise serializers.ValidationError({'snooze_minutes': 'Thiếu thời gian tạm ẩn.'})
        if attrs['action'] == 'acknowledge' and 'snooze_minutes' in attrs:
            raise serializers.ValidationError({'snooze_minutes': 'Không dùng khi xác nhận đã xem.'})
        return attrs


class AlertReadThrottle(UserRateThrottle):
    rate = '30/min'


class AlertWriteThrottle(UserRateThrottle):
    rate = '12/min'


def _respond(data, status=200):
    response = Response(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


class PublishingAlertsAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AlertReadThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = AlertQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            data = list_alerts(pipeline_id=pipeline.pk, **query.validated_data)
        except AlertError as exc:
            return _respond({'success': False, 'message': str(exc)}, status=400)
        except Exception:
            logger.error('Alert inbox failed pipeline_id=%s', pipeline.pk)
            return _respond({'success': False, 'message': 'Không thể đọc cảnh báo.'}, status=503)
        return _respond({'success': True, 'data': data})


class PublishingAlertActionAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AlertWriteThrottle]

    def post(self, request, pipeline_id, alert_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        body = AlertActionBody(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            data = take_alert_action(
                pipeline_id=pipeline.pk, alert_id=alert_id,
                actor=request.user, **body.validated_data,
            )
        except AlertConflict as exc:
            return _respond({'success': False, 'message': str(exc)}, status=409)
        except AlertError as exc:
            # Do not reveal whether an out-of-pipeline alert ID exists.
            if 'Không tìm thấy' in str(exc):
                raise Http404('Không tìm thấy cảnh báo.')
            return _respond({'success': False, 'message': str(exc)}, status=400)
        except Exception:
            logger.error('Alert action failed pipeline_id=%s', pipeline.pk)
            return _respond({'success': False, 'message': 'Không thể cập nhật cảnh báo.'}, status=503)
        return _respond({'success': True, 'data': data})


class PublishingAlertEventsAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AlertReadThrottle]

    def get(self, request, pipeline_id, alert_id):
        from modules.publishing.services.operational_alerts import alert_event_history
        pipeline = resolve_pipeline(request.user, pipeline_id)
        params = AlertEventQuery(data=request.query_params)
        params.is_valid(raise_exception=True)
        try:
            history = alert_event_history(pipeline_id=pipeline.pk, alert_id=alert_id,
                                          **params.validated_data)
        except AlertError as exc:
            if 'Không tìm thấy' in str(exc):
                raise Http404('Không tìm thấy cảnh báo.')
            return _respond({'success': False, 'message': str(exc)}, status=400)
        return _respond({'success': True, 'data': history})


class AlertEventQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)
