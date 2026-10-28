from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Q
from django.http import Http404
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.facebook_accounts.models import FacebookAccount
from modules.pipelines.models import Pipeline


class FacebookAccountFilterSerializer(serializers.Serializer):
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
        choices=FacebookAccount.ConnectionStatus.choices,
    )


class FacebookAccountListAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pipeline_id):
        user = request.user
        if not user.is_active:
            return Response(
                {"detail": "Tài khoản đã bị khóa."},
                status=403,
            )
        pipeline = (
            Pipeline.objects
            .filter(pk=pipeline_id)
            .first()
        )
        if pipeline is None:
            raise Http404("Pipeline không tồn tại.")
        if not user.is_superuser:
            if user.is_staff or pipeline.ctv_id != user.pk:
                raise Http404("Pipeline không tồn tại.")
            if pipeline.status != "active":
                return Response(
                    {"detail": "Pipeline đang bị khóa."},
                    status=403,
                )
        filters = FacebookAccountFilterSerializer(
            data=request.query_params
        )
        filters.is_valid(raise_exception=True)
        params = filters.validated_data

        base_queryset = FacebookAccount.objects.filter(
            pipeline_id=pipeline.pk
        )
        summary = base_queryset.aggregate(
            total=Count("id"),
            connected=Count(
                "id",
                filter=Q(connection_status="connected"),
            ),
            not_connected=Count(
                "id",
                filter=Q(connection_status="not_connected"),
            ),
            expired=Count(
                "id",
                filter=Q(connection_status="expired"),
            ),
            disabled=Count(
                "id",
                filter=Q(connection_status="disabled"),
            ),
        )
        queryset = base_queryset.order_by(
            "-created_at", "-id"
        )

        search = params.get("search", "")
        if search:
            queryset = queryset.filter(
                Q(label__icontains=search)
                | Q(profile_url__icontains=search)
                | Q(facebook_user_id__icontains=search)
            )
        selected_status = params.get("status")
        if selected_status:
            queryset = queryset.filter(
                connection_status=selected_status
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
                status=400,
            )
        items = [
            {
                "id": str(account.pk),
                "pipeline_id": str(account.pipeline_id),
                "label": account.label,
                "profile_url": account.profile_url,
                "facebook_user_id": account.facebook_user_id,
                "connection_status": account.connection_status,
                "last_verified_at": (
                    account.last_verified_at.isoformat()
                    if account.last_verified_at
                    else None
                ),
                "created_at": account.created_at.isoformat(),
                "updated_at": account.updated_at.isoformat(),
            }
            for account in page.object_list
        ]
        return Response({
            "success": True,
            "data": items,
            "summary": summary,
            "pagination": {
                "page": page.number,
                "page_size": params["page_size"],
                "total": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
            },
        })
