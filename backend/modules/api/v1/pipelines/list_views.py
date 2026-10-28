from django.core.paginator import EmptyPage, Paginator
from django.db.models import Q
from rest_framework import serializers, status
from rest_framework.response import Response

from modules.pipelines.models import Pipeline

from .views import PipelineCreateAPIView


class PipelineListFilterSerializer(serializers.Serializer):
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


class PipelineCollectionAPIView(PipelineCreateAPIView):
    """
    GET: List pipelines.
    POST: Create pipeline + CTV (inherited).
    Authentication and Super Admin permission
    are inherited from PipelineCreateAPIView.
    """

    def get(self, request):
        filters = PipelineListFilterSerializer(
            data=request.query_params
        )
        filters.is_valid(raise_exception=True)

        params = filters.validated_data

        queryset = Pipeline.objects.select_related(
            "ctv"
        ).order_by("-created_at", "-pk")

        search = params.get("search", "")

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(ctv__username__icontains=search)
                | Q(ctv__email__icontains=search)
            )

        selected_status = params.get("status")

        if selected_status:
            queryset = queryset.filter(
                status=selected_status
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

        items = [
            {
                "id": str(pipeline.pk),
                "name": pipeline.name,
                "status": pipeline.status,
                "created_at": pipeline.created_at.isoformat(),
                "ctv": {
                    "id": pipeline.ctv_id,
                    "username": pipeline.ctv.username,
                    "email": pipeline.ctv.email,
                    "is_active": pipeline.ctv.is_active,
                },
            }
            for pipeline in page.object_list
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
