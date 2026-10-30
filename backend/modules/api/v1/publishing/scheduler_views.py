"""Tenant-scoped schedule / eligibility management; never dispatches Facebook posts."""
from datetime import timedelta

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.scheduler_models import (
    PipelineSchedule, AccountGroupEligibility, GroupHealth, ScheduledBatch,
)
from modules.publishing.services.scheduler import plan_schedule, ScheduleError


class ScheduleWriteThrottle(UserRateThrottle):
    rate = '15/min'


class ScheduleSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    interval_minutes = serializers.IntegerField(min_value=60, max_value=10080, default=1440)
    max_groups_per_run = serializers.IntegerField(min_value=1, max_value=50, default=10)
    timezone_name = serializers.CharField(max_length=64, default='Asia/Ho_Chi_Minh')
    start_at = serializers.DateTimeField()
    caption_template = serializers.CharField(max_length=5000, allow_blank=True, required=False)
    require_anonymous = serializers.BooleanField(default=True)
    require_nonmember = serializers.BooleanField(default=False)
    enabled = serializers.BooleanField(default=False)

    def validate(self, attrs):
        raw = self.initial_data
        if not isinstance(raw, dict) or not set(raw).issubset(self.fields):
            raise serializers.ValidationError('Trường lịch đăng không hợp lệ.')
        if 'enabled' in raw and type(raw['enabled']) is not bool:
            raise serializers.ValidationError({'enabled': 'Phải là boolean.'})
        if attrs.get('start_at') and attrs['start_at'] > timezone.now() + timedelta(days=366):
            raise serializers.ValidationError({'start_at': 'Tối đa 366 ngày trong tương lai.'})
        # Check if AI caption is enabled for this pipeline
        request = self.context.get('request')
        pipeline_id = self.context.get('pipeline_id')
        if pipeline_id and request:
            from modules.publishing.caption_models import PipelineCaptionSettings
            caption_settings = PipelineCaptionSettings.objects.filter(pipeline_id=pipeline_id).first()
            ai_enabled = caption_settings and caption_settings.enabled and caption_settings.auto_generate and caption_settings.auto_approve
            if not ai_enabled and not attrs.get('caption_template', '').strip():
                raise serializers.ValidationError({'caption_template': 'Cần caption/mẫu caption đã duyệt.'})
            if ai_enabled and not attrs.get('caption_template', '').strip():
                attrs['caption_template'] = ''
        elif not attrs.get('caption_template', '').strip():
            raise serializers.ValidationError({'caption_template': 'Cần caption/mẫu caption đã duyệt.'})
        return attrs


class EligibilitySerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    group_id = serializers.UUIDField()
    state = serializers.ChoiceField(choices=AccountGroupEligibility.State.choices)
    can_post_anonymous = serializers.BooleanField(default=False)
    can_post_nonmember = serializers.BooleanField(default=False)
    evidence_note = serializers.CharField(max_length=500, allow_blank=True, default='')
    valid_days = serializers.IntegerField(min_value=1, max_value=30, default=7)

    def validate(self, attrs):
        raw = self.initial_data
        if not isinstance(raw, dict) or not set(raw).issubset(self.fields):
            raise serializers.ValidationError('Trường điều kiện Group không hợp lệ.')
        if any(type(raw[field]) is not bool for field in ('can_post_anonymous', 'can_post_nonmember') if field in raw):
            raise serializers.ValidationError('Các quyền đăng phải là boolean.')
        if attrs['state'] == AccountGroupEligibility.State.VERIFIED and not attrs['evidence_note'].strip():
            raise serializers.ValidationError({'evidence_note': 'Cần mô tả kết quả kiểm tra thủ công.'})
        return attrs


class HealthSerializer(serializers.Serializer):
    group_id = serializers.UUIDField()
    state = serializers.ChoiceField(choices=GroupHealth.State.choices)
    reason_code = serializers.RegexField(r'^[A-Z0-9_]{0,80}$', allow_blank=True, default='')
    evidence_note = serializers.CharField(max_length=500, allow_blank=True, default='')
    review_after = serializers.DateTimeField(allow_null=True, required=False)

    def validate(self, attrs):
        raw = self.initial_data
        if not isinstance(raw, dict) or not set(raw).issubset(self.fields):
            raise serializers.ValidationError('Trường Group Health không hợp lệ.')
        if attrs['state'] == GroupHealth.State.UNAVAILABLE and not attrs['evidence_note'].strip():
            raise serializers.ValidationError({'evidence_note': 'Chỉ đánh dấu unavailable khi có bằng chứng.'})
        return attrs


def schedule_dict(obj):
    return {
        'id': str(obj.pk), 'pipeline_id': str(obj.pipeline_id),
        'name': obj.name, 'enabled': obj.enabled,
        'interval_minutes': obj.interval_minutes,
        'max_groups_per_run': obj.max_groups_per_run,
        'timezone_name': obj.timezone_name,
        'start_at': obj.start_at.isoformat(),
        'next_run_at': obj.next_run_at.isoformat(),
        'caption_template': obj.caption_template,
        'require_anonymous': obj.require_anonymous,
        'require_nonmember': obj.require_nonmember,
        'updated_at': obj.updated_at.isoformat(),
    }


def no_store(data, status=200):
    response = Response({'success': True, 'data': data}, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def require_schedule(pipeline, schedule_id):
    obj = PipelineSchedule.objects.filter(pk=schedule_id, pipeline_id=pipeline.pk).first()
    if obj is None:
        raise Http404('Lịch đăng không tồn tại trong Pipeline.')
    return obj


class PipelineScheduleListCreateAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [ScheduleWriteThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        return no_store([schedule_dict(row) for row in PipelineSchedule.objects.filter(
            pipeline=pipeline).order_by('-created_at')[:100]])

    def post(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        inp = ScheduleSerializer(data=request.data, context={'request': request, 'pipeline_id': pipeline_id})
        inp.is_valid(raise_exception=True)
        values = inp.validated_data
        # Explicitly disabled at creation; a later enable action is intentional.
        values['enabled'] = False
        with transaction.atomic():
            Pipeline.objects.select_for_update().get(pk=pipeline.pk)
            schedule = PipelineSchedule(pipeline=pipeline, next_run_at=values['start_at'], **values)
            schedule.save()
        return no_store(schedule_dict(schedule), 201)


class PipelineScheduleDetailAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [ScheduleWriteThrottle]

    def get(self, request, pipeline_id, schedule_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        return no_store(schedule_dict(require_schedule(pipeline, schedule_id)))

    def patch(self, request, pipeline_id, schedule_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        form = ScheduleSerializer(data=request.data, partial=True, context={'request': request, 'pipeline_id': pipeline_id})
        form.is_valid(raise_exception=True)
        data = form.validated_data
        if not data:
            return Response({'success': False, 'message': 'Thiếu dữ liệu cập nhật.'}, status=400)
        with transaction.atomic():
            Pipeline.objects.select_for_update().get(pk=pipeline.pk)
            schedule = PipelineSchedule.objects.select_for_update().filter(
                pk=schedule_id, pipeline_id=pipeline.pk).first()
            if schedule is None:
                raise Http404('Lịch đăng không tồn tại.')
            if 'start_at' in data and ScheduledBatch.objects.filter(schedule=schedule).exists():
                return Response({'success': False, 'message': 'Không thay đổi start_at sau khi tạo Batch.'}, status=409)
            if 'start_at' in data:
                schedule.next_run_at = data['start_at']
            for k, v in data.items():
                setattr(schedule, k, v)
            schedule.save()
        return no_store(schedule_dict(schedule))


class SchedulePreviewAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScheduleWriteThrottle]

    def get(self, request, pipeline_id, schedule_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        require_schedule(pipeline, schedule_id)
        try:
            return no_store(plan_schedule(schedule_id=schedule_id, commit=False))
        except ScheduleError as exc:
            return Response({'success': False, 'message': str(exc)}, status=409)


class ScheduleRunAPIView(APIView):
    """Explicit manual enqueue only. Never publishes or starts a daemon."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [ScheduleWriteThrottle]

    def post(self, request, pipeline_id, schedule_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        require_schedule(pipeline, schedule_id)
        if request.data not in ({}, None):
            return Response({'success': False, 'message': 'Không nhận tham số bổ sung.'}, status=400)
        try:
            return no_store(plan_schedule(schedule_id=schedule_id, commit=True))
        except ScheduleError as exc:
            return Response({'success': False, 'message': str(exc)}, status=409)


class ScheduleBatchListAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pipeline_id, schedule_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        require_schedule(pipeline, schedule_id)
        return no_store([
            {
                'id': str(row.pk), 'slot_at': row.slot_at.isoformat(),
                'assigned_count': row.assigned_count, 'skipped': row.skipped,
                'created_at': row.created_at.isoformat(),
            }
            for row in ScheduledBatch.objects.filter(
                schedule_id=schedule_id, pipeline_id=pipeline.pk
            ).order_by('-slot_at')[:50]
        ])


class AccountGroupEligibilityAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [ScheduleWriteThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        return no_store([{
            'account_id': str(row.account_id), 'group_id': str(row.group_id),
            'state': row.state,
            'can_post_anonymous': row.can_post_anonymous,
            'can_post_nonmember': row.can_post_nonmember,
            'verified_at': row.verified_at.isoformat() if row.verified_at else None,
            'expires_at': row.expires_at.isoformat() if row.expires_at else None,
            'evidence_note': row.evidence_note,
        } for row in AccountGroupEligibility.objects.filter(pipeline=pipeline).order_by('-updated_at')[:1000]])

    def post(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        form = EligibilitySerializer(data=request.data)
        form.is_valid(raise_exception=True)
        val = form.validated_data
        if not FacebookAccount.objects.filter(pk=val['account_id'], pipeline=pipeline).exists():
            raise Http404('Account không thuộc Pipeline.')
        if not FacebookGroup.objects.filter(pk=val['group_id'], pipeline=pipeline).exists():
            raise Http404('Group không thuộc Pipeline.')
        with transaction.atomic():
            Pipeline.objects.select_for_update().get(pk=pipeline.pk)
            now = timezone.now()
            verified = val['state'] == AccountGroupEligibility.State.VERIFIED
            row, created = AccountGroupEligibility.objects.update_or_create(
                pipeline=pipeline, account_id=val['account_id'], group_id=val['group_id'],
                defaults={
                    'state': val['state'],
                    'can_post_anonymous': val['can_post_anonymous'] if verified else False,
                    'can_post_nonmember': val['can_post_nonmember'] if verified else False,
                    'verified_at': now if verified else None,
                    'expires_at': now + timedelta(days=val['valid_days']) if verified else None,
                    'evidence_note': val['evidence_note'],
                },
            )
        return no_store({'id': str(row.pk), 'created': created, 'state': row.state})


class GroupSchedulingHealthAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [ScheduleWriteThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        return no_store([{
            'group_id': str(row.group_id), 'state': row.state,
            'reason_code': row.reason_code,
            'evidence_note': row.evidence_note,
            'review_after': row.review_after.isoformat() if row.review_after else None,
        } for row in GroupHealth.objects.filter(pipeline=pipeline).order_by('-updated_at')[:1000]])

    def post(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        form = HealthSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        val = form.validated_data
        if not FacebookGroup.objects.filter(pk=val['group_id'], pipeline=pipeline).exists():
            raise Http404('Group không thuộc Pipeline.')
        with transaction.atomic():
            Pipeline.objects.select_for_update().get(pk=pipeline.pk)
            row, created = GroupHealth.objects.update_or_create(
                pipeline=pipeline, group_id=val['group_id'],
                defaults={
                    'state': val['state'], 'reason_code': val['reason_code'],
                    'evidence_note': val['evidence_note'],
                    'review_after': val.get('review_after'),
                },
            )
        return no_store({'id': str(row.pk), 'created': created, 'state': row.state})
