"""Automatic AI caption tick.

Preview by default. --generate creates captions through the configured AI
provider. --watch repeats the tick for 24/7 operation. Without --pipeline-id
every ACTIVE Pipeline with enabled+auto_generate settings is scanned.

Safety guarantees:
- Never posts to Facebook and never claims/prepares Jobs.
- Never approves an invalid, duplicate or foreign-handle caption.
- Bounded retry of FAILED captions with cooldown; stale GENERATING rows are
  retried automatically (generation token CAS still protects concurrency).
- A host-local flock prevents overlapping ticks across processes.
"""
import argparse
import fcntl
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.caption_models import (
    PipelineCaptionSettings, JobCaption, CaptionRevision,
)
from modules.publishing.services.caption_engine import (
    generate_job_caption, CaptionError,
)

LOCK_PATH = Path('/run/toolnet-caption-tick.lock')
DEFAULT_POLL_SECONDS = 60
DEFAULT_RETRY_DELAY_SECONDS = 900
DEFAULT_STALE_MINUTES = 10
DEFAULT_MAX_RETRIES = 3


def _acquire_lock():
    """Host-local exclusive lock; released by the OS if the process dies."""
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle = open(LOCK_PATH, 'a+')
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        return None


def _release_lock(handle):
    if handle is None:
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def _eligible_pipeline_ids(pipeline_id=None):
    qs = PipelineCaptionSettings.objects.filter(
        enabled=True,
        auto_generate=True,
        pipeline__status=Pipeline.Status.ACTIVE,
    )
    if pipeline_id is not None:
        qs = qs.filter(pipeline_id=pipeline_id)
    return list(qs.order_by('pipeline_id').values_list('pipeline_id', flat=True))


def _failed_attempts(job_id):
    return CaptionRevision.objects.filter(
        job_caption__job_id=job_id, action='generation_failed',
    ).count()


def _candidate_ids(*, pipeline_id, limit, now, retry_delay, stale_after,
                   retry_failed, max_retries):
    filters = Q(ai_caption__isnull=True)
    if retry_failed:
        filters |= Q(
            ai_caption__state=JobCaption.State.FAILED,
            ai_caption__updated_at__lte=now - retry_delay,
        )
    filters |= Q(
        ai_caption__state=JobCaption.State.GENERATING,
        ai_caption__generation_started_at__lte=now - stale_after,
    )
    rows = (PublishingJob.objects.filter(
                pipeline_id=pipeline_id,
                state=PublishingJob.State.QUEUED,
                attempt_count=0,
                manual_handoff__isnull=True,
            )
            .filter(filters)
            .order_by('scheduled_at', 'pk')
            .values_list('pk', flat=True)[:max(limit * 5, limit)])
    ids = []
    for job_id in rows:
        if retry_failed and _failed_attempts(job_id) >= max_retries:
            continue
        ids.append(job_id)
        if len(ids) >= limit:
            break
    return ids


class Command(BaseCommand):
    help = ('Generate captions for queued Jobs. Default preview never contacts an '
            'AI provider. Never posts to Facebook.')

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID,
                            help='Limit to one Pipeline; omit to scan all eligible.')
        parser.add_argument('--limit', type=int, default=5,
                            help='Max Jobs per Pipeline per tick (1-20).')
        parser.add_argument('--generate', action='store_true')
        parser.add_argument('--watch', action='store_true',
                            help='Repeat ticks until interrupted (24/7 service).')
        parser.add_argument('--poll-seconds', type=int, default=DEFAULT_POLL_SECONDS)
        parser.add_argument('--retry-failed', action=argparse.BooleanOptionalAction,
                            default=True,
                            help='Retry FAILED captions after the cooldown.')
        parser.add_argument('--retry-delay-seconds', type=int,
                            default=DEFAULT_RETRY_DELAY_SECONDS)
        parser.add_argument('--stale-minutes', type=int, default=DEFAULT_STALE_MINUTES,
                            help='Retry GENERATING captions older than this.')
        parser.add_argument('--max-retries', type=int, default=DEFAULT_MAX_RETRIES)

    def _validate(self, opts):
        if not 1 <= opts['limit'] <= 20:
            raise CommandError('Limit phải từ 1 đến 20.')
        if not 10 <= opts['poll_seconds'] <= 3600:
            raise CommandError('Poll seconds phải từ 10 đến 3600.')
        if not 60 <= opts['retry_delay_seconds'] <= 86400:
            raise CommandError('Retry delay phải từ 60 đến 86400 giây.')
        if not 1 <= opts['stale_minutes'] <= 240:
            raise CommandError('Stale minutes phải từ 1 đến 240.')
        if not 0 <= opts['max_retries'] <= 10:
            raise CommandError('Max retries phải từ 0 đến 10.')

    def _tick(self, opts):
        now = timezone.now()
        retry_delay = timedelta(seconds=opts['retry_delay_seconds'])
        stale_after = timedelta(minutes=opts['stale_minutes'])
        pipeline_ids = _eligible_pipeline_ids(opts['pipeline_id'])
        if opts['pipeline_id'] is not None and not pipeline_ids:
            raise CommandError('Pipeline chưa bật tạo caption tự động.')
        result = {
            'mode': 'generate' if opts['generate'] else 'preview',
            'watch': opts['watch'],
            'pipeline_ids': [str(pk) for pk in pipeline_ids],
            'candidate_count': 0,
            'items': [],
            'facebook_posting': False,
            'checked_at': now.isoformat(),
        }
        for pipeline_id in pipeline_ids:
            ids = _candidate_ids(
                pipeline_id=pipeline_id,
                limit=opts['limit'],
                now=now,
                retry_delay=retry_delay,
                stale_after=stale_after,
                retry_failed=opts['retry_failed'],
                max_retries=opts['max_retries'],
            )
            result['candidate_count'] += len(ids)
            for job_id in ids:
                if not opts['generate']:
                    result['items'].append({
                        'job_id': str(job_id),
                        'pipeline_id': str(pipeline_id),
                        'status': 'pending',
                    })
                    continue
                try:
                    record = generate_job_caption(
                        pipeline_id=pipeline_id, job_id=job_id,
                    )
                    result['items'].append({
                        'job_id': str(job_id),
                        'pipeline_id': str(pipeline_id),
                        'status': record['state'],
                    })
                except CaptionError as exc:
                    result['items'].append({
                        'job_id': str(job_id),
                        'pipeline_id': str(pipeline_id),
                        'status': 'failed',
                        'error': f'{exc.__class__.__name__}: {str(exc)[:160]}',
                    })
        return result

    def handle(self, *args, **opts):
        self._validate(opts)
        if not opts['watch']:
            lock = _acquire_lock()
            if lock is None:
                raise CommandError('Một Caption Tick khác đang chạy.')
            try:
                result = self._tick(opts)
            finally:
                _release_lock(lock)
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            if any(item['status'] == 'failed' for item in result['items']):
                raise CommandError('Một số caption không tạo được; xem cấu hình AI.')
            return

        self.stdout.write(self.style.WARNING(
            'CAPTION WATCH ENABLED: generates and auto-approves captions; '
            'NEVER posts to Facebook.'
        ))
        try:
            while True:
                close_old_connections()
                lock = _acquire_lock()
                if lock is None:
                    time.sleep(opts['poll_seconds'])
                    continue
                try:
                    result = self._tick(opts)
                except CommandError as exc:
                    result = {'mode': 'generate', 'watch': True, 'error': str(exc),
                              'items': [], 'candidate_count': 0,
                              'facebook_posting': False,
                              'checked_at': timezone.now().isoformat()}
                finally:
                    _release_lock(lock)
                self.stdout.write(json.dumps(result, ensure_ascii=False))
                close_old_connections()
                time.sleep(opts['poll_seconds'])
        except KeyboardInterrupt:
            self.stdout.write('Caption tick stopped.')
