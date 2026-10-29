"""Explicit, local worker lease watchdog. Read-only by default."""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from modules.publishing.services.worker_reliability import (
    worker_guard_snapshot, quarantine_stale_leases, WorkerGuardError,
)


class Command(BaseCommand):
    help = 'Inspect stale Job leases. --quarantine-expired --confirm is explicit and never retries.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--quarantine-expired', action='store_true')
        parser.add_argument('--confirm', action='store_true')
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **opts):
        if opts['confirm'] and not opts['quarantine_expired']:
            raise CommandError('--confirm requires --quarantine-expired.')
        if opts['quarantine_expired'] and not opts['confirm']:
            raise CommandError('Mutation requires both --quarantine-expired and --confirm.')
        try:
            if opts['quarantine_expired']:
                data = quarantine_stale_leases(
                    pipeline_id=opts['pipeline_id'], limit=opts['limit'],
                )
                self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
                if not data['complete']:
                    raise CommandError('Some expired leases remain. Re-run explicitly.')
                return
            data = worker_guard_snapshot(
                pipeline_id=opts['pipeline_id'], limit=opts['limit'],
            )
        except WorkerGuardError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
        if opts['strict'] and data['summary']['expired_or_missing_lease']:
            raise CommandError('Expired or missing worker leases require reconciliation.')
