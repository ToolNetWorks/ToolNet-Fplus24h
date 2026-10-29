"""Read-only production release acceptance; explicit operator signoff remains external."""
import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from modules.publishing.services.release_readiness import release_snapshot, ReleaseReadinessError


class Command(BaseCommand):
    help = 'Read-only go/no-go evidence; NEVER approves or deploys a release.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', type=uuid.UUID, required=True)
        parser.add_argument('--limit', type=int, default=50)
        parser.add_argument('--strict', action='store_true')
        parser.add_argument('--skip-performance', action='store_true')

    def handle(self, *args, **options):
        try:
            result = release_snapshot(
                pipeline_id=options['pipeline_id'], limit=options['limit'],
                include_performance=not options['skip_performance'],
            )
        except ReleaseReadinessError as exc:
            raise CommandError(str(exc)) from exc
        except Exception:
            raise CommandError('Không thể kiểm tra nghiệm thu; xem log nội bộ.') from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if options['strict']:
            raise CommandError('NO-GO: chưa thể tự phê duyệt phát hành; cần nghiệm thu và ký duyệt bên ngoài.')
        self.stdout.write(self.style.WARNING(
            'NOT APPROVED: external smoke test, backup restore and explicit human signoff required.'
        ))
