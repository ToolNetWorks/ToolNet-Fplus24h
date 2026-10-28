"""Facebook Groups adapter contract and read-only publishing preflight.

Meta discontinued the official Groups API, including publish_to_groups,
on 2024-04-22. This module DOES NOT publish to Facebook and does not
access cookies, private endpoints, passwords, browser automation or R2.

This module is safe to use for a human-reviewed content workflow.
No job state transitions or DB writes occur here.
"""

from datetime import timedelta

from django.http import Http404
from django.utils import timezone

from modules.albums.models import AlbumImage
from modules.facebook_accounts.models import FacebookAccount
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import (
    MediaAllocation, PipelineAlbumSource, PipelineMediaPolicy, PublishingJob,
)

MIN_ACCOUNT_INTERVAL = timedelta(minutes=15)
MIN_GROUP_INTERVAL = timedelta(hours=1)
MAX_ACCOUNT_POSTS_24H = 12
MAX_PROXY_HEALTH_AGE = timedelta(hours=24)
PREFLIGHT_STATES = {
    PublishingJob.State.QUEUED,
    PublishingJob.State.CLAIMED,
    PublishingJob.State.READY,
}


class GroupsApiUnavailable(RuntimeError):
    """No supported official publishing API is available for Facebook Groups."""


class FacebookGroupPublishingAdapter:
    """Deliberately non-networked, fail-closed adapter.

    A future, independently approved transport may implement a different
    class, but must not silently replace this adapter or bypass user consent.
    """

    @staticmethod
    def capabilities():
        return {
            "platform": "facebook",
            "target": "groups",
            "official_api_publishing": False,
            "auto_dispatch_enabled": False,
            "manual_review_required": True,
            "reason_code": "GROUPS_API_REMOVED_2024_04_22",
        }

    def dispatch(self, *args, **kwargs):
        # Important: do not call job_engine.begin_dispatch() here.
        raise GroupsApiUnavailable(
            "Meta đã ngừng Groups API. Adapter không hỗ trợ tự động đăng Group."
        )


def _check(checks, code, ok, message):
    checks.append({
        "code": code,
        "ok": bool(ok),
        "message": message,
    })


def build_group_preflight(*, pipeline_id, job_id):
    """Read-only preflight scoped to the provided pipeline.

    Checks are indicative. Connection status does NOT prove a live Facebook
    session; proxy health does NOT prove Facebook access or Group membership.
    The preflight never grants automatic publishing capability.
    """
    pipeline = Pipeline.objects.filter(pk=pipeline_id).first()
    if pipeline is None:
        raise Http404("Pipeline không tồn tại.")

    job = (
        PublishingJob.objects.filter(
            pk=job_id, pipeline_id=pipeline.pk
        )
        .select_related(
            "facebook_account", "facebook_group", "media_allocation"
        )
        .first()
    )
    if job is None:
        raise Http404("Job không thuộc Pipeline.")

    now = timezone.now()
    checks = []
    account = job.facebook_account
    group = job.facebook_group
    adapter = FacebookGroupPublishingAdapter()

    _check(checks, "pipeline_active",
           pipeline.status == Pipeline.Status.ACTIVE,
           "Pipeline phải đang hoạt động.")
    _check(checks, "preflight_job_state",
           job.state in PREFLIGHT_STATES,
           "Chỉ kiểm tra Job queued, claimed hoặc ready.")
    _check(checks, "account_connected",
           account.connection_status == FacebookAccount.ConnectionStatus.CONNECTED,
           "Account cần có trạng thái kết nối; trạng thái này không xác nhận phiên Facebook còn hiệu lực.")
    _check(checks, "group_enabled", group.is_enabled,
           "Group đích phải được bật.")
    # An internal 'verified' marker is not proof of account-specific posting rights.
    group_membership_verified = False

    proxy = (
        ProxyEndpoint.objects.filter(
            pipeline_id=pipeline.pk,
            account_id=account.pk,
        ).first()
    )
    proxy_info = {
        "assigned": proxy is not None,
        "id": str(proxy.pk) if proxy else None,
        "protocol": proxy.protocol if proxy else None,
        "enabled": proxy.is_enabled if proxy else False,
        "health_status": proxy.health_status if proxy else None,
        "exit_ip": proxy.exit_ip if proxy else None,
        "last_checked_at": (
            proxy.last_checked_at.isoformat()
            if proxy and proxy.last_checked_at else None
        ),
        "has_auth": (
            # Avoid reading or decrypting the secret itself.
            hasattr(proxy, "auth_secret")
            if proxy else False
        ),
    }
    healthy_proxy = bool(
        proxy
        and proxy.is_enabled
        and proxy.health_status == ProxyEndpoint.HealthStatus.HEALTHY
        and proxy.last_checked_at
        and now - MAX_PROXY_HEALTH_AGE <= proxy.last_checked_at <= now
    )
    _check(checks, "account_proxy_healthy", healthy_proxy,
           "Mỗi Account cần một Proxy đã bật và kiểm tra kết nối trong 24 giờ.")

    media_policy = PipelineMediaPolicy.objects.filter(
        pipeline_id=pipeline.pk
    ).first()
    active_sources = list(
        PipelineAlbumSource.objects.filter(
            pipeline_id=pipeline.pk,
            is_enabled=True, album__is_enabled=True,
        ).values_list("album_id", flat=True)
    )
    image_count = (
        AlbumImage.objects.filter(
            album_id__in=active_sources,
            album__pipeline_id=pipeline.pk,
            upload_status=AlbumImage.UploadStatus.READY,
        ).count()
        if active_sources else 0
    )
    policy_ok = bool(media_policy and media_policy.is_enabled)
    _check(checks, "media_policy_enabled", policy_ok,
           "Cấu hình Album nguồn phải đang bật.")
    enough_images = bool(
        media_policy and image_count >= media_policy.images_per_post
    )
    _check(checks, "media_sources_sufficient",
           bool(active_sources) and enough_images,
           "Cần đủ ảnh READY từ Album nguồn hiện đang bật.")

    allocation = job.media_allocation
    reserved = bool(
        allocation
        and allocation.pipeline_id == pipeline.pk
        and allocation.state == MediaAllocation.State.RESERVED
        and allocation.lease_expires_at > now
    )
    image_refs = []
    if allocation:
        for row in allocation.items.order_by("position").values(
            "image_uuid", "album_uuid", "position"
        ):
            image_refs.append({
                "image_id": str(row["image_uuid"]),
                "album_id": str(row["album_uuid"]),
                "position": row["position"],
            })
    if job.state == PublishingJob.State.READY:
        _check(checks, "media_reservation_valid", reserved,
               "Job READY phải có lượt giữ chỗ ảnh chưa hết hạn.")

    # Internal editorial pacing only. NOT a published Meta rate-limit.
    earliest = now - timedelta(hours=24)
    published = PublishingJob.objects.filter(
        pipeline_id=pipeline.pk,
        state=PublishingJob.State.PUBLISHED,
        finalized_at__isnull=False,
    )
    account_posted = published.filter(
        facebook_account_id=account.pk
    ).order_by("-finalized_at")
    group_posted = published.filter(
        facebook_group_id=group.pk
    ).order_by("-finalized_at")
    latest_account = account_posted.values_list(
        "finalized_at", flat=True
    ).first()
    latest_group = group_posted.values_list(
        "finalized_at", flat=True
    ).first()
    account_count_24h = account_posted.filter(
        finalized_at__gte=earliest
    ).count()
    rate_ok = (
        account_count_24h < MAX_ACCOUNT_POSTS_24H
        and (latest_account is None
             or latest_account <= now - MIN_ACCOUNT_INTERVAL)
        and (latest_group is None
             or latest_group <= now - MIN_GROUP_INTERVAL)
    )
    _check(checks, "internal_editorial_pacing", rate_ok,
           "Giới hạn nội bộ: 15 phút/Account, 60 phút/Group, 12 bài/Account/24 giờ.")

    return {
        "job_id": str(job.pk),
        "pipeline_id": str(pipeline.pk),
        "job_state": job.state,
        "capabilities": adapter.capabilities(),
        "can_prepare_media": all(row["ok"] for row in checks),
        "can_auto_publish": False,
        "group_membership_verified": group_membership_verified,
        "checks": checks,
        "account": {
            "id": str(account.pk),
            "label": account.label,
            "connection_status": account.connection_status,
        },
        "group": {
            "id": str(group.pk),
            "name": group.name,
            "url": group.group_url,
            "verification_status": group.verification_status,
        },
        "proxy": proxy_info,
        "media": {
            "policy_enabled": policy_ok,
            "ready_images_in_active_sources": image_count,
            "images_per_post": media_policy.images_per_post if media_policy else None,
            "allocation_id": str(allocation.pk) if allocation else None,
            "reservation_valid": reserved,
            "image_refs": image_refs,
        },
        "editorial_pacing": {
            "account_posts_24h": account_count_24h,
            "max_account_posts_24h": MAX_ACCOUNT_POSTS_24H,
            "min_account_interval_minutes": 15,
            "min_group_interval_minutes": 60,
        },
        "manual_package": {
            "group_url": group.group_url,
            "caption": job.caption,
            "image_refs": image_refs,
            "requires_human_posting": True,
            "requires_independent_result_verification": True,
        },
    }
