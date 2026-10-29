"""Read-only, sequential performance baseline; strict mode fails closed."""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from modules.publishing.services.performance_stability import performance_snapshot, PerformanceStabilityError


class Command(BaseCommand):
    help = 'Bounded read-only per-Pipeline baseline; never dispatches Facebook or creates Jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--repeats', type=int, default=3)
        parser.add_argument('--limit', type=int, default=25)
        parser.add_argument('--threshold-ms', type=int)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        try:
            data = performance_snapshot(
                pipeline_id=options['pipeline_id'], repeats=options['repeats'],
                limit=options['limit'], threshold_ms=options['threshold_ms'],
            )
        except PerformanceStabilityError as exc:
            raise CommandError(str(exc)) from exc
        except Exception:
            raise CommandError('Không thể đo hiệu năng; kiểm tra log nội bộ.') from None
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
        if options['strict'] and data['status'] != 'pass':
            raise CommandError('Baseline chưa đạt: ' + data['status'])
