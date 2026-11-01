"""Read-only browser inspection after a rules-review browser session is lost."""
import json
import uuid
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError

from modules.facebook_publishing.models import WorkerPublishJob, WorkerResultState
from modules.facebook_publishing.services.browser_manager import BrowserManager, _build_proxy_config
from modules.facebook_publishing.services.config import load_settings
from modules.facebook_publishing.services.verification import PublishingVerification
from modules.facebook_publishing.services.rules_review import expire_lost_session, RulesReviewConflict


class Command(BaseCommand):
    help = 'Inspect an uncertain Job after browser loss; never repost or alter Job state.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-id', required=True, type=uuid.UUID)
        parser.add_argument('--job-id', required=True, type=uuid.UUID)

    def handle(self, *args, **options):
        row = WorkerPublishJob.objects.select_related(
            'job', 'account__cookie_secret', 'group', 'proxy__auth_secret',
        ).filter(pipeline_id=options['pipeline_id'], job_id=options['job_id']).first()
        if not row or row.job.state != 'uncertain' or row.state not in (
            WorkerResultState.UNCERTAIN, WorkerResultState.RULES_CONFIRMATION_REQUIRED,
            WorkerResultState.RULES_CONFIRMED, WorkerResultState.SUBMITTED_UNVERIFIED,
        ):
            raise CommandError('Job không ở trạng thái đối soát phiên quy tắc.')
        try:
            expire_lost_session(pipeline_id=row.pipeline_id, job_id=row.job_id)
        except RulesReviewConflict as exc:
            raise CommandError(str(exc)) from None
        settings = load_settings(row.pipeline_id)
        if settings.use_proxy and (not row.proxy or not row.proxy.is_enabled):
            raise CommandError('Proxy của phiên không còn hợp lệ; không chuyển sang DIRECT.')
        proxy = _build_proxy_config(row.proxy) if settings.use_proxy else None
        caption, group_url, label = row.job.caption, row.group.group_url, row.account.label
        manager = BrowserManager(settings)
        try:
            context = manager.launch_context(proxy_config=proxy)
            loaded, _ = manager.load_account_cookies(context, row.account)
            if not loaded:
                raise CommandError('Không tải được phiên Facebook đã lưu.')
            page = context.new_page()
            page.goto('https://www.facebook.com/', timeout=settings.browser_timeout_seconds * 1000)
            if not manager.verify_account_identity(page, label):
                raise CommandError('Không xác minh được đúng tài khoản Facebook.')
            page.goto(group_url, timeout=settings.browser_timeout_seconds * 1000)
            expected, actual = urlsplit(group_url), urlsplit(page.url)
            if actual.hostname not in ('facebook.com', 'www.facebook.com') or not actual.path.startswith(expected.path):
                raise CommandError('Facebook không mở đúng Group.')
            verifier = PublishingVerification(page, settings, expected_caption=caption)
            if verifier.check_captcha_or_checkpoint():
                raise CommandError('Facebook yêu cầu checkpoint; không tự vượt qua.')
            observation = verifier.verify_post_visibility()
            # Matching a feed item alone cannot prove it is this attempt, and
            # absence from a feed never proves that Facebook did not receive it.
            self.stdout.write(json.dumps({'job_id': str(row.job_id),
                'observation': observation.state, 'verified': False,
                'automatic_retry': False, 'job_state': 'uncertain'}, ensure_ascii=False))
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f'Không thể kiểm tra Facebook: {type(exc).__name__}') from None
        finally:
            manager.shutdown()
