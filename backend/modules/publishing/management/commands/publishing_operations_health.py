"""Read-only operational check; --strict returns nonzero on any alert."""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from modules.publishing.services.operations_health import health_snapshot, OperationsHealthError


class Command(BaseCommand):
    help = 'Read-only production health of one Pipeline (no Facebook I/O).'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--limit', type=int, default=250)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        try:
            result = health_snapshot(pipeline_id=options['pipeline_id'], sample_limit=options['limit'])
        except Exception:
            # Never print database exception details that might contain DSNs or credentials.
            raise CommandError('Operational health check failed; inspect server logs securely.') from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if options['strict'] and result['status'] != 'healthy':
            raise CommandError('Operational health requires attention.')
