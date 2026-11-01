"""Check a saved Facebook session without disclosing credentials."""
import logging
import re
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.facebook_accounts.models import FacebookAccount, FacebookCookieSecret
from modules.facebook_publishing.models import ConnectionMode, WorkerRunningOp
from modules.facebook_publishing.services.config import load_settings
from modules.facebook_publishing.services.browser_manager import BrowserManager, _build_proxy_config
from modules.facebook_publishing.services.account_binding import _validate_proxy, AccountProxyBindingError
from modules.publishing.scheduler_models import AccountProxyPin

logger = logging.getLogger(__name__)


class FacebookSessionVerifyThrottle(UserRateThrottle):
    scope = 'facebook_session_verify'
    rate = '20/hour'


def inspect_session(account, settings, proxy_config):
    """Use isolated browser context; return only an outcome code."""
    # Playwright starts an event loop. Resolve the Django relation before that
    # happens so loading cookies never performs synchronous ORM work in it.
    getattr(account, 'cookie_secret', None)
    manager = BrowserManager(settings)
    context = None
    try:
        context = manager.launch_context(proxy_config=proxy_config)
        loaded, _ = manager.load_account_cookies(context, account)
        if not loaded:
            return 'cookie_unavailable'
        page = context.new_page()
        page.goto('https://www.facebook.com/', timeout=30000, wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        location = urlsplit(page.url)
        if location.scheme != 'https' or location.hostname not in {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'web.facebook.com'}:
            return 'unverified'
        path = location.path.lower()
        if path.startswith(('/checkpoint', '/captcha', '/recover')):
            return 'checkpoint'
        challenge = page.get_by_text(re.compile(
            r'confirm your identity|security check|xác nhận danh tính|kiểm tra bảo mật', re.I))
        if any(challenge.nth(i).is_visible() for i in range(min(challenge.count(), 10))):
            return 'checkpoint'
        if path.startswith('/login') or page.locator('input[name="pass"]:visible').count():
            return 'expired'
        # An unrelated Facebook page or an HTTP 200 is not proof of a session.
        menu = page.get_by_role('button', name=re.compile(
            r'tài khoản, trang cá nhân của bạn|your profile|account', re.I))
        if menu.count() != 1 or not menu.first.is_visible():
            return 'unverified'
        if manager.verify_account_identity(page, account.label):
            return 'verified'
        return 'identity_unverified'
    finally:
        manager.close_context(context)
        manager.shutdown()


class FacebookSessionVerifyAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [FacebookSessionVerifyThrottle]

    def post(self, request, pipeline_id, account_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        account = FacebookAccount.objects.filter(pk=account_id, pipeline=pipeline).first()
        if account is None:
            return Response({'detail': 'Tài khoản không tồn tại.'}, status=404)
        if account.connection_status == FacebookAccount.ConnectionStatus.DISABLED:
            return Response({'detail': 'Tài khoản đang bị vô hiệu hóa.'}, status=409)
        if WorkerRunningOp.objects.filter(account=account).exists():
            return Response({'detail': 'Tài khoản đang xử lý bài đăng. Hãy kiểm tra lại sau.'}, status=409)
        secret = FacebookCookieSecret.objects.filter(account=account).first()
        if secret is None:
            return Response({'detail': 'Tài khoản chưa có cookie.'}, status=400)
        original_ciphertext = secret.ciphertext
        settings = load_settings(pipeline.pk)
        proxy_config = None
        if settings.connection_mode == ConnectionMode.PROXY:
            pin = AccountProxyPin.objects.select_related('proxy__auth_secret').filter(
                pipeline=pipeline, account=account, proxy__account=account).first()
            if not pin:
                return Response({'detail': 'Pipeline dùng Proxy nhưng tài khoản chưa có Proxy được ghim.'}, status=409)
            try:
                _validate_proxy(pin.proxy, timezone.now())
            except AccountProxyBindingError:
                return Response({'detail': 'Proxy chưa sẵn sàng hoặc đã hết hạn kiểm tra.'}, status=409)
            if str(pin.proxy.exit_ip) != str(pin.pinned_exit_ip):
                return Response({'detail': 'Địa chỉ Proxy không khớp cấu hình đã ghim.'}, status=409)
            proxy_config = _build_proxy_config(pin.proxy)
        try:
            outcome = inspect_session(account, settings, proxy_config)
        except Exception:
            logger.warning('facebook_session_check_failed account=%s', account.pk)
            return Response({'detail': 'Không thể kiểm tra Facebook lúc này. Hãy thử lại sau.'}, status=503)
        messages = {
            'verified': 'Cookie hoạt động và tên tài khoản khớp với Facebook.',
            'expired': 'Facebook yêu cầu đăng nhập lại; hãy cập nhật cookie.',
            'checkpoint': 'Facebook yêu cầu kiểm tra bảo mật hoặc xác nhận danh tính.',
            'identity_unverified': 'Facebook có phiên đăng nhập, nhưng chưa xác minh được tên tài khoản.',
            'unverified': 'Chưa xác định được trạng thái phiên Facebook. Hãy thử lại sau.',
            'cookie_unavailable': 'Không thể đọc cookie đã lưu; hãy cập nhật cookie.',
        }
        if outcome not in messages:
            return Response({'detail': 'Không xác định được kết quả kiểm tra.'}, status=503)
        with transaction.atomic():
            locked = FacebookAccount.objects.select_for_update().get(pk=account.pk, pipeline=pipeline)
            current = FacebookCookieSecret.objects.filter(account=locked).first()
            if (current is None or current.ciphertext != original_ciphertext or locked.label != account.label or
                    locked.connection_status == FacebookAccount.ConnectionStatus.DISABLED):
                return Response({'detail': 'Cookie hoặc tài khoản đã thay đổi; hãy kiểm tra lại.'}, status=409)
            if outcome == 'verified':
                locked.connection_status = FacebookAccount.ConnectionStatus.CONNECTED
                locked.last_verified_at = timezone.now()
                locked.save(update_fields=['connection_status', 'last_verified_at', 'updated_at'])
            elif outcome == 'expired':
                locked.connection_status = FacebookAccount.ConnectionStatus.EXPIRED
                locked.last_verified_at = None
                locked.save(update_fields=['connection_status', 'last_verified_at', 'updated_at'])
        logger.info('facebook_session_checked pipeline=%s account=%s actor=%s result=%s',
                    pipeline.pk, account.pk, request.user.pk, outcome)
        response = Response({'success': True, 'result': outcome, 'message': messages[outcome]})
        response['Cache-Control'] = 'private, no-store'
        return response
