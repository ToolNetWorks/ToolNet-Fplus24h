"""Opt-in generation of queued captions. Default preview never contacts an AI."""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.caption_models import PipelineCaptionSettings, JobCaption
from modules.publishing.services.caption_engine import generate_job_caption, CaptionError


class Command(BaseCommand):
    help = 'Preview pending captions or explicitly --generate them. Never posts Facebook.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', required=True, type=uuid.UUID)
        parser.add_argument('--limit', type=int, default=5)
        parser.add_argument('--generate', action='store_true')

    def handle(self, *args, **opts):
        if not 1 <= opts['limit'] <= 20:
            raise CommandError('Limit phải từ 1 đến 20.')
        pipeline_id = opts['pipeline_id']
        cfg = PipelineCaptionSettings.objects.filter(pipeline_id=pipeline_id,
                     enabled=True, auto_generate=True).first()
        if not cfg or not Pipeline.objects.filter(pk=pipeline_id,
                                                 status=Pipeline.Status.ACTIVE).exists():
            raise CommandError('Pipeline chưa bật tạo caption tự động.')
        qs = (PublishingJob.objects.filter(pipeline_id=pipeline_id, state='queued',
                    attempt_count=0)
              .filter(ai_caption__isnull=True)
              .order_by('scheduled_at', 'pk')[:opts['limit']])
        ids = list(qs.values_list('pk', flat=True))
        result = {'mode': 'generate' if opts['generate'] else 'preview',
                  'pipeline_id': str(pipeline_id), 'candidate_count': len(ids),
                  'items': [], 'facebook_posting': False}
        for job_id in ids:
            if not opts['generate']:
                result['items'].append({'job_id': str(job_id), 'status': 'pending'})
                continue
            try:
                record = generate_job_caption(pipeline_id=pipeline_id, job_id=job_id)
                result['items'].append({'job_id': str(job_id), 'status': record['state']})
            except CaptionError:
                result['items'].append({'job_id': str(job_id), 'status': 'failed'})
        self.stdout.write(json.dumps(result, ensure_ascii=False))
        if any(item['status'] == 'failed' for item in result['items']):
            raise CommandError('Một số caption không tạo được; xem cấu hình AI.')
