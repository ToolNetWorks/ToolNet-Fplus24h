"""Conservative worker. NO Facebook integration, no background dispatch."""
import logging
import socket
import time
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.db.models import Count

from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.services.job_engine import (
    claim_due_job, prepare_job_media, fail_before_dispatch,
    JobEngineError, JobConflict,
)

logger = logging.getLogger(__name__)


def prepare_one(*, pipeline_id, worker_id, lease_seconds=600):
    """Trusted internal worker entry point, not exported via HTTP."""
    claim = claim_due_job(
        pipeline_id=pipeline_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    if claim is None:
        return None
    job_id = claim['job']['id']
    try:
        prepared = prepare_job_media(
            pipeline_id=pipeline_id,
            job_id=job_id,
            claim_token=claim['claim_token'],
        )
        return prepared
    except Exception:
        # A failure before any external dispatch is safe to retry.
        # Guard against a lost claim / a different state in the fallback.
        try:
            fail_before_dispatch(
                pipeline_id=pipeline_id,
                job_id=job_id,
                claim_token=claim['claim_token'],
                error_code='MEDIA_PREFLIGHT_FAILED',
                retry_delay_seconds=300,
            )
        except (JobEngineError, JobConflict):
            logger.exception('Cannot safely release preflight job %s', job_id)
        raise


class Command(BaseCommand):
    help = 'Inspect or prepare publishing jobs; never posts to Facebook.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID)
        parser.add_argument('--prepare-one', action='store_true')
        parser.add_argument('--watch', action='store_true')
        parser.add_argument('--poll-seconds', type=int, default=20)
        parser.add_argument('--lease-seconds', type=int, default=600)
        parser.add_argument('--worker-id', default='worker-' + socket.gethostname().split('.')[0][:35])

    def inspect(self, pipeline_id=None):
        qs = PublishingJob.objects.all()
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        rows = list(qs.values('state').annotate(total=Count('id')).order_by('state'))
        return ', '.join(f"{item['state']}={item['total']}" for item in rows) or 'empty'

    def handle(self, *args, **kwargs):
        pipeline_id = kwargs['pipeline_id']
        if pipeline_id and not Pipeline.objects.filter(pk=pipeline_id).exists():
            raise CommandError('Pipeline ID does not exist.')
        if kwargs['prepare_one'] and kwargs['watch']:
            raise CommandError('Choose either --prepare-one OR --watch.')
        if kwargs['poll_seconds'] < 5 or kwargs['poll_seconds'] > 3600:
            raise CommandError('poll-seconds must be between 5 and 3600.')
        if kwargs['prepare_one']:
            if not pipeline_id:
                raise CommandError('--prepare-one requires --pipeline-id.')
            if not 60 <= kwargs['lease_seconds'] <= 3600:
                raise CommandError('lease-seconds must be 60..3600.')
            self.stdout.write(self.style.WARNING(
                'PREPARE ONLY: Job will become READY, and may expire to UNCERTAIN.'
            ))
            try:
                result = prepare_one(
                    pipeline_id=pipeline_id,
                    worker_id=kwargs['worker_id'],
                    lease_seconds=kwargs['lease_seconds'],
                )
            except (JobEngineError, JobConflict) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write('EMPTY' if result is None else (
                f"PREPARED job={result['id']} state={result['state']}"
            ))
            return
        if kwargs['watch']:
            self.stdout.write('READ-ONLY WATCH MODE: no claims, no dispatch, no Facebook.')
            try:
                while True:
                    close_old_connections()
                    self.stdout.write(self.inspect(pipeline_id))
                    time.sleep(kwargs['poll_seconds'])
            except KeyboardInterrupt:
                return
        else:
            self.stdout.write('READ-ONLY QUEUE: ' + self.inspect(pipeline_id))
