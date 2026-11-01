import logging

from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.facebook_accounts.cookie_parser import (
    CookieFileError,
    MAX_COOKIE_FILE_SIZE,
    parse_facebook_cookie_file,
)
from modules.facebook_accounts.crypto import encrypt_cookies
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_accounts.credentials import (
    FacebookCookieSecret,
)
from modules.pipelines.models import Pipeline
logger = logging.getLogger(__name__)
class FacebookCookieUploadThrottle(UserRateThrottle):
    rate = "10/hour"
class FacebookCookieUploadSerializer(serializers.Serializer):
    label = serializers.CharField(
        max_length=150,
        allow_blank=False,
        trim_whitespace=True,
    )
    profile_url = serializers.URLField(
        required=False,
        allow_blank=True,
        max_length=500,
    )
    file = serializers.FileField(
        allow_empty_file=False,
    )


class FacebookCookieReplaceThrottle(UserRateThrottle):
    scope = 'facebook_cookie_replace'
    rate = '10/hour'


class FacebookCookieReplaceAPIView(APIView):
    """Replace a single account's cookies without creating a duplicate account."""
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [FacebookCookieReplaceThrottle]

    def post(self, request, pipeline_id, account_id):
        from modules.api.v1.albums.views import resolve_pipeline
        from modules.facebook_publishing.models import WorkerRunningOp
        from modules.publishing.models import PublishingJob

        pipeline = resolve_pipeline(request.user, pipeline_id)
        uploaded_file = request.FILES.get('file')
        if not uploaded_file or set(request.data) != {'file'}:
            return Response({'detail': 'Cần đúng một file cookie JSON.'}, status=400)
        if not uploaded_file.name.lower().endswith('.json') or uploaded_file.size > MAX_COOKIE_FILE_SIZE:
            return Response({'detail': 'Chỉ nhận file JSON tối đa 64 KB.'}, status=400)
        try:
            cookies = parse_facebook_cookie_file(uploaded_file.read(MAX_COOKIE_FILE_SIZE + 1))
            ciphertext = encrypt_cookies(cookies)
        except (CookieFileError, ValueError):
            return Response({'detail': 'File cookie Facebook không hợp lệ.'}, status=400)

        with transaction.atomic():
            locked_pipeline = Pipeline.objects.select_for_update().get(pk=pipeline.pk)
            if locked_pipeline.status != Pipeline.Status.ACTIVE:
                return Response({'detail': 'Pipeline đang bị khóa.'}, status=409)
            account = FacebookAccount.objects.select_for_update().filter(
                pk=account_id, pipeline=locked_pipeline).first()
            if account is None:
                return Response({'detail': 'Tài khoản không tồn tại.'}, status=404)
            if account.connection_status == FacebookAccount.ConnectionStatus.DISABLED:
                return Response({'detail': 'Tài khoản đang bị vô hiệu hóa.'}, status=409)
            cookie_uid = next((item['value'] for item in cookies if item['name'] == 'c_user'), '')
            if account.facebook_user_id and cookie_uid != account.facebook_user_id:
                return Response({'detail': 'Cookie không khớp danh tính tài khoản đã xác minh.'}, status=400)
            if (WorkerRunningOp.objects.filter(account=account).exists() or
                    PublishingJob.objects.filter(pipeline=locked_pipeline, facebook_account=account,
                        state__in=('claimed', 'ready', 'dispatching', 'uncertain')).exists()):
                return Response({'detail': 'Tài khoản đang có Job cần xử lý hoặc đối soát.'}, status=409)
            FacebookCookieSecret.objects.update_or_create(account=account, defaults={
                'ciphertext': ciphertext, 'cookie_count': len(cookies), 'key_version': 1,
            })
            account.connection_status = FacebookAccount.ConnectionStatus.NOT_CONNECTED
            account.last_verified_at = None
            account.save(update_fields=['connection_status', 'last_verified_at', 'updated_at'])
        logger.info('facebook_cookie_replaced pipeline=%s account=%s actor=%s',
                    pipeline.pk, account_id, request.user.pk)
        response = Response({'success': True, 'message': 'Đã cập nhật cookie; phiên chưa được xác minh.'})
        response['Cache-Control'] = 'private, no-store'
        return response
class FacebookCookieUploadAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [FacebookCookieUploadThrottle]
    def post(self, request, pipeline_id):
        pipeline = get_object_or_404(
            Pipeline,
            pk=pipeline_id,
        )
        user = request.user
        if not user.is_active:
            return Response(
                {"detail": "Tài khoản đã bị khóa."},
                status=status.HTTP_403_FORBIDDEN,
            )
        is_admin = user.is_superuser and user.is_staff
        is_owner = (not user.is_staff and not user.is_superuser
                    and pipeline.ctv_id == user.pk)
        if not (is_admin or is_owner):
            return Response(
                {"detail": "Pipeline không tồn tại."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if pipeline.status != "active":
            return Response(
                {
                    "detail": (
                        "Pipeline đang bị khóa. "
                        "Không thể thêm tài khoản."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        serializer = FacebookCookieUploadSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        uploaded_file = serializer.validated_data["file"]
        if not uploaded_file.name.lower().endswith(".json"):
            return Response(
                {"detail": "Chỉ chấp nhận file JSON."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if uploaded_file.size > MAX_COOKIE_FILE_SIZE:
            return Response(
                {"detail": "File cookie vượt quá 64 KB."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            content = uploaded_file.read(
                MAX_COOKIE_FILE_SIZE + 1
            )
            cookies = parse_facebook_cookie_file(
                content
            )
        except (CookieFileError, ValueError):
            return Response(
                {
                    "detail": (
                        "File cookie không đúng định dạng "
                        "Facebook được hỗ trợ."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Encrypt before writing to the database.
        ciphertext = encrypt_cookies(cookies)
        try:
            with transaction.atomic():
                account = FacebookAccount(
                    pipeline=pipeline,
                    label=serializer.validated_data["label"],
                    profile_url=serializer.validated_data.get(
                        "profile_url", ""
                    ),
                    connection_status=(
                        FacebookAccount
                        .ConnectionStatus.NOT_CONNECTED
                    ),
                )
                account.full_clean()
                account.save()
                FacebookCookieSecret.objects.create(
                    account=account,
                    ciphertext=ciphertext,
                    cookie_count=len(cookies),
                    key_version=1,
                )
        except DjangoValidationError as exc:
            return Response(
                {
                    "detail": (
                        "Thông tin tài khoản không hợp lệ."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        response = Response(
            {
                "success": True,
                "message": (
                    "Đã lưu file cookie mã hóa. "
                    "Phiên Facebook chưa được xác minh."
                ),
                "data": {
                    "id": str(account.pk),
                    "pipeline_id": str(pipeline.pk),
                    "label": account.label,
                    "profile_url": account.profile_url,
                    "connection_status": (
                        account.connection_status
                    ),
                    "cookie_count": len(cookies),
                },
            },
            status=status.HTTP_201_CREATED,
        )
        response["Cache-Control"] = "private, no-store"
        return response
