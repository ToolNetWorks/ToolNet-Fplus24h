from django.db import transaction
from django.http import Http404
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from modules.albums.models import Album, AlbumImage
from .views import resolve_pipeline
class ImageReorderSerializer(serializers.Serializer):
    image_id = serializers.UUIDField()
    direction = serializers.ChoiceField(
        choices=["up", "down"],
        required=False,
    )
    target_id = serializers.UUIDField(required=False)
    placement = serializers.ChoiceField(
        choices=["before", "after"],
        required=False,
        default="before",
    )
    def validate(self, attrs):
        if not isinstance(self.initial_data, dict):
            raise serializers.ValidationError(
                "Dữ liệu phải là JSON object."
            )
        keys = set(self.initial_data)
        allowed = {
            "image_id",
            "direction",
            "target_id",
            "placement",
        }
        if not keys.issubset(allowed):
            raise serializers.ValidationError(
                "Có trường dữ liệu không được phép."
            )
        has_direction = "direction" in attrs
        has_target = "target_id" in attrs
        if has_direction == has_target:
            raise serializers.ValidationError(
                "Chọn direction hoặc target_id."
            )
        if has_direction and "placement" in self.initial_data:
            raise serializers.ValidationError(
                "placement chỉ dùng với target_id."
            )
        if (
            has_target
            and attrs["target_id"] == attrs["image_id"]
        ):
            raise serializers.ValidationError(
                "Không thể di chuyển ảnh vào chính nó."
            )
        return attrs
class AlbumImageReorderAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    def patch(self, request, pipeline_id, album_id):
        pipeline = resolve_pipeline(
            request.user,
            pipeline_id,
        )
        serializer = ImageReorderSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            # Shared lock with upload and delete services.
            album = (
                Album.objects
                .select_for_update()
                .filter(
                    pk=album_id,
                    pipeline_id=pipeline.pk,
                )
                .first()
            )
            if album is None:
                raise Http404("Album không tồn tại.")
            images = list(
                AlbumImage.objects
                .filter(album_id=album.pk)
                .order_by("position", "created_at", "id")
            )
            if len(images) > 5000:
                return Response({
                    "success": False,
                    "message": (
                        "Album có quá nhiều ảnh để "
                        "sắp xếp bằng API này."
                    ),
                }, status=409)
            ids = {
                str(image.pk): image
                for image in images
            }
            source_id = str(data["image_id"])
            source = ids.get(source_id)
            if (
                source is None
                or source.upload_status
                != AlbumImage.UploadStatus.READY
            ):
                return Response({
                    "success": False,
                    "message": (
                        "Ảnh không tồn tại hoặc "
                        "không ở trạng thái sẵn sàng."
                    ),
                }, status=409)
            source_index = images.index(source)
            if "direction" in data:
                step = (
                    -1
                    if data["direction"] == "up"
                    else 1
                )
                neighbor_index = source_index + step
                while 0 <= neighbor_index < len(images):
                    if (
                        images[neighbor_index].upload_status
                        == AlbumImage.UploadStatus.READY
                    ):
                        break
                    neighbor_index += step
                if not 0 <= neighbor_index < len(images):
                    return Response({
                        "success": False,
                        "message": "Ảnh đã ở đầu hoặc cuối Album.",
                    }, status=409)
                # Swap only ready images.
                images[source_index], images[neighbor_index] = (
                    images[neighbor_index],
                    images[source_index],
                )
            else:
                target = ids.get(str(data["target_id"]))
                if (
                    target is None
                    or target.upload_status
                    != AlbumImage.UploadStatus.READY
                ):
                    return Response({
                        "success": False,
                        "message": (
                            "Ảnh đích không thuộc Album "
                            "hoặc không sẵn sàng."
                        ),
                    }, status=409)
                images.pop(source_index)
                target_index = images.index(target)
                if data["placement"] == "after":
                    target_index += 1
                images.insert(target_index, source)
            changed = []
            for position, image in enumerate(images, start=1):
                if image.position == position:
                    continue
                image.position = position
                changed.append(image)
            if changed:
                AlbumImage.objects.bulk_update(
                    changed,
                    ["position"],
                    batch_size=500,
                )
            response = Response({
                "success": True,
                "message": "Đã lưu thứ tự ảnh.",
                "data": {
                    "image_id": source_id,
                    "position": source.position,
                    "updated_count": len(changed),
                },
            })
            response["Cache-Control"] = "private, no-store"
            return response
