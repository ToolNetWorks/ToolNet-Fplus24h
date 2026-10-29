"""Read-only verification inspection: cannot confirm posts or contact Facebook."""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from modules.publishing.services.post_verification import (
    job_verification_snapshot, VerificationError,
)


class Command(BaseCommand):
    help = 'Inspect human observations and trusted receipt (read only).'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--job-id', type=uuid.UUID, required=True)
        parser.add_argument('--page', type=int, default=1)

    def handle(self, *args, **options):
        try:
            data = job_verification_snapshot(
                pipeline_id=options['pipeline_id'], job_id=options['job_id'],
                page=options['page'],
            )
        except VerificationError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
        self.stdout.write(self.style.WARNING(
            'READ ONLY; HAR/HTTP 200 IS NOT PROOF; NO FACEBOOK REQUEST OR RETRY.'
        ))
