"""Read-only by default; explicit execution with server-configured provider only.

No Facebook private API, cookies or HAR replay; no provider is shipped.
"""
import json
import uuid
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from modules.publishing.services.authorized_readback import (
    readback_snapshot, run_authorized_readback, ReadbackError,
)


class Command(BaseCommand):
    help = 'Inspect trusted readback ledger; --execute requires explicitly configured approved provider.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--job-id', type=uuid.UUID, required=True)
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--request-key', type=uuid.UUID)

    def handle(self, *args, **options):
        pipeline_id, job_id = options['pipeline_id'], options['job_id']
        if options['request_key'] and not options['execute']:
            raise CommandError('--request-key chỉ sử dụng cùng --execute.')
        if options['execute']:
            if not options['request_key']:
                raise CommandError('--execute cần --request-key UUID rõ ràng.')
            if getattr(settings, 'TOOLNET_PUBLICATION_VERIFIER_ENABLED', False) is not True:
                raise CommandError('Bộ xác minh độc lập chưa được bật.')
            provider_path = getattr(settings, 'TOOLNET_PUBLICATION_READBACK_PROVIDER', '')
            if not provider_path:
                raise CommandError('Chưa cấu hình provider đọc lại được cấp phép.')
            try:
                provider_factory = import_string(provider_path)
                adapter = provider_factory()
                decision = run_authorized_readback(
                    pipeline_id=pipeline_id, job_id=job_id,
                    adapter=adapter, request_key=options['request_key'],
                )
            except (ReadbackError, ImportError, TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(json.dumps({'decision': decision}, ensure_ascii=False, indent=2))
        try:
            snapshot = readback_snapshot(pipeline_id=pipeline_id, job_id=job_id)
        except ReadbackError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(snapshot, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.WARNING(
            'No provider is shipped. Observation/HAR is NEVER verified publication.'
        ))
