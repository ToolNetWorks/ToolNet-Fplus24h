"""Conservative automatic recovery tick.

Two independent recovery actions, both scoped per Pipeline:
1. Stale JobCaption GENERATING rows older than --stale-caption-minutes are
   reset to FAILED (bounded retry is then handled by the caption tick).
2. Worker leases that expired are quarantined with the existing conservative
   service: in-flight Jobs move to UNCERTAIN and are NEVER auto-retried.

Preview by default. --apply performs the writes. Never posts to Facebook and
never marks a Job as PUBLISHED.
"""
import fcntl
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, transaction
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.caption_models import JobCaption, CaptionRevision
from modules.publishing.services.worker_reliability import (
    worker_guard_snapshot, quarantine_stale_leases,
    WorkerGuardError, WorkerGuardConflict,
)

LOCK_PATH = Path('/run/toolnet-recovery-tick.lock')
DEFAULT_POLL_SECONDS = 300
DEFAULT_STALE_CAPTION_MINUTES = 30


def _acquire_lock():
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


def _reset_stale_captions(*, limit, stale_after, apply, pipeline_id=None):
    now = timezone.now()
    qs = JobCaption.objects.select_for_update().filter(
        state=JobCaption.State.GENERATING,
        generation_started_at__lt=now - stale_after,
    )
    if pipeline_id is not None:
        qs = qs.filter(pipeline_id=pipeline_id)
    rows = list(qs.order_by('generation_started_at')[:limit])
    result = []
    for row in rows:
        item = {
            'job_id': str(row.job_id),
            'pipeline_id': str(row.pipeline_id),
            'started_at': row.generation_started_at.isoformat()
            if row.generation_started_at else None,
            'action': 'reset_failed',
        }
        if apply:
            row.state = JobCaption.State.FAILED
            row.generation_token = None
            row.revision += 1
            row.save(update_fields=['state', 'generation_token', 'revision',
                                    'updated_at'])
            CaptionRevision.objects.create(
                job_caption=row, revision=row.revision,
                action='generation_stale_reset', text=row.text,
                destination=row.destination_snapshot, model_name=row.model_name,
            )
        result.append(item)
    return result


def _recover_pipeline(*, pipeline_id, limit, apply, now):
    snapshot = worker_guard_snapshot(pipeline_id=pipeline_id, limit=limit, now=now)
    expired = snapshot['summary']['expired_or_missing_lease']
    quarantined = []
    if apply and expired:
        try:
            data = quarantine_stale_leases(
                pipeline_id=pipeline_id, limit=limit, now=now,
            )
            quarantined = data.get('quarantined', data.get('items', []))
        except (WorkerGuardError, WorkerGuardConflict) as exc:
            return {
                'pipeline_id': str(pipeline_id),
                'expired_or_missing_lease': expired,
                'quarantined': [],
                'error': exc.__class__.__name__,
            }
    return {
        'pipeline_id': str(pipeline_id),
        'expired_or_missing_lease': expired,
        'quarantined_count': len(quarantined),
        'quarantined': quarantined,
        'summary': snapshot['summary'],
    }


class Command(BaseCommand):
    help = ('Recover stale captions and expired worker leases. Preview by '
            'default; --apply writes. Never posts to Facebook.')

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID)
        parser.add_argument('--limit', type=int, default=20)
        parser.add_argument('--stale-caption-minutes', type=int,
                            default=DEFAULT_STALE_CAPTION_MINUTES)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--watch', action='store_true')
        parser.add_argument('--poll-seconds', type=int, default=DEFAULT_POLL_SECONDS)

    def _validate(self, opts):
        if not 1 <= opts['limit'] <= 100:
            raise CommandError('Limit phải từ 1 đến 100.')
        if not 5 <= opts['stale_caption_minutes'] <= 1440:
            raise CommandError('Stale caption phút phải từ 5 đến 1440.')
        if not 30 <= opts['poll_seconds'] <= 3600:
            raise CommandError('Poll seconds phải từ 30 đến 3600.')

    def _tick(self, opts):
        now = timezone.now()
        stale_after = timedelta(minutes=opts['stale_caption_minutes'])
        pipelines = Pipeline.objects.filter(status=Pipeline.Status.ACTIVE)
        if opts['pipeline_id'] is not None:
            pipelines = pipelines.filter(pk=opts['pipeline_id'])
        result = {
            'mode': 'apply' if opts['apply'] else 'preview',
            'watch': opts['watch'],
            'checked_at': now.isoformat(),
            'stale_captions': [],
            'pipelines': [],
            'facebook_posting': False,
        }
        with transaction.atomic():
            result['stale_captions'] = _reset_stale_captions(
                limit=opts['limit'], stale_after=stale_after,
                apply=opts['apply'], pipeline_id=opts['pipeline_id'],
            )
        if opts['pipeline_id'] is not None and not pipelines.exists():
            raise CommandError('Pipeline không tồn tại.')
        for pipeline in pipelines.order_by('pk'):
            with transaction.atomic():
                result['pipelines'].append(_recover_pipeline(
                    pipeline_id=pipeline.pk, limit=opts['limit'],
                    apply=opts['apply'], now=now,
                ))
        return result

    def handle(self, *args, **opts):
        self._validate(opts)
        if not opts['watch']:
            lock = _acquire_lock()
            if lock is None:
                raise CommandError('Một Recovery Tick khác đang chạy.')
            try:
                result = self._tick(opts)
            finally:
                _release_lock(lock)
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            return

        try:
            while True:
                close_old_connections()
                lock = _acquire_lock()
                if lock is not None:
                    try:
                        result = self._tick(opts)
                    finally:
                        _release_lock(lock)
                    self.stdout.write(json.dumps(result, ensure_ascii=False))
                close_old_connections()
                time.sleep(opts['poll_seconds'])
        except KeyboardInterrupt:
            self.stdout.write('Recovery tick stopped.')
