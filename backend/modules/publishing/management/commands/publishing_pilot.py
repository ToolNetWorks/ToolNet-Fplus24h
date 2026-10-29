"""Explicitly read-only per-Pipeline pilot readiness report."""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from modules.publishing.services.pilot_readiness import (
    pilot_readiness_snapshot, PilotReadinessError,
)


class Command(BaseCommand):
    help = 'Read-only Pilot readiness; NEVER submits Facebook posts.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        try:
            result = pilot_readiness_snapshot(
                pipeline_id=options['pipeline_id'], limit=options['limit'],
            )
        except PilotReadinessError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if options['strict'] and result['status'] != 'ready_for_manual_pilot':
            raise CommandError('Pilot chưa có Job đáp ứng đầy đủ điều kiện để kiểm thử thủ công.')
