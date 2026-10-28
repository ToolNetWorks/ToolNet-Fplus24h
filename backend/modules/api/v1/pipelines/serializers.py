from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework import serializers

from modules.pipelines.models import Pipeline


class PipelineCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)

    status = serializers.ChoiceField(
        choices=Pipeline.Status.choices,
        default=Pipeline.Status.ACTIVE,
    )

    ctv_username = serializers.CharField(max_length=150)
    ctv_email = serializers.EmailField(max_length=254)

    ctv_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    ctv_password_confirm = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate_name(self, value):
        value = value.strip()

        if Pipeline.objects.filter(
            name__iexact=value
        ).exists():
            raise serializers.ValidationError(
                "Tên Pipeline đã tồn tại."
            )

        return value

    def validate_ctv_username(self, value):
        value = value.strip()

        User = get_user_model()
        username_field = User._meta.get_field(
            User.USERNAME_FIELD
        )

        try:
            username_field.run_validators(value)
        except ValidationError as exc:
            raise serializers.ValidationError(
                exc.messages
            ) from exc

        if User.objects.filter(
            username__iexact=value
        ).exists():
            raise serializers.ValidationError(
                "Username CTV đã tồn tại."
            )

        return value

    def validate(self, attrs):
        password = attrs["ctv_password"]
        confirmation = attrs["ctv_password_confirm"]

        if password != confirmation:
            raise serializers.ValidationError({
                "ctv_password_confirm":
                    "Mật khẩu xác nhận không khớp."
            })

        User = get_user_model()
        user = User(
            username=attrs["ctv_username"],
            email=attrs["ctv_email"],
        )

        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise serializers.ValidationError({
                "ctv_password": exc.messages
            }) from exc

        return attrs
