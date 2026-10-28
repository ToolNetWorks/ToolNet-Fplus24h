from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework import serializers
class CTVPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )
    confirm_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        max_length=128,
    )
    def validate(self, attrs):
        password = attrs["new_password"]
        confirm = attrs["confirm_password"]
        if password != confirm:
            raise serializers.ValidationError({
                "confirm_password": "Mật khẩu xác nhận không khớp."
            })
        ctv = self.context.get("ctv")
        if ctv is None:
            raise serializers.ValidationError(
                "Không xác định được tài khoản CTV."
            )
        try:
            validate_password(password, user=ctv)
        except ValidationError as exc:
            raise serializers.ValidationError({
                "new_password": exc.messages
            }) from exc
        return attrs
