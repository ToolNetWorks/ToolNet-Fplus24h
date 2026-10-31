import json
from datetime import timedelta
from ..models import AIProvider
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from ..crypto import decrypt_secret
from .adapters.protocol import ProviderError


def headers(provider):
    try:
        return json.loads(decrypt_secret(provider.custom_headers_encrypted) or '{}')
    except ValueError:
        raise ProviderError('invalid_headers_config') from None


def has_key(provider):
    # Once managed keys exist, do not resurrect a legacy key after disabling/deleting one.
    if provider.keys.exists():
        return provider.keys.filter(is_active=True).exclude(secret_encrypted='').exists()
    return provider.has_api_key


def check_cooldown(provider):
    if AIProvider.objects.filter(pk=provider.pk, cooldown_until__gt=timezone.now()).exists():
        raise ProviderError('provider_rate_limit_cooldown', 429)


def record_rate_limit(provider, error):
    if error.http_status == 429:
        AIProvider.objects.filter(pk=provider.pk).update(cooldown_until=timezone.now() + timedelta(seconds=error.retry_after or 60))


def select_key(provider, policy='priority', *, mark_used=True, key_id=None):
    check_cooldown(provider)
    with transaction.atomic():
        queryset = provider.keys.select_for_update().filter(is_active=True).exclude(secret_encrypted='')
        if key_id:
            queryset = queryset.filter(pk=key_id)
        if policy == 'round_robin':
            if not provider.rotation_authorized:
                raise ProviderError('rotation_not_authorized')
            queryset = queryset.order_by(F('last_used_at').asc(nulls_first=True), 'priority', 'id')
        else:
            queryset = queryset.order_by('priority', 'created_at', 'id')
        row = queryset.first()
        if row:
            secret = row.get_secret()
            if not secret:
                raise ProviderError('key_decryption_failed')
            if mark_used:
                row.last_used_at = timezone.now()
                row.save(update_fields=['last_used_at'])
            return secret, str(row.pk)
        if key_id or provider.keys.exists():
            raise ProviderError('no_enabled_key')
        secret = provider.get_api_key()
        if not secret:
            raise ProviderError('no_enabled_key')
        return secret, 'legacy'
