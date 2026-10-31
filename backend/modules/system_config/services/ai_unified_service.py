"""Stable Caption Engine facade; routing and key policy live in dedicated services."""
from .provider_registry import adapter as get_adapter
from .ai_router import route_text
from .adapters.protocol import ProviderError
from ..models import AIProvider


def ensure_default_provider_initialized():
    # Reading settings never creates or activates providers.
    return AIProvider.objects.filter(is_default=True, is_active=True).first()


def generate_ai_text(prompt, system_instruction=None, requested_model=None, pipeline_id=None):
    result = route_text(prompt, system_instruction=system_instruction, requested_model=requested_model, pipeline_id=pipeline_id)
    return result['text'], result['model']


def test_provider_connection(provider_type, base_url, api_key, model, timeout=25):
    try:
        return get_adapter(provider_type).test_connection(base_url=base_url, api_key=api_key, model=model, timeout=timeout)
    except (ProviderError, KeyError):
        return {'success': False, 'error': 'invalid_provider_configuration'}
