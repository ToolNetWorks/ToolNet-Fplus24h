"""Read alerts by default. --scan is the only write path for detection.

An opt-in systemd timer can call --scan --all; this command neither sends
external notifications nor makes Facebook requests.
"""
import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from modules.pipelines.models import Pipeline
from modules.publishing.services.operational_alerts import (
    AlertError, list_alerts, scan_alerts,
)


class Command(BaseCommand):
    help = 'Per-Pipeline alert inbox; scan only with --scan; never changes jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID)
        parser.add_argument('--all', action='store_true', dest='all_pipelines')
        parser.add_argument('--scan', action='store_true')
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        pipeline_id = options['pipeline_id']
        all_pipelines = options['all_pipelines']
        scan = options['scan']
        limit = options['limit']
        if (pipeline_id is None) == (not all_pipelines):
            raise CommandError('Chọn đúng một: --pipeline-id hoặc --all.')
        if all_pipelines and not scan:
            raise CommandError('--all chỉ được dùng cùng --scan.')
        if type(limit) is not int or not 1 <= limit <= 500:
            raise CommandError('--limit phải nằm trong 1..500.')
        if pipeline_id is not None:
            try:
                data = scan_alerts(pipeline_id=pipeline_id) if scan else list_alerts(
                    pipeline_id=pipeline_id, page_size=20,
                )
            except Exception:
                raise CommandError('Không thể đọc/quét cảnh báo Pipeline; kiểm tra log server.') from None
            self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
            return
        # Never claim that a bounded scan checked every Pipeline.
        pipeline_ids = list(Pipeline.objects.filter(status=Pipeline.Status.ACTIVE)
                            .order_by('pk').values_list('pk', flat=True)[:limit + 1])
        truncated = len(pipeline_ids) > limit
        total = 0
        failures = 0
        for pid in pipeline_ids[:limit]:
            close_old_connections()
            try:
                data = scan_alerts(pipeline_id=pid)
            except Exception:
                failures += 1
                self.stderr.write('SCAN FAILED pipeline_id=' + str(pid))
                continue
            total += data['active_count']
        self.stdout.write(json.dumps({
            'processed': min(limit, len(pipeline_ids)), 'failed': failures,
            'active_incidents': total, 'truncated': truncated,
            'external_delivery_enabled': False,
        }, ensure_ascii=False))
        if failures or truncated:
            raise CommandError('Quét cảnh báo không đầy đủ; xem báo cáo ở trên.')
