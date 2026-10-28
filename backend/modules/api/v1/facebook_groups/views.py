from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.core.paginator import EmptyPage, Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from .serializers import (
    FacebookGroupCreateSerializer,
    FacebookGroupUpdateSerializer,
    FacebookGroupFilterSerializer,
)
def get_accessible_pipeline(user, pipeline_id):
    if not user.is_active:
        raise PermissionDenied(
            "Tài khoản đã bị khóa."
        )
    if user.is_superuser and user.is_staff:
        pipeline = Pipeline.objects.filter(
            pk=pipeline_id,
        ).first()
        if pipeline is None:
            raise Http404("Pipeline không tồn tại.")
        return pipeline
    if user.is_staff or user.is_superuser:
        raise Http404("Pipeline không tồn tại.")
    pipeline = Pipeline.objects.filter(
        pk=pipeline_id,
        ctv_id=user.pk,
    ).first()
    if pipeline is None:
        raise Http404("Pipeline không tồn tại.")
    if pipeline.status != Pipeline.Status.ACTIVE:
        raise PermissionDenied(
            "Pipeline đang bị khóa."
        )
    return pipeline
def serialize_group(group):
    return {
        "id": str(group.pk),
        "pipeline_id": str(group.pipeline_id),
        "name": group.name,
        "group_url": group.group_url,
        "group_key": group.group_key,
        "is_enabled": group.is_enabled,
        "verification_status": group.verification_status,
        "notes": group.notes,
        "created_at": group.created_at.isoformat(),
        "updated_at": group.updated_at.isoformat(),
    }
def validation_error_response(exc):
    if hasattr(exc, "message_dict"):
        errors = exc.message_dict
    else:
        errors = {"non_field_errors": exc.messages}
    return Response(
        {
            "success": False,
            "message": "Dữ liệu Group không hợp lệ.",
            "errors": errors,
        },
        status=status.HTTP_400_BAD_REQUEST,
    )
class FacebookGroupBaseAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    def get_pipeline(self, request, pipeline_id):
        return get_accessible_pipeline(
            request.user,
            pipeline_id,
        )
class FacebookGroupCollectionAPIView(FacebookGroupBaseAPIView):
    def get(self, request, pipeline_id):
        pipeline = self.get_pipeline(
            request,
            pipeline_id,
        )
        serializer = FacebookGroupFilterSerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data
        queryset = FacebookGroup.objects.filter(
            pipeline_id=pipeline.pk,
        ).order_by("-created_at", "-id")
        search = filters.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(group_url__icontains=search)
            )
        if "enabled" in filters:
            queryset = queryset.filter(
                is_enabled=filters["enabled"]
            )
        paginator = Paginator(
            queryset,
            filters["page_size"],
        )
        try:
            page = paginator.page(filters["page"])
        except EmptyPage:
            return Response(
                {
                    "success": False,
                    "message": "Trang không tồn tại.",
                },
                status=400,
            )
        response = Response({
            "success": True,
            "data": [
                serialize_group(group)
                for group in page.object_list
            ],
            "pagination": {
                "page": page.number,
                "page_size": filters["page_size"],
                "total": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "has_previous": page.has_previous(),
            },
        })
        response["Cache-Control"] = "private, no-store"
        return response
    def post(self, request, pipeline_id):
        pipeline = self.get_pipeline(
            request,
            pipeline_id,
        )
        serializer = FacebookGroupCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                group = FacebookGroup(
                    pipeline=pipeline,
                    **serializer.validated_data,
                )
                group.save()
        except DjangoValidationError as exc:
            return validation_error_response(exc)
        except IntegrityError:
            return Response(
                {
                    "success": False,
                    "message": (
                        "Group đã tồn tại trong Pipeline "
                        "hoặc vi phạm ràng buộc database."
                    ),
                },
                status=409,
            )
        return Response(
            {
                "success": True,
                "message": "Đã thêm Facebook Group.",
                "data": serialize_group(group),
            },
            status=201,
        )
class FacebookGroupDetailAPIView(FacebookGroupBaseAPIView):
    def get_group(self, request, pipeline_id, group_id):
        pipeline = self.get_pipeline(
            request,
            pipeline_id,
        )
        group = FacebookGroup.objects.filter(
            pk=group_id,
            pipeline_id=pipeline.pk,
        ).first()
        if group is None:
            raise Http404("Group không tồn tại.")
        return group
    def get(self, request, pipeline_id, group_id):
        group = self.get_group(
            request,
            pipeline_id,
            group_id,
        )
        response = Response({
            "success": True,
            "data": serialize_group(group),
        })
        response["Cache-Control"] = "private, no-store"
        return response
    def patch(self, request, pipeline_id, group_id):
        # Check ownership before accepting changes.
        self.get_group(
            request,
            pipeline_id,
            group_id,
        )
        serializer = FacebookGroupUpdateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                group = (
                    FacebookGroup.objects
                    .select_for_update()
                    .get(
                        pk=group_id,
                        pipeline_id=pipeline_id,
                    )
                )
                for field, value in serializer.validated_data.items():
                    setattr(group, field, value)
                # Model.save() runs full_clean()
                # and normalizes the Group URL.
                group.save()
        except FacebookGroup.DoesNotExist:
            raise Http404("Group không tồn tại.")
        except DjangoValidationError as exc:
            return validation_error_response(exc)
        except IntegrityError:
            return Response(
                {
                    "success": False,
                    "message": (
                        "Group đã tồn tại hoặc không thể cập nhật."
                    ),
                },
                status=409,
            )
        return Response({
            "success": True,
            "message": "Đã cập nhật Facebook Group.",
            "data": serialize_group(group),
        })
