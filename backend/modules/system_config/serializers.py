import json
from urllib.parse import urlsplit
from .ai_serializers import validate_headers
from .crypto import encrypt_secret
from rest_framework import serializers
from .models import AIProvider, StorageConfig, AIProviderKey, AIModel


def validate_endpoint(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise serializers.ValidationError("Endpoint phải là HTTPS, không chứa credentials hoặc query.")
    return value.rstrip("/")


class AIProviderSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(default=False)
    is_default = serializers.BooleanField(default=False)
    custom_headers = serializers.DictField(child=serializers.CharField(max_length=2048, allow_blank=True), write_only=True, required=False, validators=[validate_headers])
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=8192)
    base_url = serializers.CharField(validators=[validate_endpoint], max_length=500)
    priority = serializers.IntegerField(min_value=1, max_value=10000, required=False)
    timeout_seconds = serializers.IntegerField(min_value=1, max_value=120, required=False)
    models = serializers.ListField(source="available_models", child=serializers.CharField(max_length=120), required=False, max_length=100)

    class Meta:
        model = AIProvider
        fields = ("id", "name", "provider_type", "base_url", "default_model", "models", "is_active", "is_default", "priority", "timeout_seconds", "api_key", "custom_headers", "rotation_authorized", "has_api_key", "last_status", "last_latency_ms")
        read_only_fields = ("id", "has_api_key", "last_status", "last_latency_ms")

    def validate(self, data):
        if any(ord(c) < 32 or ord(c) > 126 for c in data.get("api_key", "")):
            raise serializers.ValidationError({"api_key": "Key không được chứa ký tự điều khiển hoặc ngoài ASCII."})
        if self.instance is None and not data.get("api_key"):
            raise serializers.ValidationError({"api_key": "Vui lòng nhập API Key."})
        if data.get("is_default", getattr(self.instance, "is_default", False)) and not data.get("is_active", getattr(self.instance, "is_active", True)):
            raise serializers.ValidationError("Provider mặc định phải được bật.")
        return data

    def create(self, validated_data):
        key = validated_data.pop("api_key", "")
        headers = validated_data.pop("custom_headers", {})
        obj = AIProvider(**validated_data)
        if headers:
            obj.custom_headers_encrypted = encrypt_secret(json.dumps(headers))
        obj.set_api_key(key)
        if obj.is_default:
            AIProvider.objects.filter(is_default=True).update(is_default=False)
        obj.save()
        if key:
            managed = AIProviderKey(provider=obj, name="Primary Key")
            managed.set_secret(key); managed.save()
        if obj.default_model:
            AIModel.objects.get_or_create(provider=obj, model_id=obj.default_model, defaults={"source": "legacy", "is_enabled": obj.is_active, "max_output_tokens": 1000 if obj.provider_type == "anthropic" else None})
        return obj

    def update(self, instance, validated_data):
        key = validated_data.pop("api_key", "")
        headers = validated_data.pop("custom_headers", None)
        if headers is not None:
            instance.custom_headers_encrypted = encrypt_secret(json.dumps(headers))
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if key:
            instance.set_api_key(key)
            managed = instance.keys.order_by("priority", "id").first() or AIProviderKey(provider=instance, name="Primary Key")
            managed.set_secret(key); managed.last_status = "untested"; managed.save()
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
