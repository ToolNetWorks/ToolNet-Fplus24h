"""Facebook Publishing Worker management command.

Runs the Worker loop: claims, prepares and publishes a job.
"""
import logging
import socket
import time
import uuid

from django.core.management.base import BaseCommand, CommandError

from modules.pipelines.models import Pipeline
from modules.facebook_publishing.services.config import load_settings
from modules.facebook_publishing.services.worker import (
    claim_job, prepare_session, prepare_media, run_publish,
    WorkerError, WorkerNotEnabledError,
)
from modules.facebook_publishing.services.account_binding import release_running_op
from modules.facebook_publishing.services.audit_log import AuditLogger
from modules.facebook_publishing.services.eligibility import check_group_eligibility
from modules.facebook_publishing.models import WorkerRunningOp

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
        parser.add_argument('--job-id', type=uuid.UUID,
                            help='Process only this specific Job.')
        parser.add_argument('--expected-image-id', type=uuid.UUID,
                            help='Require exactly this image for a real post.')
        parser.add_argument('--worker-id',
                            default='fb-worker-' + socket.gethostname().split('.')[0][:30])
        parser.add_argument('--force-publish', action='store_true',
                            help='Process exactly one specified job and expected image.')

    def handle(self, *args, **kwargs):
        pipeline_id = kwargs['pipeline_id']
        if not Pipeline.objects.filter(pk=pipeline_id).exists():
            raise CommandError(f'Pipeline {pipeline_id} does not exist.')

        if kwargs['force_publish'] and not kwargs['once']:
            raise CommandError('--force-publish requires --once (exactly one post).')
        if kwargs['force_publish'] and kwargs['watch']:
            raise CommandError('--force-publish cannot be used with --watch.')
        if kwargs['force_publish'] and not kwargs['job_id']:
            raise CommandError('--force-publish requires --job-id.')
        if kwargs['force_publish'] and not kwargs['expected_image_id']:
            raise CommandError('--force-publish requires --expected-image-id.')

        worker_id = kwargs['worker_id']
        audit = AuditLogger(worker_id=worker_id)

        if kwargs['once'] or kwargs['force_publish']:
            self._process_one(
                pipeline_id, worker_id, kwargs['force_publish'], audit,
                job_id=kwargs['job_id'], expected_image_id=kwargs['expected_image_id'],
            )
            return

        if kwargs['watch']:
            poll = kwargs['poll_seconds']
            if poll < 5 or poll > 3600:
                raise CommandError('poll-seconds must be between 5 and 3600.')
            while True:
                try:
                    self._process_one(
                        pipeline_id, worker_id, False, audit,
                    )
                except WorkerNotEnabledError:
                    logger.info('Worker not enabled for pipeline %s, sleeping.', pipeline_id)
                except WorkerError as exc:
                    logger.error('Worker error: %s', exc)
                time.sleep(poll)
            return

        # Default: claim and print inspection info
        claim = claim_job(
            pipeline_id=pipeline_id, worker_id=worker_id,
        )
        if claim is None:
            self.stdout.write('No due job.')
            return
        self.stdout.write(f"Claimed job: {claim['job']['id']}")

    def _process_one(self, pipeline_id, worker_id, force_publish, audit, job_id=None, expected_image_id=None):
        """Process a single job claim through the full Worker lifecycle."""
        claim_result = claim_job(
            pipeline_id=pipeline_id, worker_id=worker_id, job_id=job_id,
        )
        if claim_result is None:
            logger.info('No due job for pipeline %s', pipeline_id)
            self.stdout.write('No due job.')
            return

        settings = claim_result['settings']
        config = claim_result.get('config')
        claim_token = claim_result['claim_token']

        try:
            session = prepare_session(claim_result, settings)
            audit.log_event('session_prepared', ready=True)

            # Capture running_op before browser operations (sync context)
            running_op = claim_result['worker_job'].running_op.get()

            caption, media_info = prepare_media(
                claim_result, session, settings,
            )
            if force_publish and session.image_ids != [str(expected_image_id)]:
                from modules.publishing.services.job_engine import fail_before_dispatch
                fail_before_dispatch(pipeline_id=pipeline_id, job_id=str(session.publish_job.job_id),
                    claim_token=claim_token, error_code='UNEXPECTED_IMAGE')
                session.publish_job.state = 'failed'
                session.publish_job.error_code = 'UNEXPECTED_IMAGE'
                session.publish_job.save(update_fields=['state', 'error_code'])
                raise WorkerError('Job không được cấp đúng ảnh đã chỉ định; chưa gửi.')
            audit.log_event(
                'media_prepared',
                images=str(media_info.get('images', [])),
                caption_length=len(caption),
            )

            eligibility = check_group_eligibility(
                pipeline_id=pipeline_id,
                account_id=session.bundle.account_id,
                group_id=session.publish_job.group_id,
            )

            result = run_publish(
                session, settings, eligibility, caption,
                claim_token, config,
            )
            audit.log_event(
                'publish_completed',
                result=result.get('result', 'unknown'),
            )
            self.stdout.write(json.dumps(result, default=str, ensure_ascii=False))

        except WorkerNotEnabledError:
            self.stdout.write('Worker not enabled for this Pipeline.')
            logger.info('Worker not enabled, skipping.')
        except WorkerError as exc:
            self.stdout.write(f'Worker error: {exc}')
            logger.error('Worker error: %s', exc)
            raise
        finally:
            # Release the concurrency lock
            try:
                release_running_op(running_op)
                audit.log_event('running_op_released')
            except WorkerRunningOp.DoesNotExist:
                pass
            except Exception:
                pass  # Lock will expire on its own

import json
