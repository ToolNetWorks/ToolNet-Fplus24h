"""Operator-only, read-only consistency audit. No external calls."""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from modules.publishing.services.integrity_audit import (
    integrity_snapshot, IntegrityAuditError,
)


class Command(BaseCommand):
    help = 'Read-only Pipeline consistency check. --strict fails on findings or partial scans.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--limit', type=int, default=250)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        try:
            result = integrity_snapshot(
                pipeline_id=options['pipeline_id'], sample_limit=options['limit'],
            )
        except IntegrityAuditError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if options['strict'] and result['status'] != 'consistent':
            raise CommandError('Không đạt kiểm toán: có vấn đề hoặc chưa quét đủ dữ liệu.')
