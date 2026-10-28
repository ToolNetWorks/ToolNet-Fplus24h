from rest_framework import serializers
class FacebookGroupCreateSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=200,
        trim_whitespace=True,
    )
    group_url = serializers.URLField(
        max_length=500,
    )
    is_enabled = serializers.BooleanField(
        default=True,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
    )
class FacebookGroupUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=False,
        max_length=200,
        trim_whitespace=True,
    )
    group_url = serializers.URLField(
        required=False,
        max_length=500,
    )
    is_enabled = serializers.BooleanField(
        required=False,
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=5000,
    )
    def validate(self, attrs):
        allowed = {
            "name",
            "group_url",
            "is_enabled",
            "notes",
        }
        if not isinstance(self.initial_data, dict):
            raise serializers.ValidationError(
                "Dữ liệu phải là JSON object."
            )
        keys = set(self.initial_data)
        if not keys or not keys.issubset(allowed):
            raise serializers.ValidationError(
                "Chỉ được sửa tên, URL, ghi chú và trạng thái bật/tắt."
            )
        return attrs
class FacebookGroupFilterSerializer(serializers.Serializer):
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
    )
    enabled = serializers.BooleanField(
        required=False,
    )
    verification_status = serializers.ChoiceField(
        choices=[
            "unknown",
            "verified",
            "unavailable",
        ],
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enabled"].default_empty_html = serializers.empty
