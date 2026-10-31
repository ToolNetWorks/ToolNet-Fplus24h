import re
import math
from rest_framework import serializers
from .models import AIModel, AIProviderKey, AIRoute

POLICIES = ('priority', 'round_robin')
HEADER_NAMES = {'http-referer', 'x-title', 'openai-organization', 'openai-project', 'anthropic-beta'}


def validate_headers(value):
    if len(value) > 16:
        raise serializers.ValidationError('Tối đa 16 headers.')
    for name, text in value.items():
        if name.lower() not in HEADER_NAMES and not re.fullmatch(r'X-Client-[A-Za-z0-9-]{1,50}', name, re.I):
            raise serializers.ValidationError('Chỉ chấp nhận HTTP-Referer, X-Title, OpenAI-Organization, OpenAI-Project, Anthropic-Beta hoặc X-Client-*.')
        if not isinstance(text, str) or len(text) > 2048 or any(ord(c) < 32 or ord(c) > 126 for c in text):
            raise serializers.ValidationError('Giá trị header phải là ASCII hợp lệ, không chứa ký tự điều khiển.')
    return value


class KeySerializer(serializers.ModelSerializer):
    secret = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=8192, trim_whitespace=True)
    priority = serializers.IntegerField(min_value=1, max_value=10000, required=False)

    class Meta:
        model = AIProviderKey
        fields = ('id', 'name', 'secret', 'is_active', 'priority', 'last_used_at', 'last_tested_at', 'last_status', 'last_http_status')
        read_only_fields = ('id', 'last_used_at', 'last_tested_at', 'last_status', 'last_http_status')

    def validate(self, data):
        secret = data.get('secret', '')
        if any(ord(c) < 32 or ord(c) > 126 for c in secret):
            raise serializers.ValidationError({'secret': 'Key không được chứa ký tự điều khiển hoặc ngoài ASCII.'})
        if self.instance is None and not data.get('secret'):
            raise serializers.ValidationError({'secret': 'Vui lòng nhập Key.'})
        return data

    def create(self, data):
        secret = data.pop('secret')
        obj = AIProviderKey(**data)
        obj.set_secret(secret)
        obj.save()
        return obj

    def update(self, instance, data):
        secret = data.pop('secret', '')
        for key, value in data.items():
            setattr(instance, key, value)
        if secret:
            instance.set_secret(secret)
            instance.last_status = 'untested'
            instance.last_tested_at = None
            instance.last_http_status = None
        instance.save()
        return instance


class ModelSerializer(serializers.ModelSerializer):
    model_id = serializers.RegexField(r'^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,119}$')
    request_timeout = serializers.IntegerField(min_value=1, max_value=120, required=False)
    retry_count = serializers.IntegerField(min_value=0, max_value=2, required=False)
    max_output_tokens = serializers.IntegerField(min_value=1, max_value=10000000, allow_null=True, required=False)
    temperature = serializers.FloatField(min_value=0, max_value=2, allow_null=True, required=False)
    top_p = serializers.FloatField(min_value=0, max_value=1, allow_null=True, required=False)

    class Meta:
        model = AIModel
        fields = ('id', 'provider', 'model_id', 'display_name', 'is_enabled', 'availability', 'source', 'supports_temperature', 'supports_top_p', 'temperature', 'top_p', 'max_output_tokens', 'output_token_limit', 'token_parameter', 'request_timeout', 'retry_count', 'last_seen_at', 'last_tested_at', 'last_http_status')
        read_only_fields = ('id', 'provider', 'availability', 'source', 'output_token_limit', 'last_seen_at', 'last_tested_at', 'last_http_status')
        validators = []

    def validate(self, data):
        def value(name):
            return data.get(name, getattr(self.instance, name, None))
        if '..' in data.get('model_id', '').split('/'):
            raise serializers.ValidationError('Model ID không hợp lệ.')
        for parameter in ('temperature', 'top_p'):
            if value(parameter) is not None and not math.isfinite(value(parameter)):
                raise serializers.ValidationError({parameter: 'Giá trị phải là số hữu hạn.'})
            if value(parameter) is not None and value('supports_' + parameter) is not True:
                raise serializers.ValidationError({parameter: 'Xác nhận Model hỗ trợ tham số trước khi cấu hình.'})
        limit = getattr(self.instance, 'output_token_limit', None)
        if limit and value('max_output_tokens') and value('max_output_tokens') > limit:
            raise serializers.ValidationError({'max_output_tokens': 'Vượt giới hạn do Models API công bố.'})
        provider = self.context.get('provider') or (self.instance.provider if self.instance else None)
        if provider:
            if provider.provider_type == 'anthropic' and value('is_enabled') and value('max_output_tokens') is None:
                raise serializers.ValidationError({'max_output_tokens': 'Anthropic yêu cầu Max Output Tokens trước khi bật Model.'})
            model_id = value('model_id')
            duplicate = AIModel.objects.filter(provider=provider, model_id=model_id)
            if self.instance:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError({'model_id': 'Model đã tồn tại ở Provider này.'})
        return data

    def update(self, instance, validated_data):
        changed = any(name in validated_data and validated_data[name] != getattr(instance, name) for name in (
            'model_id', 'supports_temperature', 'supports_top_p', 'temperature', 'top_p', 'max_output_tokens', 'token_parameter',
        ))
        if changed:
            instance.availability = 'untested'
            instance.last_tested_at = None
            instance.last_http_status = None
        return super().update(instance, validated_data)


class FallbackSerializer(serializers.Serializer):
    provider = serializers.UUIDField(source='model.provider_id', read_only=True)
    model_name = serializers.CharField(source='model.model_id', read_only=True)
    model = serializers.PrimaryKeyRelatedField(queryset=AIModel.objects.select_related('provider'))
    priority = serializers.IntegerField(min_value=1, max_value=100)
    timeout = serializers.IntegerField(min_value=1, max_value=120, default=60)
    retries = serializers.IntegerField(min_value=0, max_value=2, default=0)
    key_policy = serializers.ChoiceField(choices=POLICIES, default='priority')


class RouteSerializer(serializers.ModelSerializer):
    task = serializers.SlugField(max_length=80)
    primary_provider = serializers.UUIDField(source='primary_model.provider_id', read_only=True)
    primary_model_name = serializers.CharField(source='primary_model.model_id', read_only=True)
    primary_model = serializers.PrimaryKeyRelatedField(queryset=AIModel.objects.select_related('provider'))
    fallbacks = FallbackSerializer(many=True, required=False, max_length=8)
    expected_version = serializers.IntegerField(write_only=True, min_value=0, required=True)

    class Meta:
        model = AIRoute
        fields = ('task', 'primary_model', 'primary_provider', 'primary_model_name', 'key_policy', 'is_enabled', 'version', 'expected_version', 'fallbacks', 'updated_at')
        read_only_fields = ('version', 'updated_at')
        extra_kwargs = {'task': {'validators': []}}
        validators = []

    def validate(self, data):
        from .services.key_manager import has_key
        primary = data['primary_model']
        steps = [(primary, data.get('key_policy', 'priority'))] + [(step['model'], step['key_policy']) for step in data.get('fallbacks', [])]
        models, priorities = set(), set()
        for model, policy in steps:
            if model.pk in models:
                raise serializers.ValidationError('Không được lặp Model trong tuyến.')
            models.add(model.pk)
            if data.get('is_enabled', True) and (not model.is_enabled or not model.provider.is_active or not has_key(model.provider) or model.availability == 'unavailable'):
                raise serializers.ValidationError('Tuyến đang bật cần Provider, Model và ít nhất một Key đang bật.')
            if policy == 'round_robin' and not model.provider.rotation_authorized:
                raise serializers.ValidationError('Provider chưa được xác nhận cho phép rotation.')
        for step in data.get('fallbacks', []):
            if step['priority'] in priorities:
                raise serializers.ValidationError('Priority fallback phải khác nhau.')
            priorities.add(step['priority'])
        return data
