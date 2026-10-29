"""Read-only command for checking aged review cases; no external verification."""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from modules.pipelines.models import Pipeline
from modules.publishing.services.review_sla import review_sla_snapshot, SLAQueryError


class Command(BaseCommand):
    help = 'Read-only SLA and evidence-readiness report; never changes Job or Facebook state.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--page', type=int, default=1)
        parser.add_argument('--page-size', type=int, default=20)
        parser.add_argument('--filter', dest='filter_by',
                            choices=['all', 'overdue', 'critical', 'awaiting'], default='all')

    def handle(self, *args, **options):
        if not Pipeline.objects.filter(pk=options['pipeline_id']).exists():
            raise CommandError('Pipeline không tồn tại.')
        try:
            report = review_sla_snapshot(
                pipeline_id=options['pipeline_id'],
                page=options['page'], page_size=options['page_size'],
                filter_by=options['filter_by'],
            )
        except SLAQueryError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.WARNING('READ ONLY. NO FACEBOOK CHECK, NO JOB STATE CHANGE.'))
