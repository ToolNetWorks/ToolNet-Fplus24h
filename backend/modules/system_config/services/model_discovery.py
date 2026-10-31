from django.db import transaction
from django.utils import timezone
from ..models import AIModel
from ..ai_serializers import ModelSerializer
from .key_manager import select_key, headers
from .provider_registry import adapter
from .adapters.protocol import ProviderError


def discover(provider):
    key, _ = select_key(provider, mark_used=False)
    rows = adapter(provider.provider_type).discover(base_url=provider.base_url, api_key=key, timeout=provider.timeout_seconds, custom_headers=headers(provider))
    # Complete discovery and validate before changing inventory. Failure never removes models.
    validated = {}
    for row in rows:
        if any(secret and (secret in row['model_id'] or secret in row['display_name']) for secret in [key, *headers(provider).values()]):
            raise ProviderError('invalid_models_response')
        validator = ModelSerializer(data={'model_id': row['model_id'], 'display_name': row['display_name']})
        validator.is_valid(raise_exception=True)
        validated[row['model_id']] = row
    now = timezone.now()
    with transaction.atomic():
        for model_id, row in validated.items():
            model, created = AIModel.objects.get_or_create(provider=provider, model_id=model_id, defaults={'display_name': row['display_name'], 'source': 'discovery'})
            model.last_seen_at = now
            if created:
                model.supports_temperature = row.get('supports_temperature')
                model.supports_top_p = row.get('supports_top_p')
            limit = row.get('output_token_limit')
            if isinstance(limit, int) and 0 < limit <= 10000000:
                model.output_token_limit = limit
            model.save()
        # Absence in a listing is not proof inference access was revoked. Keep status/settings.
    return {'success': True, 'discovered': len(validated), 'synced_at': now.isoformat()}
