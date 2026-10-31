from django.contrib.auth import get_user_model
from django.core.paginator import EmptyPage, Paginator
from django.db.models import F, Q
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.api.v1.permissions import IsSuperAdmin
from modules.pipelines.models import CTVAdminAuditLog, Pipeline

from ..pipelines.views import PipelineCreateAPIView


class CTVListFilterSerializer(serializers.Serializer):
    page = serializers.IntegerField(
        min_value=1,
        default=1,
    )

    page_size = serializers.IntegerField(
        min_value=1,
        max_value=50,
        default=10,
    )

    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        trim_whitespace=True,
    )

    status = serializers.ChoiceField(
        required=False,
        choices=Pipeline.Status.choices,
    )


class CTVCollectionAPIView(PipelineCreateAPIView):
    """
    GET: List CTVs with their Pipeline and actual last login.
    POST: Create CTV + Pipeline (inherited, one transaction).
    """

    def get(self, request):
        filters = CTVListFilterSerializer(
            data=request.query_params
        )
        filters.is_valid(raise_exception=True)

        params = filters.validated_data

        User = get_user_model()

        queryset = (
            User.objects
            .filter(is_staff=False, is_superuser=False)
            .select_related("pipeline")
            .order_by(
                F("pipeline__created_at").desc(nulls_last=True),
                "-pk",
            )
        )

        search = params.get("search", "")

        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(pipeline__name__icontains=search)
            )

        selected_status = params.get("status")

        if selected_status == Pipeline.Status.ACTIVE:
            queryset = queryset.filter(
                is_active=True,
                pipeline__status=Pipeline.Status.ACTIVE,
            )
        elif selected_status == Pipeline.Status.DISABLED:
            queryset = queryset.filter(
                Q(is_active=False)
                | Q(pipeline__status=Pipeline.Status.DISABLED)
            )

        paginator = Paginator(
            queryset,
            params["page_size"],
        )

        try:
            page = paginator.page(params["page"])
        except EmptyPage:
            return Response(
                {
                    "success": False,
                    "message": "Trang không tồn tại.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = []

        for ctv in page.object_list:
            try:
                pipeline = ctv.pipeline
            except Pipeline.DoesNotExist:
                pipeline = None

            items.append({
                "id": (
                    str(pipeline.pk)
                    if pipeline is not None
                    else f"ctv-{ctv.pk}"
                ),
                "pipeline": (
                    {
                        "id": str(pipeline.pk),
                        "name": pipeline.name,
                        "status": pipeline.status,
                        "created_at": pipeline.created_at.isoformat(),
                    }
                    if pipeline is not None
                    else None
                ),
                "ctv": {
                    "id": ctv.pk,
                    "username": ctv.username,
                    "email": ctv.email,
                    "is_active": ctv.is_active,
                    "last_login": (
                        ctv.last_login.isoformat()
                        if ctv.last_login
                        else None
                    ),
                },
            })

        return Response({
            "success": True,
            "data": items,
            "pagination": {
                "page": page.number,
                "page_size": params["page_size"],
                "total": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
            },
        })


class CTVAuditLogFilterSerializer(serializers.Serializer):
    page = serializers.IntegerField(
        min_value=1,
        default=1,
    )

    page_size = serializers.IntegerField(
        min_value=1,
        max_value=50,
        default=10,
    )


class CTVAdminAuditLogAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        filters = CTVAuditLogFilterSerializer(
            data=request.query_params
        )
        filters.is_valid(raise_exception=True)

        params = filters.validated_data

        queryset = CTVAdminAuditLog.objects.select_related(
            "admin"
        ).order_by("-created_at", "-pk")

        paginator = Paginator(
            queryset,
            params["page_size"],
        )

        try:
            page = paginator.page(params["page"])
        except EmptyPage:
            return Response(
                {
                    "success": False,
                    "message": "Trang không tồn tại.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = [
            {
                "id": entry.pk,
                "created_at": entry.created_at.isoformat(),
                "admin": {
                    "id": entry.admin_id,
                    "username": entry.admin_username,
                },
                "action": entry.action,
                "action_label": entry.get_action_display(),
                "pipeline_id": (
                    str(entry.pipeline_id)
                    if entry.pipeline_id
                    else None
                ),
                "pipeline_name": entry.pipeline_name,
                "ctv_id": entry.ctv_id,
                "ctv_username": entry.ctv_username,
            }
            for entry in page.object_list
        ]

        return Response({
            "success": True,
            "data": items,
            "pagination": {
                "page": page.number,
                "page_size": params["page_size"],
                "total": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
            },
        })
