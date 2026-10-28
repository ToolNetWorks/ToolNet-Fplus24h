from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from .views import get_accessible_pipeline


class GroupBulkThrottle(UserRateThrottle):
    rate = "15/min"


class GroupBulkSerializer(serializers.Serializer):
    group_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        min_length=1,
        max_length=50,
    )
    is_enabled = serializers.BooleanField()

    def validate(self, attrs):
        raw = self.initial_data
        if not isinstance(raw, dict):
            raise serializers.ValidationError(
                "Dữ liệu phải là JSON object."
            )
        if set(raw) != {"group_ids", "is_enabled"}:
            raise serializers.ValidationError(
                "Chỉ chấp nhận group_ids và is_enabled."
            )
        if type(raw["is_enabled"]) is not bool:
            raise serializers.ValidationError({
                "is_enabled": "Giá trị phải là boolean."
            })
        ids = attrs["group_ids"]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError({
                "group_ids": "Danh sách chứa Group trùng lặp."
            })
        return attrs


class FacebookGroupBulkStatusAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [GroupBulkThrottle]

    def post(self, request, pipeline_id):
        pipeline = get_accessible_pipeline(
            request.user,
            pipeline_id,
        )
        serializer = GroupBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        ids = payload["group_ids"]
        is_enabled = payload["is_enabled"]
        with transaction.atomic():
            Pipeline.objects.select_for_update().get(
                pk=pipeline.pk
            )
            groups = list(
                FacebookGroup.objects
                .select_for_update()
                .filter(
                    pipeline_id=pipeline.pk,
                    pk__in=ids,
                )
                .order_by("pk")
            )
            if len(groups) != len(ids):
                return Response({
                    "success": False,
                    "message": (
                        "Một hoặc nhiều Group không thuộc "
                        "Pipeline hoặc không tồn tại. "
                        "Không có thay đổi nào được lưu."
                    ),
                }, status=404)
            now = timezone.now()
            changed_ids = [
                group.pk
                for group in groups
                if group.is_enabled != is_enabled
            ]
            if changed_ids:
                FacebookGroup.objects.filter(
                    pipeline_id=pipeline.pk,
                    pk__in=changed_ids,
                ).update(
                    is_enabled=is_enabled,
                    updated_at=now,
                )
        response = Response({
            "success": True,
            "message": (
                "Đã bật các Group được chọn."
                if is_enabled
                else "Đã tắt các Group được chọn."
            ),
            "data": {
                "selected_count": len(ids),
                "updated_count": len(changed_ids),
                "is_enabled": is_enabled,
            },
        })
        response["Cache-Control"] = "private, no-store"
        return response
