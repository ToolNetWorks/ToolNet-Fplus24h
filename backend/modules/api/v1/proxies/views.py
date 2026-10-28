from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.core.paginator import EmptyPage, Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.facebook_accounts.models import FacebookAccount
from modules.pipelines.models import Pipeline
from modules.proxies.crypto import encrypt_proxy_credentials
from modules.proxies.models import ProxyAuthSecret, ProxyEndpoint


class ProxyFields:
    protocol = serializers.ChoiceField(
        choices=ProxyEndpoint.Protocol.choices,
        required=False,
    )
    host = serializers.CharField(
        max_length=253,
        trim_whitespace=True,
        required=False,
    )
    port = serializers.IntegerField(
        min_value=1,
        max_value=65535,
        required=False,
    )
    account_id = serializers.UUIDField(
        required=False,
        allow_null=True,
    )
    username = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        max_length=128,
        write_only=True,
    )
    password = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        max_length=256,
        write_only=True,
    )
    is_enabled = serializers.BooleanField(required=False)
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
    )


class ProxyValidationMixin:
    def run_validation(self, data=serializers.empty):
        self._raw_input = data
        return super().run_validation(data)

    def validate(self, attrs):
        raw = getattr(self, "_raw_input", None)
        if raw is None or raw is serializers.empty:
            raw = getattr(self, "initial_data", None)
        if not isinstance(raw, dict):
            raise serializers.ValidationError(
                "Dữ liệu phải là JSON object."
            )
        allowed = {
            "protocol",
            "host",
            "port",
            "account_id",
            "username",
            "password",
            "is_enabled",
            "notes",
        }
        if set(raw) - allowed:
            raise serializers.ValidationError(
                "Có trường không được phép chỉnh sửa."
            )
        credentials_supplied = (
            "username" in raw or "password" in raw
        )
        if credentials_supplied:
            if not {"username", "password"}.issubset(raw):
                raise serializers.ValidationError({
                    "credentials": (
                        "Phải gửi cả username và password."
                    ),
                })
            username = attrs.get("username", "")
            password = attrs.get("password", "")
            if bool(username) != bool(password):
                raise serializers.ValidationError({
                    "credentials": (
                        "Username và password phải cùng "
                        "có giá trị hoặc cùng để trống."
                    ),
                })
        return attrs


class ProxyCreateSerializer(
    ProxyValidationMixin,
    serializers.Serializer,
):
    protocol = ProxyFields.protocol
    host = serializers.CharField(max_length=253)
    port = serializers.IntegerField(
        min_value=1,
        max_value=65535,
    )
    account_id = ProxyFields.account_id
    username = ProxyFields.username
    password = ProxyFields.password
    is_enabled = ProxyFields.is_enabled
    notes = ProxyFields.notes


class ProxyUpdateSerializer(
    ProxyValidationMixin,
    serializers.Serializer,
):
    protocol = ProxyFields.protocol
    host = ProxyFields.host
    port = ProxyFields.port
    account_id = ProxyFields.account_id
    username = ProxyFields.username
    password = ProxyFields.password
    is_enabled = ProxyFields.is_enabled
    notes = ProxyFields.notes

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs:
            raise serializers.ValidationError(
                "Không có dữ liệu cập nhật."
            )
        return attrs


class ProxyBulkSerializer(serializers.Serializer):
    items = ProxyCreateSerializer(
        many=True,
        allow_empty=False,
        max_length=50,
    )

    def validate(self, attrs):
        if set(self.initial_data) != {"items"}:
            raise serializers.ValidationError(
                "Chỉ chấp nhận trường items."
            )
        return attrs


class ProxyFilterSerializer(serializers.Serializer):
    page = serializers.IntegerField(
        min_value=1,
        default=1,
    )
    page_size = serializers.IntegerField(
        min_value=1,
        max_value=50,
        default=20,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
    )
    status = serializers.ChoiceField(
        required=False,
        choices=ProxyEndpoint.HealthStatus.choices,
    )
    assigned = serializers.BooleanField(required=False)


def resolve_proxy_pipeline(user, pipeline_id):
    if not user.is_active:
        raise Http404("Pipeline không tồn tại.")
    queryset = Pipeline.objects.filter(pk=pipeline_id)
    if user.is_superuser and user.is_staff:
        pipeline = queryset.first()
    elif not user.is_staff and not user.is_superuser:
        pipeline = queryset.filter(ctv_id=user.pk).first()
    else:
        raise Http404("Pipeline không tồn tại.")
    if pipeline is None:
        raise Http404("Pipeline không tồn tại.")
    if (
        not user.is_superuser
        and pipeline.status != Pipeline.Status.ACTIVE
    ):
        raise Http404("Pipeline không tồn tại.")
    return pipeline


def proxy_to_dict(proxy):
    account = proxy.account
    return {
        "id": str(proxy.pk),
        "pipeline_id": str(proxy.pipeline_id),
        "protocol": proxy.protocol,
        "host": proxy.host,
        "port": proxy.port,
        "is_enabled": proxy.is_enabled,
        "health_status": proxy.health_status,
        "exit_ip": proxy.exit_ip,
        "latency_ms": proxy.latency_ms,
        "last_checked_at": (
            proxy.last_checked_at.isoformat()
            if proxy.last_checked_at else None
        ),
        "notes": proxy.notes,
        "account": (
            {
                "id": str(account.pk),
                "label": account.label,
            }
            if account else None
        ),
        "has_auth": hasattr(proxy, "auth_secret"),
        "created_at": proxy.created_at.isoformat(),
        "updated_at": proxy.updated_at.isoformat(),
    }


def validation_response(exc):
    return Response({
        "success": False,
        "message": "Thông tin Proxy không hợp lệ.",
        "errors": (
            exc.message_dict
            if hasattr(exc, "message_dict")
            else {"non_field_errors": exc.messages}
        ),
    }, status=400)


def persist_proxy(*, pipeline, data, instance=None):
    values = dict(data)
    credentials_supplied = (
        "username" in values or "password" in values
    )
    username = values.pop("username", "")
    password = values.pop("password", "")
    account_supplied = "account_id" in values
    account_id = values.pop("account_id", None)
    proxy = instance or ProxyEndpoint(pipeline=pipeline)
    if account_supplied:
        if account_id is None:
            proxy.account = None
        else:
            account = (
                FacebookAccount.objects
                .select_for_update()
                .filter(
                    pk=account_id,
                    pipeline_id=pipeline.pk,
                )
                .first()
            )
            if account is None:
                raise DjangoValidationError({
                    "account_id": (
                        "Tài khoản không thuộc Pipeline."
                    )
                })
            proxy.account = account
    reset_health = instance is None
    for field in (
        "protocol",
        "host",
        "port",
        "is_enabled",
        "notes",
    ):
        if field not in values:
            continue
        if field in {"protocol", "host", "port"}:
            if getattr(proxy, field) != values[field]:
                reset_health = True
        setattr(proxy, field, values[field])
    if credentials_supplied:
        reset_health = True
    if reset_health:
        proxy.health_status = (
            ProxyEndpoint.HealthStatus.UNTESTED
        )
        proxy.exit_ip = None
        proxy.latency_ms = None
        proxy.last_checked_at = None
    proxy.full_clean()
    proxy.save()
    if credentials_supplied:
        if username and password:
            ciphertext = encrypt_proxy_credentials(
                username,
                password,
            )
            ProxyAuthSecret.objects.update_or_create(
                proxy=proxy,
                defaults={
                    "ciphertext": ciphertext,
                    "key_version": 1,
                },
            )
        else:
            ProxyAuthSecret.objects.filter(
                proxy=proxy
            ).delete()
    return proxy


class ProxyListCreateAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get(self, request, pipeline_id):
        pipeline = resolve_proxy_pipeline(
            request.user,
            pipeline_id,
        )
        filters = ProxyFilterSerializer(
            data=request.query_params,
        )
        filters.is_valid(raise_exception=True)
        params = filters.validated_data
        queryset = (
            ProxyEndpoint.objects
            .filter(pipeline_id=pipeline.pk)
            .select_related("account", "auth_secret")
        )
        search = params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(host__icontains=search)
                | Q(notes__icontains=search)
                | Q(account__label__icontains=search)
            )
        if "status" in params:
            queryset = queryset.filter(
                health_status=params["status"]
            )
        if "assigned" in params:
            queryset = queryset.filter(
                account__isnull=not params["assigned"]
            )
        paginator = Paginator(
            queryset.order_by("-created_at", "-id"),
            params["page_size"],
        )
        try:
            page = paginator.page(params["page"])
        except EmptyPage:
            return Response({
                "success": False,
                "message": "Trang không tồn tại.",
            }, status=400)
        response = Response({
            "success": True,
            "data": [
                proxy_to_dict(proxy)
                for proxy in page.object_list
            ],
            "pagination": {
                "page": page.number,
                "page_size": params["page_size"],
                "total": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
            },
        })
        response["Cache-Control"] = "private, no-store"
        return response

    def post(self, request, pipeline_id):
        pipeline = resolve_proxy_pipeline(
            request.user,
            pipeline_id,
        )
        serializer = ProxyCreateSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                Pipeline.objects.select_for_update().get(
                    pk=pipeline.pk
                )
                proxy = persist_proxy(
                    pipeline=pipeline,
                    data=serializer.validated_data,
                )
        except DjangoValidationError as exc:
            return validation_response(exc)
        except IntegrityError:
            return Response({
                "success": False,
                "message": (
                    "Proxy hoặc Facebook Account đã được gán."
                ),
            }, status=409)
        response = Response({
            "success": True,
            "message": "Đã thêm Proxy.",
            "data": proxy_to_dict(proxy),
        }, status=201)
        response["Cache-Control"] = "private, no-store"
        return response


class ProxyBulkAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request, pipeline_id):
        pipeline = resolve_proxy_pipeline(
            request.user,
            pipeline_id,
        )
        serializer = ProxyBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        class RowError(Exception):
            def __init__(self, index):
                self.index = index

        created = []
        try:
            with transaction.atomic():
                Pipeline.objects.select_for_update().get(
                    pk=pipeline.pk
                )
                for index, item in enumerate(
                    serializer.validated_data["items"],
                    start=1,
                ):
                    try:
                        proxy = persist_proxy(
                            pipeline=pipeline,
                            data=item,
                        )
                    except DjangoValidationError as exc:
                        raise RowError(index) from exc
                    created.append(proxy)
        except RowError as exc:
            return Response({
                "success": False,
                "message": (
                    f"Proxy thứ {exc.index} không hợp lệ. "
                    "Toàn bộ lô đã được rollback."
                ),
            }, status=400)
        except IntegrityError:
            return Response({
                "success": False,
                "message": (
                    "Có Proxy hoặc tài khoản bị trùng. "
                    "Toàn bộ lô đã được rollback."
                ),
            }, status=409)
        response = Response({
            "success": True,
            "message": f"Đã thêm {len(created)} Proxy.",
            "data": {
                "created": len(created),
            },
        }, status=201)
        response["Cache-Control"] = "private, no-store"
        return response


class ProxyDetailAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def get_proxy(self, pipeline_id, proxy_id):
        proxy = (
            ProxyEndpoint.objects
            .filter(
                pk=proxy_id,
                pipeline_id=pipeline_id,
            )
            .select_related("account", "auth_secret")
            .first()
        )
        if proxy is None:
            raise Http404("Proxy không tồn tại.")
        return proxy

    def get(self, request, pipeline_id, proxy_id):
        pipeline = resolve_proxy_pipeline(
            request.user,
            pipeline_id,
        )
        proxy = self.get_proxy(pipeline.pk, proxy_id)
        response = Response({
            "success": True,
            "data": proxy_to_dict(proxy),
        })
        response["Cache-Control"] = "private, no-store"
        return response

    def patch(self, request, pipeline_id, proxy_id):
        pipeline = resolve_proxy_pipeline(
            request.user,
            pipeline_id,
        )
        serializer = ProxyUpdateSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                Pipeline.objects.select_for_update().get(
                    pk=pipeline.pk
                )
                proxy = (
                    ProxyEndpoint.objects
                    .select_for_update()
                    .filter(
                        pk=proxy_id,
                        pipeline_id=pipeline.pk,
                    )
                    .first()
                )
                if proxy is None:
                    raise Http404("Proxy không tồn tại.")
                proxy = persist_proxy(
                    pipeline=pipeline,
                    instance=proxy,
                    data=serializer.validated_data,
                )
        except DjangoValidationError as exc:
            return validation_response(exc)
        except IntegrityError:
            return Response({
                "success": False,
                "message": (
                    "Proxy hoặc tài khoản đã được sử dụng."
                ),
            }, status=409)
        proxy = self.get_proxy(pipeline.pk, proxy_id)
        response = Response({
            "success": True,
            "message": "Đã cập nhật Proxy.",
            "data": proxy_to_dict(proxy),
        })
        response["Cache-Control"] = "private, no-store"
        return response

    def delete(self, request, pipeline_id, proxy_id):
        pipeline = resolve_proxy_pipeline(
            request.user,
            pipeline_id,
        )
        with transaction.atomic():
            Pipeline.objects.select_for_update().get(
                pk=pipeline.pk
            )
            proxy = (
                ProxyEndpoint.objects
                .select_for_update()
                .filter(
                    pk=proxy_id,
                    pipeline_id=pipeline.pk,
                )
                .first()
            )
            if proxy is None:
                raise Http404("Proxy không tồn tại.")
            proxy.delete()
        response = Response({
            "success": True,
            "message": "Đã xóa Proxy.",
        })
        response["Cache-Control"] = "private, no-store"
        return response
