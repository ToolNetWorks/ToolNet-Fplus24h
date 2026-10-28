"""Rollback-only database verification; no network or Facebook credentials."""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.albums.models import Album, AlbumImage
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import (
    PublishingJob, PipelineMediaPolicy, PipelineAlbumSource,
)
from modules.publishing.adapters.facebook_groups import (
    FacebookGroupPublishingAdapter,
    GroupsApiUnavailable,
    build_group_preflight,
)
from modules.api.v1.publishing.facebook_group_preflight_views import (
    FacebookGroupPreflightAPIView,
)

suffix = uuid.uuid4().hex[:10]
factory = APIRequestFactory()
endpoint = FacebookGroupPreflightAPIView.as_view()
User = get_user_model()


def make_pipeline(label):
    user = User.objects.create_user(
        username=f"fbpre_{label}_{suffix}",
        password=f"Test#{suffix}Aa1!",
    )
    pipe = Pipeline.objects.create(
        name=f"FB Preflight {label} {suffix}", ctv=user,
        status=Pipeline.Status.ACTIVE,
    )
    return pipe, user


with transaction.atomic():
    pipe_a, user_a = make_pipeline("a")
    pipe_b, user_b = make_pipeline("b")

    account = FacebookAccount.objects.create(
        pipeline=pipe_a,
        label="Account A",
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    )
    group = FacebookGroup.objects.create(
        pipeline=pipe_a,
        name="Group A",
        group_url="https://www.facebook.com/groups/" + suffix + "/",
    )
    album = Album.objects.create(pipeline=pipe_a, name="Album A")
    image_id = uuid.uuid4()
    AlbumImage.objects.create(
        id=image_id, album=album,
        original_filename="dry-run.webp",
        storage_key=(
            f"pipeline-albums/{pipe_a.pk}/{album.pk}/{image_id}.webp"
        ),
        mime_type="image/webp", file_size=1024, width=100, height=100,
        sha256="a" * 64,
        upload_status=AlbumImage.UploadStatus.READY,
    )
    PipelineMediaPolicy.objects.create(
        pipeline=pipe_a, is_enabled=True, images_per_post=1,
    )
    PipelineAlbumSource.objects.create(
        pipeline=pipe_a, album=album, position=1, is_enabled=True,
    )
    proxy = ProxyEndpoint.objects.create(
        pipeline=pipe_a, account=account,
        protocol=ProxyEndpoint.Protocol.HTTP,
        host="8.8.8.8", port=8080,
        is_enabled=True,
        health_status=ProxyEndpoint.HealthStatus.HEALTHY,
        last_checked_at=timezone.now(),
    )
    job = PublishingJob.objects.create(
        pipeline=pipe_a, facebook_account=account, facebook_group=group,
        request_key=f"job-{suffix}", caption="Test dry-run",
        scheduled_at=timezone.now(), next_run_at=timezone.now(),
    )

    with patch("socket.socket", side_effect=AssertionError("Unexpected network")), \
         patch("modules.proxies.crypto.decrypt_proxy_credentials",
               side_effect=AssertionError("Credentials accessed")):
        preflight = build_group_preflight(
            pipeline_id=pipe_a.pk, job_id=job.pk,
        )
        assert preflight["can_auto_publish"] is False
        assert preflight["can_prepare_media"]
        assert preflight["proxy"]["assigned"]
        assert preflight["manual_package"]["caption"] == "Test dry-run"
    print("PREFLIGHT READ-ONLY + NO NETWORK/CREDENTIALS: PASS")

    job.refresh_from_db()
    assert job.state == PublishingJob.State.QUEUED
    assert job.attempt_count == 0
    print("JOB STATE UNCHANGED: PASS")

    try:
        FacebookGroupPublishingAdapter().dispatch()
    except GroupsApiUnavailable:
        print("OFFICIAL GROUP DISPATCH: BLOCKED")
    else:
        raise AssertionError("Dispatch unexpectedly permitted")

    response_req = factory.get(
        f"/api/v1/pipelines/{pipe_a.pk}/publishing-jobs/{job.pk}/preflight/"
    )
    force_authenticate(response_req, user=user_a)
    response = endpoint(
        response_req, pipeline_id=pipe_a.pk, job_id=job.pk,
    )
    assert response.status_code == 200, response.data
    assert "claim_token" not in str(response.data)
    assert "ciphertext" not in str(response.data)
    print("SCOPED PREFLIGHT API + NO SECRETS: PASS")

    foreign_req = factory.get(
        f"/api/v1/pipelines/{pipe_a.pk}/publishing-jobs/{job.pk}/preflight/"
    )
    force_authenticate(foreign_req, user=user_b)
    response = endpoint(
        foreign_req, pipeline_id=pipe_a.pk, job_id=job.pk,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE CTV: BLOCKED")

    anonymous_req = factory.get(
        f"/api/v1/pipelines/{pipe_a.pk}/publishing-jobs/{job.pk}/preflight/"
    )
    response = endpoint(
        anonymous_req, pipeline_id=pipe_a.pk, job_id=job.pk,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS ACCESS: BLOCKED")

    proxy.health_status = ProxyEndpoint.HealthStatus.FAILED
    proxy.save()
    bad_proxy = build_group_preflight(
        pipeline_id=pipe_a.pk, job_id=job.pk,
    )
    assert not bad_proxy["can_prepare_media"]
    print("FAILED PROXY PREFLIGHT: BLOCKED")

    group.is_enabled = False
    group.save()
    bad_group = build_group_preflight(
        pipeline_id=pipe_a.pk, job_id=job.pk,
    )
    assert not bad_group["can_prepare_media"]
    print("DISABLED GROUP PREFLIGHT: BLOCKED")

    try:
        build_group_preflight(pipeline_id=pipe_b.pk, job_id=job.pk)
    except Http404:
        print("FOREIGN JOB ID: BLOCKED")
    else:
        raise AssertionError("Foreign Job accessible")

    transaction.set_rollback(True)

print("DATABASE CHANGES: ROLLED BACK")
print("FACEBOOK GROUP ADAPTER PREFLIGHT: PASSED")
