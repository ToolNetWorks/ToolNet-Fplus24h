"""Opt-in Scheduler Tick runner, defaulting to read-only preview."""
import json
import logging
import os
import re
import socket
import time
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from modules.publishing.services.scheduler_tick import tick_due_schedules, TickValidationError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Scan due schedules. --enqueue creates QUEUED Jobs only, NEVER posts to Facebook.'

    def add_arguments(self, parser):
        parser.add_argument('--enqueue', action='store_true',
                            help='Persist due batches/Jobs; default is read-only preview.')
        parser.add_argument('--watch', action='store_true',
                            help='Repeat ticks; requires --enqueue and explicit environment opt-in.')
        parser.add_argument('--poll-seconds', type=int, default=30)
        parser.add_argument('--limit', type=int, default=25)
        parser.add_argument('--pipeline-id', type=uuid.UUID)
        parser.add_argument('--schedule-id', type=uuid.UUID)
        parser.add_argument('--worker-id', default='tick-' + re.sub(
            r'[^A-Za-z0-9._:-]', '-', socket.gethostname())[:45])

    def handle(self, *args, **options):
        enqueue = options['enqueue']
        watch = options['watch']
        poll_seconds = options['poll_seconds']
        if not 10 <= poll_seconds <= 3600:
            raise CommandError('poll-seconds must be between 10 and 3600.')
        if watch and not enqueue:
            raise CommandError('--watch requires --enqueue (otherwise use default one-shot preview).')
        if watch and os.environ.get('TOOLNET_SCHEDULER_TICK_ENABLED') != '1':
            raise CommandError('Watch disabled. Set TOOLNET_SCHEDULER_TICK_ENABLED=1 explicitly.')

        def once():
            close_old_connections()
            try:
                result = tick_due_schedules(
                    enqueue=enqueue,
                    limit=options['limit'],
                    worker_id=options['worker_id'],
                    pipeline_id=options['pipeline_id'],
                    schedule_id=options['schedule_id'],
                )
            except TickValidationError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            if result['error_count']:
                logger.warning('Scheduler tick had %s failed schedules', result['error_count'])
            return result

        if not watch:
            once()
            return

        self.stdout.write(self.style.WARNING(
            'SCHEDULER AUTO TICK ENABLED: creates queued Jobs, NEVER posts to Facebook.'
        ))
        try:
            while True:
                once()
                close_old_connections()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            self.stdout.write('Scheduler tick stopped.')
