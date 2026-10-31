from urllib.parse import urlsplit
from rest_framework import serializers
from .models import AIProvider, StorageConfig


def validate_endpoint(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise serializers.ValidationError("Endpoint phải là HTTPS, không chứa credentials hoặc query.")
    return value.rstrip("/")


class AIProviderSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(default=True)
    is_default = serializers.BooleanField(default=False)
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=8192)
    base_url = serializers.CharField(validators=[validate_endpoint], max_length=500)
    priority = serializers.IntegerField(min_value=1, max_value=10000, required=False)
    timeout_seconds = serializers.IntegerField(min_value=1, max_value=120, required=False)
    models = serializers.ListField(source="available_models", child=serializers.CharField(max_length=120), required=False, max_length=100)

    class Meta:
        model = AIProvider
        fields = ("id", "name", "provider_type", "base_url", "default_model", "models", "is_active", "is_default", "priority", "timeout_seconds", "api_key", "has_api_key", "last_status", "last_latency_ms")
        read_only_fields = ("id", "has_api_key", "last_status", "last_latency_ms")

    def validate(self, data):
        if self.instance is None and not data.get("api_key"):
            raise serializers.ValidationError({"api_key": "Vui lòng nhập API Key."})
        if data.get("is_default", getattr(self.instance, "is_default", False)) and not data.get("is_active", getattr(self.instance, "is_active", True)):
            raise serializers.ValidationError("Provider mặc định phải được bật.")
        return data

    def create(self, validated_data):
        key = validated_data.pop("api_key", "")
        obj = AIProvider(**validated_data)
        obj.set_api_key(key)
        if obj.is_default:
            AIProvider.objects.filter(is_default=True).update(is_default=False)
        obj.save()
        return obj

    def update(self, instance, validated_data):
        key = validated_data.pop("api_key", "")
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if key:
            instance.set_api_key(key)
        if instance.is_default:
            AIProvider.objects.exclude(pk=instance.pk).filter(is_default=True).update(is_default=False)
        instance.save()
        return instance


class StorageConfigSerializer(serializers.ModelSerializer):
    secret_access_key = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=8192)
    access_key_id = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=120)
    endpoint_url = serializers.CharField(validators=[validate_endpoint], required=False, allow_blank=True, max_length=500)

    class Meta:
        model = StorageConfig
        fields = ("account_id", "endpoint_url", "bucket_name", "access_key_id", "secret_access_key", "is_active")
