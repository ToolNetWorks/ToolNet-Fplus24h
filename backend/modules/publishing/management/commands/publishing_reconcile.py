"""Conservative reconciliation CLI; default is read-only inspection."""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from modules.pipelines.models import Pipeline
from modules.publishing.services.job_engine import sweep_expired_jobs
from modules.publishing.services.reconciliation import reconciliation_snapshot


class Command(BaseCommand):
    help = ('Inspect review-needed jobs. --quarantine-expired explicitly moves '
            'expired worker claims to UNCERTAIN; never retries or posts to Facebook.')

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--quarantine-expired', action='store_true')
        parser.add_argument('--page', type=int, default=1)
        parser.add_argument('--page-size', type=int, default=20)

    def handle(self, *args, **options):
        pipeline_id = options['pipeline_id']
        if not Pipeline.objects.filter(pk=pipeline_id).exists():
            raise CommandError('Pipeline không tồn tại.')
        if options['page'] < 1 or not 1 <= options['page_size'] <= 50:
            raise CommandError('page/page-size không hợp lệ.')
        quarantined = 0
        if options['quarantine_expired']:
            quarantined = sweep_expired_jobs(pipeline_id=pipeline_id)
        try:
            snapshot = reconciliation_snapshot(
                pipeline_id=pipeline_id, page=options['page'],
                page_size=options['page_size'],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps({
            'quarantined_expired_jobs': quarantined,
            'mode': 'explicit_quarantine' if options['quarantine_expired'] else 'read_only',
            **snapshot,
        }, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.WARNING('NO FACEBOOK DISPATCH OR AUTOMATIC RETRY.'))
