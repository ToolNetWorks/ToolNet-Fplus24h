import time
import uuid
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response

from modules.api.v1.permissions import IsSuperAdmin
from modules.system_config.models import AIProvider, AIProviderKey, AIModel, AIRoute, AIFallback
from modules.system_config.serializers import AIProviderSerializer
from modules.system_config.ai_serializers import KeySerializer, ModelSerializer, RouteSerializer
from modules.system_config.services import provider_registry, model_discovery, ai_router
from modules.system_config.services.key_manager import select_key, headers, check_cooldown, record_rate_limit, has_key
from modules.system_config.services.adapters.protocol import ProviderError
from .views import ConfigAPIView, _log_audit


class AdminAIView(ConfigAPIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]

    def handle_exception(self, exc):
        if isinstance(exc, ProviderError):
            return Response(exc.public(), status=400)
        if isinstance(exc, ProtectedError):
            return Response({'error': 'Cấu hình đang được tuyến AI sử dụng. Hãy thay đổi tuyến trước.'}, status=409)
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response


def provider_data(provider):
    result = AIProviderSerializer(provider).data
    result.update({'cooldown_until': provider.cooldown_until, 'key_count': provider.keys.count(), 'model_count': provider.model_registry.count(), 'last_tested_at': provider.last_tested_at,
                   'custom_header_names': list(headers(provider).keys()), 'has_api_key': provider.keys.exclude(secret_encrypted='').exists() or provider.has_api_key})
    return result


def provider_or_404(provider_id):
    return get_object_or_404(AIProvider, pk=provider_id)


class RegistryView(AdminAIView):
    def get(self, request):
        config = ai_router.legacy_config()
        from modules.system_config.serializers import validate_endpoint
        try:
            validate_endpoint(config['base_url'])
            base = config['base_url']
        except Exception:
            base = ''
        return Response({'providers': provider_registry.catalog(), 'tasks': [{'id': 'caption_generation', 'name': 'AI Caption Generation'}, {'id': 'caption_review', 'name': 'AI Caption Review (không tự động duyệt)'}],
                         'legacy': {'configured': all(config.values()), 'base_url': base, 'model': config['model'], 'has_key': bool(config['api_key'])}})


class LegacyImportView(AdminAIView):
    def post(self, request):
        config = ai_router.legacy_config()
        if not all(config.values()):
            raise serializers.ValidationError('Chưa có cấu hình legacy đầy đủ.')
        from modules.system_config.serializers import validate_endpoint
        validate_endpoint(config['base_url'])
        provider, created = AIProvider.objects.get_or_create(pk=uuid.uuid5(uuid.NAMESPACE_URL, 'toolnet.system.env.import'), defaults={
            'name': 'ToolNetAPI (legacy)', 'provider_type': 'toolnet', 'base_url': config['base_url'], 'default_model': config['model'], 'is_active': False,
        })
        if created:
            key = AIProviderKey(provider=provider, name='Production import', is_active=True)
            key.set_secret(config['api_key']); key.save()
            AIModel.objects.create(provider=provider, model_id=config['model'], display_name=config['model'], source='legacy', is_enabled=False,
                supports_temperature=True, temperature=0.85, max_output_tokens=700)
            _log_audit(request, 'ai_providers', 'import_legacy', provider.id, provider.name, {'activated': False})
        return Response(provider_data(provider), status=201 if created else 200)


class ProvidersView(AdminAIView):
    def get(self, request):
        return Response([provider_data(p) for p in AIProvider.objects.all()])

    def post(self, request):
        serializer = AIProviderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        provider.api_key_encrypted = ''; provider.save(update_fields=['api_key_encrypted'])
        _log_audit(request, 'ai_providers', 'create_provider', provider.id, provider.name, {'activated': provider.is_active})
        return Response(provider_data(provider), status=201)


class ProviderView(AdminAIView):
    def get(self, request, provider_id):
        return Response(provider_data(provider_or_404(provider_id)))

    def put(self, request, provider_id):
        provider = provider_or_404(provider_id)
        serializer = AIProviderSerializer(provider, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        if request.data.get('api_key'):
            key = provider.keys.order_by('priority', 'id').first() or AIProviderKey(provider=provider, name='Primary Key')
            key.set_secret(request.data['api_key']); key.last_status = 'untested'; key.save()
            provider.api_key_encrypted = ''; provider.save(update_fields=['api_key_encrypted'])
        _log_audit(request, 'ai_providers', 'update_provider', provider.id, provider.name, {'key_updated': bool(request.data.get('api_key'))})
        return Response(provider_data(provider))

    patch = put

    def delete(self, request, provider_id):
        provider = provider_or_404(provider_id)
        ident, name = provider.pk, provider.name
        provider.delete()
        _log_audit(request, 'ai_providers', 'delete_provider', ident, name)
        return Response({'success': True})


class KeysView(AdminAIView):
    def get(self, request, provider_id):
        provider = provider_or_404(provider_id)
        return Response(KeySerializer(provider.keys.all(), many=True).data)

    def post(self, request, provider_id):
        provider = provider_or_404(provider_id)
        serializer = KeySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = serializer.save(provider=provider)
        _log_audit(request, 'ai_keys', 'add_key', key.pk, key.name, {'provider_id': str(provider.pk)})
        return Response(KeySerializer(key).data, status=201)


class KeyView(AdminAIView):
    def patch(self, request, provider_id, key_id):
        key = get_object_or_404(AIProviderKey, provider_id=provider_id, pk=key_id)
        serializer = KeySerializer(key, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Do not retain a usable shadow copy after rotation/revocation.
        AIProvider.objects.filter(pk=provider_id).update(api_key_encrypted='')
        _log_audit(request, 'ai_keys', 'update_key', key.pk, key.name, {'key_rotated': bool(request.data.get('secret'))})
        return Response(KeySerializer(key).data)

    def delete(self, request, provider_id, key_id):
        key = get_object_or_404(AIProviderKey, provider_id=provider_id, pk=key_id)
        ident, name = key.pk, key.name
        key.delete()
        AIProvider.objects.filter(pk=provider_id).update(api_key_encrypted='')
        _log_audit(request, 'ai_keys', 'delete_key', ident, name, {'provider_id': str(provider_id)})
        return Response({'success': True})


class ModelFilter(serializers.Serializer):
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=30, min_value=1, max_value=100)
    q = serializers.CharField(required=False, allow_blank=True, max_length=150, default='')


class ModelsView(AdminAIView):
    def get(self, request, provider_id):
        from django.db.models import Q
        from django.core.paginator import Paginator, EmptyPage
        provider = provider_or_404(provider_id)
        filters = ModelFilter(data=request.query_params); filters.is_valid(raise_exception=True)
        params = filters.validated_data
        qs = provider.model_registry.filter(Q(model_id__icontains=params['q']) | Q(display_name__icontains=params['q']))
        paginator = Paginator(qs, params['page_size'])
        try:
            page = paginator.page(params['page'])
        except EmptyPage:
            raise serializers.ValidationError('Trang không tồn tại.') from None
        return Response({'items': ModelSerializer(page.object_list, many=True).data, 'total': paginator.count, 'page': page.number, 'pages': paginator.num_pages})

    def post(self, request, provider_id):
        provider = provider_or_404(provider_id)
        serializer = ModelSerializer(data=request.data, context={'provider': provider})
        serializer.is_valid(raise_exception=True)
        model = serializer.save(provider=provider)
        _log_audit(request, 'ai_models', 'add_model', model.pk, model.model_id, {'provider_id': str(provider.pk)})
        return Response(ModelSerializer(model).data, status=201)


class ModelView(AdminAIView):
    def patch(self, request, provider_id, model_id):
        model = get_object_or_404(AIModel.objects.select_related('provider'), pk=model_id, provider_id=provider_id)
        serializer = ModelSerializer(model, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        old_model_id = model.model_id
        serializer.save()
        if old_model_id == model.provider.default_model and old_model_id != model.model_id:
            model.provider.default_model = model.model_id
            model.provider.save(update_fields=['default_model'])
        _log_audit(request, 'ai_models', 'update_model', model.pk, model.model_id)
        return Response(ModelSerializer(model).data)


class SyncModelsView(AdminAIView):
    def post(self, request, provider_id):
        provider = provider_or_404(provider_id)
        result = model_discovery.discover(provider)
        _log_audit(request, 'ai_models', 'sync_models', provider.pk, provider.name, {'discovered': result['discovered']})
        return Response(result)


class ModelDefaultView(AdminAIView):
    def post(self, request, provider_id, model_id):
        model = get_object_or_404(AIModel.objects.select_related('provider'), pk=model_id, provider_id=provider_id)
        if not model.is_enabled or not model.provider.is_active or not has_key(model.provider) or model.availability == 'unavailable':
            raise serializers.ValidationError('Hãy bật Provider và Model trước khi chọn mặc định.')
        AIProvider.objects.exclude(pk=provider_id).filter(is_default=True).update(is_default=False)
        model.provider.is_default = True; model.provider.default_model = model.model_id
        model.provider.save(update_fields=['is_default', 'default_model'])
        route = AIRoute.objects.select_for_update().filter(task='caption_generation').first()
        if route:
            route.primary_model = model; route.version += 1
            if route.key_policy == 'round_robin' and not model.provider.rotation_authorized:
                route.key_policy = 'priority'
            route.save(); route.fallbacks.filter(model=model).delete()
        _log_audit(request, 'ai_models', 'set_default_model', model.pk, model.model_id, {'provider_id': str(provider_id)})
        return Response({'success': True, 'provider_id': str(provider_id), 'model_id': str(model.pk)})


class TestPrompt(serializers.Serializer):
    prompt = serializers.CharField(max_length=2000, default='Reply OK.')


def test_model(model, prompt, *, key=None):
    start = time.monotonic()
    try:
        if key:
            check_cooldown(model.provider)
            secret = key.get_secret()
            if not secret:
                raise ProviderError('key_decryption_failed')
            result = provider_registry.adapter(model.provider.provider_type).complete(base_url=model.provider.base_url, api_key=secret,
                model=model.model_id, prompt=prompt, timeout=min(model.request_timeout, 45),
                settings={name: getattr(model, name) for name in ai_router.MODEL_OPTIONS}, custom_headers=headers(model.provider))
            result.update({'provider': model.provider.name, 'provider_id': str(model.provider.pk), 'key_id': str(key.pk)})
        else:
            result = ai_router.model_complete(model, prompt, mark_used=False, allow_disabled=True, retries=0, timeout=min(model.request_timeout, 45))
        return result
    except ProviderError as exc:
        record_rate_limit(model.provider, exc)
        return {**exc.public(), 'provider': model.provider.name, 'model': model.model_id, 'latency_ms': int((time.monotonic() - start) * 1000)}


class ModelTestView(AdminAIView):
    def post(self, request, provider_id, model_id):
        model = get_object_or_404(AIModel.objects.select_related('provider'), pk=model_id, provider_id=provider_id)
        prompt = TestPrompt(data=request.data); prompt.is_valid(raise_exception=True)
        result = test_model(model, prompt.validated_data['prompt'])
        model.last_tested_at = timezone.now(); model.last_http_status = result.get('http_status')
        # Transient transport failure is not evidence the model is inaccessible.
        if result['success']:
            model.availability = 'available'
        elif result.get('http_status') in (401, 403, 404):
            model.availability = 'unavailable'
        model.save(update_fields=['last_tested_at', 'last_http_status', 'availability'])
        _log_audit(request, 'ai_models', 'test_model', model.pk, model.model_id, {'success': result['success'], 'http_status': result.get('http_status')})
        return Response(result)


class ProviderTestView(AdminAIView):
    def post(self, request, provider_id, key_id=None):
        provider = provider_or_404(provider_id)
        key = get_object_or_404(AIProviderKey, provider=provider, pk=key_id) if key_id else None
        model = provider.model_registry.filter(model_id=provider.default_model).first() or provider.model_registry.order_by('-is_enabled', 'model_id').first()
        if model:
            result = test_model(model, 'Reply OK.', key=key)
            result.pop('text', None)
        else:
            start = time.monotonic()
            try:
                secret = key.get_secret() if key else select_key(provider, mark_used=False)[0]
                if not secret:
                    raise ProviderError('no_enabled_key')
                rows = provider_registry.adapter(provider.provider_type).discover(base_url=provider.base_url, api_key=secret, timeout=provider.timeout_seconds, custom_headers=headers(provider))
                result = {'success': True, 'http_status': 200, 'discovered': len(rows), 'latency_ms': int((time.monotonic() - start) * 1000)}
            except ProviderError as exc:
                result = {**exc.public(), 'latency_ms': int((time.monotonic() - start) * 1000)}
        provider.last_tested_at = timezone.now(); provider.last_status = 'ok' if result['success'] else 'error'; provider.last_latency_ms = result.get('latency_ms')
        provider.save(update_fields=['last_tested_at', 'last_status', 'last_latency_ms'])
        if key:
            key.last_tested_at = timezone.now(); key.last_status = provider.last_status; key.last_http_status = result.get('http_status')
            key.save(update_fields=['last_tested_at', 'last_status', 'last_http_status'])
        _log_audit(request, 'ai_providers', 'test_key' if key else 'test_provider', key.pk if key else provider.pk, provider.name, {'success': result['success'], 'http_status': result.get('http_status')})
        return Response(result)


class RoutesView(AdminAIView):
    def get(self, request):
        return Response(RouteSerializer(AIRoute.objects.prefetch_related('fallbacks').all(), many=True).data)


class RouteView(AdminAIView):
    def put(self, request, task):
        serializer = RouteSerializer(data={**request.data, 'task': task})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        route = AIRoute.objects.select_for_update().filter(task=task).first()
        version = data.pop('expected_version')
        if version != (route.version if route else 0):
            return Response({'error': 'Tuyến đã thay đổi. Hãy tải lại trước khi lưu.'}, status=409)
        steps = data.pop('fallbacks', [])
        if route:
            for field, value in data.items():
                setattr(route, field, value)
            route.version += 1; route.save()
            route.fallbacks.all().delete()
        else:
            route = AIRoute.objects.create(**data)
        for step in steps:
            AIFallback.objects.create(route=route, **step)
        _log_audit(request, 'ai_routing', 'save_route', task, task, {'version': route.version, 'fallback_count': len(steps), 'enabled': route.is_enabled})
        return Response(RouteSerializer(route).data)


class RouteTestView(AdminAIView):
    def post(self, request, task):
        prompt = TestPrompt(data=request.data); prompt.is_valid(raise_exception=True)
        result = ai_router.route_text(prompt.validated_data['prompt'], task=task, budget_seconds=45)
        _log_audit(request, 'ai_routing', 'test_route', task, task, {'provider_id': result.get('provider_id'), 'model': result.get('model')})
        return Response(result)


class AdHocProviderTestView(AdminAIView):
    def post(self, request):
        data = AIProviderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        start = time.monotonic()
        rows = provider_registry.adapter(values['provider_type']).discover(base_url=values['base_url'], api_key=values['api_key'], timeout=min(values.get('timeout_seconds', 30), 30), custom_headers=values.get('custom_headers', {}))
        _log_audit(request, 'ai_providers', 'test_unsaved_provider', target_name=values['provider_type'], details={'success': True})
        return Response({'success': True, 'http_status': 200, 'discovered': len(rows), 'latency_ms': int((time.monotonic() - start) * 1000)})
