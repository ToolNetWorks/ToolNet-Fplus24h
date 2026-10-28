"""Explicit one-slot Scheduler runner; defaults to no-write preview."""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from modules.publishing.services.scheduler import plan_schedule, ScheduleError


class Command(BaseCommand):
    help = 'Preview one Pipeline schedule slot or explicitly enqueue Jobs; NEVER post to Facebook.'

    def add_arguments(self, parser):
        parser.add_argument('--schedule-id', type=uuid.UUID, required=True)
        parser.add_argument('--commit', action='store_true', help='Enqueue Jobs; otherwise no database writes.')

    def handle(self, *args, **options):
        try:
            result = plan_schedule(
                schedule_id=options['schedule_id'],
                commit=options['commit'],
            )
        except ScheduleError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
        if not options['commit']:
            self.stdout.write(self.style.WARNING('PREVIEW ONLY: Database was not modified.'))
        else:
            self.stdout.write(self.style.WARNING(
                'Jobs QUEUED ONLY. Facebook dispatch is not implemented or enabled.'
            ))
