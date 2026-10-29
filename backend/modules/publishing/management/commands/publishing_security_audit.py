"""Scoped read-only tenant isolation audit; no secrets printed."""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from modules.publishing.services.security_audit import security_snapshot, SecurityAuditError


class Command(BaseCommand):
    help = 'Read-only security audit for one Pipeline. Does not certify production security.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        try:
            data = security_snapshot(pipeline_id=options['pipeline_id'], limit=options['limit'])
        except SecurityAuditError as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            # No raw SQL/DB exception (may contain connection details).
            raise CommandError('Security audit failed; inspect server logs privately.') from None
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
        if options['strict'] and data['status'] != 'consistent':
            raise CommandError('Audit incomplete or security finding detected.')
