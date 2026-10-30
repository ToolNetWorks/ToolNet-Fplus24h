"""Facebook Publishing Worker management command.

Runs the Worker loop: claims a job, prepares, and (in DRY_RUN or real mode)
processes it.
"""
import logging
import socket
import time
import uuid

from django.core.management.base import BaseCommand, CommandError

from modules.pipelines.models import Pipeline
from modules.facebook_publishing.services.config import load_settings
from modules.facebook_publishing.services.worker import (
    claim_job, prepare_session, prepare_media, run_dry_run, run_publish,
    WorkerError, WorkerNotEnabledError,
)
from modules.facebook_publishing.services.audit_log import AuditLogger

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Facebook Publishing Worker: claims and processes jobs via browser automation.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--once', action='store_true',
                            help='Process one job and exit.')
        parser.add_argument('--watch', action='store_true',
                            help='Poll loop.')
        parser.add_argument('--poll-seconds', type=int, default=20)
        parser.add_argument('--lease-seconds', type=int, default=600)
        parser.add_argument('--worker-id',
                            default='fb-worker-' + socket.gethostname().split('.')[0][:30])
        parser.add_argument('--dry-run', action='store_true',
                            help='Override: force dry-run mode even if config says otherwise.')

    def handle(self, *args, **kwargs):
        pipeline_id = kwargs['pipeline_id']
        if not Pipeline.objects.filter(pk=pipeline_id).exists():
            raise CommandError(f'Pipeline {pipeline_id} does not exist.')

        settings = load_settings(pipeline_id)
        force_dry_run = kwargs.get('dry_run', False)

        if force_dry_run:
            logger.info('DRY RUN override requested.')

        if not settings.enabled and not (settings.dry_run or force_dry_run):
            raise CommandError(
                'FACEBOOK_PUBLISHING_ENABLED=false. Worker is disabled.'
            )

        worker_id = kwargs['worker_id']
        audit = AuditLogger(worker_id=worker_id)

        if kwargs['once']:
            self._process_one(
                pipeline_id, worker_id, settings, force_dry_run, audit,
            )
            return

        if kwargs['watch']:
            poll = kwargs['poll_seconds']
            if poll < 5 or poll > 3600:
                raise CommandError('poll-seconds must be between 5 and 3600.')
            while True:
                try:
                    self._process_one(
                        pipeline_id, worker_id, settings, force_dry_run, audit,
                    )
                except WorkerNotEnabledError:
                    logger.info('Worker not enabled for pipeline %s, sleeping.', pipeline_id)
                except WorkerError as exc:
                    logger.error('Worker error: %s', exc)
                time.sleep(poll)
            return

        # Default: prepare one and print inspection info
        claim = claim_job(
            pipeline_id=pipeline_id, worker_id=worker_id,
            lease_seconds=kwargs['lease_seconds'],
        )
        if claim is None:
            self.stdout.write('No due job.')
            return
        self.stdout.write(f"Claimed job: {claim['job']['id']}")

    def _process_one(self, pipeline_id, worker_id, settings, force_dry_run, audit):
        """Process a single job claim through the full Worker lifecycle."""
        claim_result = claim_job(
            pipeline_id=pipeline_id, worker_id=worker_id,
        )
        if claim_result is None:
            logger.info('No due job for pipeline %s', pipeline_id)
            return

        if force_dry_run:
            object.__setattr__(claim_result['settings'], 'dry_run', True)
            object.__setattr__(claim_result['settings'], 'enabled', True)
            logger.info('Force dry-run override applied.')

        effective_settings = claim_result['settings']
        claim_token = claim_result['claim_token']

        try:
            session = prepare_session(claim_result, effective_settings)
            audit.log_event('session_prepared', ready=True)

            caption, media_info = prepare_media(
                claim_result, session, effective_settings,
            )
            audit.log_event('media_prepared', images=str(media_info.get('images', [])))

            from modules.facebook_publishing.services.eligibility import \
                check_group_eligibility
            eligibility = check_group_eligibility(
                pipeline_id=pipeline_id,
                account_id=session.bundle.account_id,
                group_id=session.bundle.account_id if False else
                claim_result['job_obj'].facebook_group_id,
            )

            if effective_settings.dry_run:
                result = run_dry_run(
                    session, effective_settings, eligibility, caption,
                )
                audit.log_event(
                    'dry_run_completed',
                    result=result.get('result', 'unknown'),
                )
                self.stdout.write(f"DRY RUN result: {result}")
            else:
                result = run_publish(
                    session, effective_settings, eligibility, caption,
                    claim_token,
                )
                audit.log_event(
                    'publish_completed',
                    result=result.get('result', 'unknown'),
                )
                self.stdout.write(f"Publish result: {result}")

        except WorkerNotEnabledError:
            logger.info('Worker not enabled, skipping.')
        except WorkerError as exc:
            logger.error('Worker error processing job: %s', exc)
            raise
        finally:
            # Release the concurrency lock
            from modules.facebook_publishing.models import WorkerRunningOp
            try:
                op = WorkerRunningOp.objects.get(publish_job=claim_result['worker_job'])
                release_running_op(op)
            except WorkerRunningOp.DoesNotExist:
                pass
