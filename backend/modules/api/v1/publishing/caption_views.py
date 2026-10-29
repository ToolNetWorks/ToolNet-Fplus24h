"""Tenant-scoped caption Library + Admin-only destination lock + Job drafting."""
from django.http import Http404
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.caption_models import PipelineCaptionSettings, CaptionSample, JobCaption
from modules.publishing.services.caption_engine import (
    CaptionError, CaptionConflict, settings_payload, sample_payload,
    caption_payload, update_settings, create_sample, generate_job_caption,
    approve_job_caption, reject_job_caption,
)


class CaptionReadThrottle(UserRateThrottle):
    rate = '30/min'


class CaptionWriteThrottle(UserRateThrottle):
    rate = '10/min'


class CaptionGenerateThrottle(UserRateThrottle):
    rate = '4/min'


def respond(data, status=200):
    response = Response({'success': True, 'data': data}, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def fail(exc):
    response = Response({'success': False, 'message': str(exc)},
                        status=409 if isinstance(exc, CaptionConflict) else 400)
    response['Cache-Control'] = 'private, no-store'
    return response


class ConfigForm(serializers.Serializer):
    destination = serializers.CharField(max_length=64)
    enabled = serializers.BooleanField()
    auto_generate = serializers.BooleanField()
    auto_approve = serializers.BooleanField()
    writing_guidance = serializers.CharField(max_length=2000, required=False,
                                                allow_blank=True, default='')


class CaptionSettingsAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [CaptionWriteThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        cfg = PipelineCaptionSettings.objects.filter(pipeline=pipeline).first()
        return respond(settings_payload(cfg))

    def put(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        if not (request.user.is_superuser and request.user.is_staff):
            raise Http404('Không có quyền sửa khóa trang đích.')
        form = ConfigForm(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            data = update_settings(pipeline_id=pipeline.pk, actor=request.user,
                                   **form.validated_data)
        except CaptionError as exc:
            return fail(exc)
        return respond(data)


class SampleForm(serializers.Serializer):
    text = serializers.CharField(min_length=8, max_length=1500, trim_whitespace=True)


class CaptionSamplesAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [CaptionWriteThrottle]

    def get(self, request, pipeline_id):
        pipe = resolve_pipeline(request.user, pipeline_id)
        try:
            page = int(request.query_params.get('page', '1'))
        except (ValueError, TypeError):
            return fail(CaptionError('Trang không hợp lệ.'))
        if not 1 <= page <= 100000:
            return fail(CaptionError('Trang không hợp lệ.'))
        query = CaptionSample.objects.filter(pipeline=pipe).order_by('-created_at', '-pk')
        total = query.count()
        rows = query[(page - 1) * 30:page * 30]
        return respond({'total': total, 'page': page,
                        'items': [sample_payload(row) for row in rows]})

    def post(self, request, pipeline_id):
        pipe = resolve_pipeline(request.user, pipeline_id)
        form = SampleForm(data=request.data)
        form.is_valid(raise_exception=True)
        try:
            data = create_sample(pipeline_id=pipe.pk, actor=request.user,
                                 text=form.validated_data['text'])
        except CaptionError as exc:
            return fail(exc)
        return respond(data, 201)


class SampleUpdateForm(serializers.Serializer):
    text = serializers.CharField(min_length=8, max_length=1500, trim_whitespace=True, required=False)
    is_active = serializers.BooleanField(required=False)


class CaptionSampleDetailAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [CaptionWriteThrottle]

    def patch(self, request, pipeline_id, sample_id):
        pipe = resolve_pipeline(request.user, pipeline_id)
        form = SampleUpdateForm(data=request.data)
        form.is_valid(raise_exception=True)
        if not isinstance(request.data, dict) or not form.validated_data or \
           set(request.data) - {'text', 'is_active'}:
            return fail(CaptionError('Chỉ nhận nội dung mẫu hoặc trạng thái hoạt động.'))
        row = CaptionSample.objects.filter(pk=sample_id, pipeline=pipe).first()
        if row is None:
            raise Http404('Mẫu không tồn tại.')
        for key, value in form.validated_data.items():
            setattr(row, key, value)
        row.full_clean()
        row.save()
        return respond(sample_payload(row))

    def delete(self, request, pipeline_id, sample_id):
        pipe = resolve_pipeline(request.user, pipeline_id)
        count, _ = CaptionSample.objects.filter(pk=sample_id, pipeline=pipe).delete()
        if not count:
            raise Http404('Mẫu không tồn tại.')
        return respond({'deleted': True})


class CaptionJobListAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [CaptionReadThrottle]

    def get(self, request, pipeline_id):
        pipe = resolve_pipeline(request.user, pipeline_id)
        jobs = PublishingJob.objects.filter(pipeline=pipe).select_related(
            'facebook_group', 'ai_caption').order_by('-scheduled_at', '-pk')[:50]
        data = []
        for job in jobs:
            record = JobCaption.objects.filter(job=job, pipeline=pipe).first()
            data.append({'job_id': str(job.pk), 'group': job.facebook_group.name,
                         'scheduled_at': job.scheduled_at.isoformat(),
                         'job_state': job.state,
                         'caption': caption_payload(record) if record else None})
        return respond({'items': data, 'limit': 50})


class CaptionJobAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [CaptionGenerateThrottle]

    def get(self, request, pipeline_id, job_id):
        pipe = resolve_pipeline(request.user, pipeline_id)
        if not PublishingJob.objects.filter(pk=job_id, pipeline=pipe).exists():
            raise Http404('Job không tồn tại.')
        record = JobCaption.objects.filter(job_id=job_id, pipeline=pipe).first()
        return respond(caption_payload(record) if record else None)

    def post(self, request, pipeline_id, job_id):
        pipe = resolve_pipeline(request.user, pipeline_id)
        if not PublishingJob.objects.filter(pk=job_id, pipeline=pipe).exists():
            raise Http404('Job không tồn tại.')
        action = request.data.get('action') if isinstance(request.data, dict) else None
        if action not in ('generate', 'approve', 'reject'):
            return fail(CaptionError('Hành động không hợp lệ.'))
        try:
            if action == 'generate':
                if set(request.data) != {'action'}:
                    raise CaptionError('Generate không nhận trường khác.')
                data = generate_job_caption(pipeline_id=pipe.pk, job_id=job_id,
                                            actor=request.user)
            else:
                if not isinstance(request.data.get('revision'), int) or \
                        isinstance(request.data.get('revision'), bool):
                    raise CaptionError('Cần số phiên bản revision hợp lệ.')
                if action == 'approve':
                    if set(request.data) - {'action', 'revision', 'text'}:
                        raise CaptionError('Trường không hợp lệ.')
                    data = approve_job_caption(
                        pipeline_id=pipe.pk, job_id=job_id, actor=request.user,
                        expected_revision=request.data['revision'],
                        text=request.data.get('text'))
                else:
                    if set(request.data) != {'action', 'revision'}:
                        raise CaptionError('Trường không hợp lệ.')
                    data = reject_job_caption(pipeline_id=pipe.pk, job_id=job_id,
                        actor=request.user, expected_revision=request.data['revision'])
        except CaptionError as exc:
            return fail(exc)
        return respond(data)
