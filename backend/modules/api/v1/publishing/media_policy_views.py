"""Pipeline-bound media configuration: GET (read), PUT (replace atomically)."""

from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.albums.models import Album, AlbumImage
from modules.pipelines.models import Pipeline
from modules.publishing.models import PipelineAlbumSource, PipelineMediaPolicy
from modules.api.v1.albums.views import resolve_pipeline


MAX_SOURCES = 50


class PolicyWriteThrottle(UserRateThrottle):
    rate = "30/min"


class SourceSerializer(serializers.Serializer):
    album_id = serializers.UUIDField()
    is_enabled = serializers.BooleanField(default=True)

    def run_validation(self, data=serializers.empty):
        # Nested serializers do not receive self.initial_data automatically.
        self._raw_input = data
        return super().run_validation(data)

    def validate(self, attrs):
        raw = getattr(self, "_raw_input", None)
        if not isinstance(raw, dict) or not set(raw).issubset(
            {"album_id", "is_enabled"}
        ):
            raise serializers.ValidationError("Trường nguồn Album không hợp lệ.")
        if "is_enabled" in raw and type(raw["is_enabled"]) is not bool:
            raise serializers.ValidationError({"is_enabled": "Phải là boolean."})
        return attrs


class PolicySerializer(serializers.Serializer):
    version = serializers.CharField(allow_null=True, max_length=50)
    is_enabled = serializers.BooleanField()
    album_selection = serializers.ChoiceField(
        choices=PipelineMediaPolicy.SelectionMode.choices
    )
    image_selection = serializers.ChoiceField(
        choices=PipelineMediaPolicy.SelectionMode.choices
    )
    reuse_policy = serializers.ChoiceField(
        choices=PipelineMediaPolicy.ReusePolicy.choices
    )
    images_per_post = serializers.IntegerField(min_value=1, max_value=10)
    sources = SourceSerializer(many=True, allow_empty=True, max_length=MAX_SOURCES)

    def validate(self, attrs):
        raw = self.initial_data
        allowed = {
            "version", "is_enabled", "album_selection", "image_selection",
            "reuse_policy", "images_per_post", "sources",
        }
        if not isinstance(raw, dict) or set(raw) != allowed:
            raise serializers.ValidationError(
                "Cần gửi đủ version, chính sách và danh sách sources."
            )
        if type(raw["is_enabled"]) is not bool:
            raise serializers.ValidationError({"is_enabled": "Phải là boolean."})
        if type(raw["images_per_post"]) is not int:
            raise serializers.ValidationError({"images_per_post": "Phải là số nguyên."})
        ids = [item["album_id"] for item in attrs["sources"]]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError({"sources": "Album bị chọn trùng."})
        return attrs


def policy_payload(pipeline_id):
    policy = PipelineMediaPolicy.objects.filter(pipeline_id=pipeline_id).first()
    rows = (
        PipelineAlbumSource.objects.filter(pipeline_id=pipeline_id)
        .select_related("album")
        .annotate(
            ready_image_count=Count(
                "album__images", filter=Q(album__images__upload_status=AlbumImage.UploadStatus.READY)
            )
        )
        .order_by("position", "id")
    )
    return {
        "pipeline_id": str(pipeline_id),
        "version": policy.updated_at.isoformat() if policy else None,
        "is_enabled": policy.is_enabled if policy else False,
        "album_selection": (
            policy.album_selection if policy else PipelineMediaPolicy.SelectionMode.IN_ORDER
        ),
        "image_selection": (
            policy.image_selection if policy else PipelineMediaPolicy.SelectionMode.IN_ORDER
        ),
        "reuse_policy": (
            policy.reuse_policy if policy else PipelineMediaPolicy.ReusePolicy.NO_REPEAT
        ),
        "images_per_post": policy.images_per_post if policy else 1,
        "sources": [
            {
                "id": str(row.pk),
                "album_id": str(row.album_id),
                "album_name": row.album.name,
                "album_is_enabled": row.album.is_enabled,
                "ready_image_count": row.ready_image_count,
                "position": row.position,
                "is_enabled": row.is_enabled,
            }
            for row in rows
        ],
    }


def reject(message, status=400):
    return Response({"success": False, "message": message}, status=status)


class PipelineMediaPolicyAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    throttle_classes = [PolicyWriteThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        response = Response({"success": True, "data": policy_payload(pipeline.pk)})
        response["Cache-Control"] = "private, no-store"
        return response

    def put(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        serializer = PolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        requested = values["sources"]
        requested_ids = [row["album_id"] for row in requested]

        with transaction.atomic():
            locked_pipeline = Pipeline.objects.select_for_update().filter(pk=pipeline.pk).first()
            if locked_pipeline is None:
                raise Http404("Pipeline không tồn tại.")
            if not request.user.is_superuser and locked_pipeline.status != Pipeline.Status.ACTIVE:
                return reject("Pipeline đã bị khóa.", 403)

            existing_policy = (
                PipelineMediaPolicy.objects.select_for_update()
                .filter(pipeline_id=pipeline.pk).first()
            )
            current_version = (
                existing_policy.updated_at.isoformat() if existing_policy else None
            )
            if values["version"] != current_version:
                return reject("Cấu hình đã thay đổi. Tải lại trước khi lưu.", 409)

            # Check ALL supplied album IDs, including disabled ones, for tenant isolation.
            albums = {
                album.pk: album
                for album in Album.objects.filter(
                    pipeline_id=pipeline.pk,
                    pk__in=requested_ids,
                ).annotate(
                    ready_count=Count(
                        "images", filter=Q(images__upload_status=AlbumImage.UploadStatus.READY)
                    )
                )
            }
            if len(albums) != len(requested_ids):
                return reject("Album không tồn tại hoặc không thuộc Pipeline.", 404)

            active_sources = [row for row in requested if row["is_enabled"]]
            if values["is_enabled"]:
                if not active_sources:
                    return reject("Phải chọn ít nhất một nguồn Album đang bật.")
                if any(not albums[row["album_id"]].is_enabled for row in active_sources):
                    return reject("Một nguồn Album đang tắt trong thư viện.")
                if any(albums[row["album_id"]].ready_count < 1 for row in active_sources):
                    return reject("Mỗi nguồn Album đang bật cần ít nhất một ảnh sẵn sàng.")
                ready_total = sum(albums[row["album_id"]].ready_count for row in active_sources)
                if ready_total < values["images_per_post"]:
                    return reject("Không đủ ảnh sẵn sàng cho số ảnh mỗi bài đăng.")

            # Preserve existing source IDs and timestamps when reordering.
            old_rows = list(
                PipelineAlbumSource.objects.select_for_update()
                .filter(pipeline_id=pipeline.pk)
                .order_by("position", "id")
            )
            old_by_album = {source.album_id: source for source in old_rows}
            keep_ids = set(requested_ids)
            retained = [row for row in old_rows if row.album_id in keep_ids]
            max_position = max([row.position for row in retained] + [len(requested), 0])
            temp_start = max_position + len(retained) + 1
            if temp_start + len(retained) > 32767:
                return reject("Dữ liệu thứ tự Album không hợp lệ.", 409)

            for row in old_rows:
                if row.album_id not in keep_ids:
                    row.delete()

            # Move retained rows out of the final 1..N range before reassigning.
            for i, row in enumerate(retained):
                PipelineAlbumSource.objects.filter(pk=row.pk).update(
                    position=temp_start + i
                )

            for index, row in enumerate(requested, start=1):
                source = old_by_album.get(row["album_id"])
                if source is None:
                    source = PipelineAlbumSource(
                        pipeline=locked_pipeline,
                        album=albums[row["album_id"]],
                    )
                source.position = index
                source.is_enabled = row["is_enabled"]
                source.save()

            policy = existing_policy or PipelineMediaPolicy(pipeline=locked_pipeline)
            for field in (
                "is_enabled", "album_selection", "image_selection",
                "reuse_policy", "images_per_post",
            ):
                setattr(policy, field, values[field])
            policy.save()

        response = Response({"success": True, "data": policy_payload(pipeline.pk)})
        response["Cache-Control"] = "private, no-store"
        return response
