"""CTV-scoped publishing queue API. No dispatch or claim tokens exposed."""
from datetime import timedelta
import re
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.publishing.models import PublishingJob, PublishingAttempt
from modules.publishing.services.job_engine import (
    JobEngineError, JobConflict, enqueue_job, cancel_queued_job,
)
from modules.api.v1.albums.views import resolve_pipeline


class JobWriteThrottle(UserRateThrottle):
    rate = '20/min'


class JobListQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)
    state = serializers.ChoiceField(choices=PublishingJob.State.choices, required=False)
    search = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)


class NewJobRequest(serializers.Serializer):
    account_id = serializers.UUIDField()
    group_id = serializers.UUIDField()
    request_key = serializers.RegexField(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
    caption = serializers.CharField(max_length=5000, allow_blank=True, required=False, default='')
    scheduled_at = serializers.DateTimeField(required=False)
    max_attempts = serializers.IntegerField(min_value=1, max_value=5, default=3)

    def validate(self, attrs):
        raw = self.initial_data
        if not isinstance(raw, dict) or not set(raw).issubset(self.fields):
            raise serializers.ValidationError('Trường dữ liệu Job không hợp lệ.')
        if 'scheduled_at' in raw:
            stamp = raw['scheduled_at']
            if not isinstance(stamp, str) or not (
                stamp.endswith('Z') or
                re.search(r'[+-]\d\d:\d\d$', stamp)
            ):
                raise serializers.ValidationError({
                    'scheduled_at': 'Phải gửi thời gian ISO 8601 có múi giờ.',
                })
            at = attrs['scheduled_at']
            if at < timezone.now() - timedelta(minutes=2):
                raise serializers.ValidationError({
                    'scheduled_at': 'Thời gian đăng không được ở quá khứ.',
                })
            if at > timezone.now() + timedelta(days=366):
                raise serializers.ValidationError({
                    'scheduled_at': 'Chỉ cho phép đặt lịch trong 366 ngày.',
                })
        return attrs


def job_data(job):
    """Never include worker_id or claim_token in HTTP responses."""
    return {
        'id': str(job.pk),
        'pipeline_id': str(job.pipeline_id),
        'request_key': job.request_key,
        'state': job.state,
        'caption': job.caption,
        'account': {
            'id': str(job.facebook_account_id),
            'label': job.facebook_account.label,
        },
        'group': {
            'id': str(job.facebook_group_id),
            'name': job.facebook_group.name,
            'url': job.facebook_group.group_url,
        },
        'scheduled_at': job.scheduled_at.isoformat(),
        'next_run_at': job.next_run_at.isoformat(),
        'attempt_count': job.attempt_count,
        'max_attempts': job.max_attempts,
        'media_allocation_id': str(job.media_allocation_id) if job.media_allocation_id else None,
        'external_post_id': job.external_post_id or None,
        'error_code': job.error_code or None,
        'created_at': job.created_at.isoformat(),
        'updated_at': job.updated_at.isoformat(),
        'finalized_at': job.finalized_at.isoformat() if job.finalized_at else None,
    }


def check_payload(job_id, pipeline):
    job = (
        PublishingJob.objects
        .filter(pk=job_id, pipeline_id=pipeline.pk)
        .select_related('facebook_account', 'facebook_group')
        .first()
    )
    if job is None:
        raise Http404('Job không tồn tại.')
    return job


class PublishingJobListCreateAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [JobWriteThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        params = JobListQuery(data=request.query_params)
        params.is_valid(raise_exception=True)
        val = params.validated_data
        base = PublishingJob.objects.filter(pipeline_id=pipeline.pk)
        counts = base.aggregate(
            total=Count('id'),
            queued=Count('id', filter=Q(state=PublishingJob.State.QUEUED)),
            ready=Count('id', filter=Q(state=PublishingJob.State.READY)),
            uncertain=Count('id', filter=Q(state=PublishingJob.State.UNCERTAIN)),
            published=Count('id', filter=Q(state=PublishingJob.State.PUBLISHED)),
            failed=Count('id', filter=Q(state=PublishingJob.State.FAILED)),
        )
        queryset = base.select_related('facebook_account', 'facebook_group')
        if val.get('state'):
            queryset = queryset.filter(state=val['state'])
        if val.get('search'):
            search = val['search']
            queryset = queryset.filter(
                Q(caption__icontains=search) |
                Q(request_key__icontains=search) |
                Q(facebook_account__label__icontains=search) |
                Q(facebook_group__name__icontains=search)
            )
        queryset = queryset.order_by('-scheduled_at', '-id')
        pages = Paginator(queryset, val['page_size'])
        try:
            page = pages.page(val['page'])
        except EmptyPage:
            return Response({'success': False, 'message': 'Trang không tồn tại.'}, status=400)
        response = Response({
            'success': True,
            'data': [job_data(job) for job in page.object_list],
            'summary': counts,
            'pagination': {
                'page': page.number, 'page_size': val['page_size'],
                'total': pages.count, 'total_pages': pages.num_pages,
                'has_next': page.has_next(), 'has_previous': page.has_previous(),
            },
        })
        response['Cache-Control'] = 'private, no-store'
        return response

    def post(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        params = NewJobRequest(data=request.data)
        params.is_valid(raise_exception=True)
        val = params.validated_data
        # Fail fast if client selects a disconnected account, but the trusted
        # job engine is the authoritative tenant + state boundary.
        account = FacebookAccount.objects.filter(
            pk=val['account_id'], pipeline_id=pipeline.pk,
        ).first()
        group = FacebookGroup.objects.filter(
            pk=val['group_id'], pipeline_id=pipeline.pk,
        ).first()
        if account is None or group is None:
            raise Http404('Account hoặc Group không tồn tại.')
        # Idempotent replay is resolved by the engine even if the account later expires.
        if not PublishingJob.objects.filter(
            pipeline_id=pipeline.pk, request_key=val['request_key'],
        ).exists() and account.connection_status != FacebookAccount.ConnectionStatus.CONNECTED:
            raise ValidationError({'account_id': 'Tài khoản Facebook chưa kết nối.'})
        try:
            result = enqueue_job(
                pipeline_id=pipeline.pk,
                account_id=val['account_id'], group_id=val['group_id'],
                request_key=val['request_key'], caption=val['caption'],
                scheduled_at=val.get('scheduled_at'), max_attempts=val['max_attempts'],
            )
        except JobConflict as exc:
            return Response({'success': False, 'message': str(exc)}, status=409)
        except JobEngineError as exc:
            raise ValidationError({'job': str(exc)}) from exc
        job = check_payload(result['id'], pipeline)
        response = Response({'success': True, 'data': job_data(job)}, status=201)
        response['Cache-Control'] = 'private, no-store'
        return response


class PublishingJobDetailAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pipeline_id, job_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        job = check_payload(job_id, pipeline)
        attempts = list(
            PublishingAttempt.objects.filter(job=job).order_by('number')
            .values('number', 'state', 'started_at', 'finalized_at', 'media_allocation_id')
        )
        data = job_data(job)
        data['attempts'] = [
            {
                'number': row['number'],
                'state': row['state'],
                'started_at': row['started_at'].isoformat(),
                'finalized_at': row['finalized_at'].isoformat() if row['finalized_at'] else None,
                'media_allocation_id': str(row['media_allocation_id']) if row['media_allocation_id'] else None,
            }
            for row in attempts
        ]
        response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response


class PublishingJobCancelAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [JobWriteThrottle]

    def post(self, request, pipeline_id, job_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        if request.data not in ({}, None):
            return Response({'success': False, 'message': 'Không nhận tham số bổ sung.'}, status=400)
        check_payload(job_id, pipeline)
        try:
            cancel_queued_job(pipeline_id=pipeline.pk, job_id=job_id)
        except JobConflict as exc:
            return Response({'success': False, 'message': str(exc)}, status=409)
        except JobEngineError as exc:
            raise ValidationError({'job': str(exc)}) from exc
        job = check_payload(job_id, pipeline)
        response = Response({'success': True, 'data': job_data(job)})
        response['Cache-Control'] = 'private, no-store'
        return response
