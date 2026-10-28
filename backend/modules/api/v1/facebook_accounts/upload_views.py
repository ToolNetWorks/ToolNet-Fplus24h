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
        if not user.is_superuser:
            if user.is_staff or pipeline.ctv_id != user.pk:
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
        return Response(
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
