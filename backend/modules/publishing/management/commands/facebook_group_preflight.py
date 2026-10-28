"""Run a sanitized, read-only Facebook Group preflight by IDs."""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.http import Http404

from modules.publishing.adapters.facebook_groups import build_group_preflight


class Command(BaseCommand):
    help = "Inspect Facebook Group publishing readiness; no external calls."

    def add_arguments(self, parser):
        parser.add_argument("--pipeline-id", required=True, type=uuid.UUID)
        parser.add_argument("--job-id", required=True, type=uuid.UUID)

    def handle(self, *args, **options):
        try:
            result = build_group_preflight(
                pipeline_id=options["pipeline_id"],
                job_id=options["job_id"],
            )
        except Http404 as exc:
            raise CommandError("Pipeline/Job not found.") from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
