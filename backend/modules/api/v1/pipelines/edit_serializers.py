from django.contrib.auth import get_user_model
from django.core.validators import validate_unicode_slug
from rest_framework import serializers
from modules.pipelines.models import Pipeline
User = get_user_model()
class PipelineEditSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=150,
        trim_whitespace=True,
    )
    ctv_username = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=150,
        trim_whitespace=True,
    )
    ctv_email = serializers.EmailField(
        required=False,
        allow_blank=False,
        max_length=254,
    )
    def validate(self, attrs):
        allowed = {
            "name",
            "ctv_username",
            "ctv_email",
        }
        if not isinstance(self.initial_data, dict):
            raise serializers.ValidationError(
                "Dữ liệu phải là JSON object."
            )
        keys = set(self.initial_data)
        if not keys or not keys.issubset(allowed):
            raise serializers.ValidationError(
                "Chỉ cho phép sửa tên Pipeline, username và email CTV."
            )
        pipeline = self.context["pipeline"]
        ctv = pipeline.ctv
        if "name" in attrs:
            duplicate = Pipeline.objects.filter(
                name__iexact=attrs["name"]
            ).exclude(pk=pipeline.pk).exists()
            if duplicate:
                raise serializers.ValidationError({
                    "name": "Tên Pipeline đã tồn tại."
                })
        if "ctv_username" in attrs:
            username = attrs["ctv_username"]
            try:
                validate_unicode_slug(username)
            except Exception:
                raise serializers.ValidationError({
                    "ctv_username": "Username không hợp lệ."
                })
            duplicate = User.objects.filter(
                username__iexact=username
            ).exclude(pk=ctv.pk).exists()
            if duplicate:
                raise serializers.ValidationError({
                    "ctv_username": "Username đã tồn tại."
                })
        return attrs
