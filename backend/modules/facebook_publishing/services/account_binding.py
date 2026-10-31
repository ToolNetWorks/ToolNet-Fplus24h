"""Account/Proxy binding for the Facebook Publishing Worker.

Validates that an Account has a pinned Proxy and that the Proxy is healthy,
returning a validated bundle for the Worker to use.
"""
import logging
import uuid
from dataclasses import dataclass
from django.utils import timezone
from datetime import timedelta

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.proxies.models import ProxyEndpoint
from modules.publishing.scheduler_models import AccountProxyPin, AccountGroupEligibility
from modules.facebook_publishing.models import WorkerRunningOp
from modules.facebook_publishing.services.config import WorkerSettings

logger = logging.getLogger(__name__)

PROXY_HEALTH_TTL = timedelta(hours=24)


class AccountProxyBindingError(Exception):
    pass


@dataclass(frozen=True)
class AccountBundle:
    account_id: uuid.UUID
    account: FacebookAccount
    proxy: ProxyEndpoint
    pin: AccountProxyPin
    proxy_server_url: str
    encrypted_cookies_count: int
    has_cookies: bool
    is_anonymous_enabled: bool


def _check_single_op(account_id, worker_id):
    """Guard: a single Account may have at most one running posting operation."""
    from django.db import transaction
    with transaction.atomic():
        try:
            existing = WorkerRunningOp.objects.select_for_update(
                nowait=True, of=('self',)
            ).filter(
                account_id=account_id,
            ).first()
        except Exception:
            # If we can't acquire a lock, assume another worker is active
            raise AccountProxyBindingError(
                f'Account {account_id} may have a running operation; lock unavailable.'
            )
        if existing:
            raise AccountProxyBindingError(
                f'Account {account_id} already has a running operation '
                f'(worker={existing.worker_id}).'
            )


def _validate_proxy(proxy, now):
    if not proxy.is_enabled:
        raise AccountProxyBindingError(f'Proxy {proxy.pk} is disabled.')
    if proxy.health_status != ProxyEndpoint.HealthStatus.HEALTHY:
        raise AccountProxyBindingError(
            f'Proxy {proxy.pk} health status is {proxy.health_status}.'
        )
    if not proxy.exit_ip:
        raise AccountProxyBindingError(f'Proxy {proxy.pk} has no exit IP.')
    if not proxy.last_checked_at:
        raise AccountProxyBindingError(f'Proxy {proxy.pk} has never been checked.')
    if (now - proxy.last_checked_at) > PROXY_HEALTH_TTL:
        raise AccountProxyBindingError(
            f'Proxy {proxy.pk} health check has expired.'
        )


def _proxy_server_url(proxy):
    return f'{proxy.protocol}://{proxy.host}:{proxy.port}'


def _count_encrypted_cookies(account_id):
    """Count cookies available for the Account from the existing system.

    Never returns cookie contents — only the count and presence flag.
    """
    from modules.facebook_accounts.credentials import FacebookCookieSecret
    try:
        secret = FacebookCookieSecret.objects.filter(account_id=account_id).first()
        if secret is None:
            return False, 0
        return True, getattr(secret, 'cookie_count', 0)
    except Exception:
        return False, 0


def resolve_account_bundle(*, pipeline_id, account_id, group_id, worker_id,
                           settings: WorkerSettings):
    """Resolve a full Account + Proxy bundle for publishing.

    Validates:
    - Account belongs to Pipeline and is CONNECTED
    - Account has a pinned Proxy (fail-closed: never silently change IP)
    - Proxy is healthy and within health TTL
    - Account has no running operation (concurrency guard)
    """
    import uuid

    if not isinstance(account_id, uuid.UUID):
        account_id = uuid.UUID(str(account_id))
    if not isinstance(group_id, uuid.UUID):
        group_id = uuid.UUID(str(group_id))

    now = timezone.now()

    account = FacebookAccount.objects.select_related(
        'assigned_proxy', 'cookie_secret',
    ).filter(
        pk=account_id, pipeline_id=pipeline_id,
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    ).first()
    if account is None:
        raise AccountProxyBindingError(
            f'Account {account_id} not found, not CONNECTED, or not in Pipeline {pipeline_id}.'
        )

    group = FacebookGroup.objects.filter(
        pk=group_id, pipeline_id=pipeline_id, is_enabled=True,
    ).first()
    if group is None:
        raise AccountProxyBindingError(
            f'Group {group_id} not found, disabled, or not in Pipeline {pipeline_id}.'
        )

    pin = AccountProxyPin.objects.select_related('proxy__auth_secret').filter(
        pipeline_id=pipeline_id, account_id=account_id,
    ).first()
    if pin is None:
        raise AccountProxyBindingError(
            f'Account {account_id} has no Proxy Pin. Worker cannot proceed.'
        )
    proxy = pin.proxy
    if str(proxy.account_id) != str(account_id):
        raise AccountProxyBindingError(
            f'Proxy {proxy.pk} is not bound to Account {account_id}.'
        )
    _validate_proxy(proxy, now)

    proxy_server = _proxy_server_url(proxy)
    has_cookies, cookie_count = _count_encrypted_cookies(account_id)

    # Guard: one running operation per Account
    _check_single_op(account_id, worker_id)

    # Check anonymous posting eligibility
    eligibility = AccountGroupEligibility.objects.filter(
        pipeline_id=pipeline_id, account_id=account_id, group_id=group_id,
        state=AccountGroupEligibility.State.VERIFIED,
        can_post_anonymous=True,
        verified_at__lte=now, expires_at__gt=now,
    ).first()
    is_anonymous_enabled = eligibility is not None and eligibility.can_post_anonymous

    return AccountBundle(
        account_id=account_id,
        account=account,
        proxy=proxy,
        pin=pin,
        proxy_server_url=proxy_server,
        encrypted_cookies_count=cookie_count,
        has_cookies=has_cookies,
        is_anonymous_enabled=is_anonymous_enabled,
    )


def acquire_running_op(*, account_id, worker_id, publish_job, started_at=None):
    """Create a running-op advisory lock for this Account.

    Uses select_for_update on any existing lock to prevent race conditions.
    Wraps in a transaction since select_for_update requires one.
    """
    from django.db import transaction
    now = timezone.now()
    started_at = started_at or now
    with transaction.atomic():
        # Double-check: no existing op for this account
        existing = WorkerRunningOp.objects.select_for_update(nowait=True).filter(
            account_id=account_id,
        ).first()
        if existing:
            raise AccountProxyBindingError(
                f'Account {account_id} already has a running operation '
                f'(worker={existing.worker_id}).'
            )
        op = WorkerRunningOp.objects.create(
            account_id=account_id,
            publish_job=publish_job,
            worker_id=worker_id,
            started_at=started_at,
            heartbeat_at=now,
        )
    return op


def release_running_op(op):
    """Release the advisory lock."""
    op.delete()


def heartbeat_running_op(op):
    """Update the advisory lock heartbeat."""
    op.heartbeat_at = timezone.now()
    op.save(update_fields=['heartbeat_at'])
