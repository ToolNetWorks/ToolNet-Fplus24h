"""Rollback-only integration of Pilot preflight -> human handoff -> moderation report.

No R2 access, no Facebook I/O, no external session or cookie data.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.publishing.pilot_views import PublishingPilotReadinessAPIView
from modules.albums.models import Album, AlbumImage
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import (
    PublishingJob, PipelineMediaPolicy, PipelineAlbumSource, MediaAllocation,
)
from modules.publishing.scheduler_models import AccountGroupEligibility, AccountProxyPin
from modules.publishing.services.manual_handoff import prepare_handoff, mutate_handoff
from modules.publishing.services.pilot_readiness import (
    pilot_readiness_snapshot, PilotReadinessError,
)
from modules.publishing.services.reconciliation import held_subject_ids

User = get_user_model()
factory = APIRequestFactory()
suffix = uuid.uuid4().hex[:10]
now = timezone.now()


def request(pipe, actor=None, query=''):
    req = factory.get(f'/api/v1/pipelines/{pipe.pk}/pilot-readiness/{query}')
    if actor is not None:
        force_authenticate(req, user=actor)
    return PublishingPilotReadinessAPIView.as_view()(req, pipeline_id=pipe.pk)


with transaction.atomic():
    owner = User.objects.create_user(username='pilot_' + suffix, password='FixtureOnlyNeverReal!123')
    outsider = User.objects.create_user(username='pilot_other_' + suffix, password='FixtureOnlyNeverReal!123')
    pipe = Pipeline.objects.create(name='Pilot ' + suffix, ctv=owner, status=Pipeline.Status.ACTIVE)
    foreign = Pipeline.objects.create(name='Foreign pilot ' + suffix, ctv=outsider, status=Pipeline.Status.ACTIVE)

    with patch('socket.socket', side_effect=AssertionError('No external sockets permitted')):
        empty = pilot_readiness_snapshot(pipeline_id=pipe.pk)
        assert empty['status'] == 'not_configured' and empty['read_only'] is True
        assert empty['automatic_facebook_posting'] is False
        assert request(pipe, owner).status_code == 200
        assert request(pipe, outsider).status_code == 404
        assert request(foreign, owner).status_code == 404
        assert request(pipe).status_code in (401, 403)
        assert request(pipe, owner, '?limit=0').status_code == 400
        assert request(pipe, owner, '?limit=101').status_code == 400
        assert request(pipe, owner)['Cache-Control'] == 'private, no-store'
        print('TENANT, NO-CACHE, INPUT VALIDATION AND EMPTY PIPELINE: PASS')

        account = FacebookAccount.objects.create(pipeline=pipe, label='Pilot Account', connection_status='connected')
        group = FacebookGroup.objects.create(pipeline=pipe, name='Pilot Group',
            group_url=f'https://www.facebook.com/groups/pilot{suffix}/')
        album = Album.objects.create(pipeline=pipe, name='Pilot Album')
        image_id = uuid.uuid4()
        AlbumImage.objects.create(
            pk=image_id, album=album, original_filename='pilot.webp',
            storage_key=f'pipeline-albums/{pipe.pk}/{album.pk}/{image_id}.webp',
            mime_type='image/webp', file_size=1024, width=20, height=20,
            sha256='a' * 64, position=1, upload_status='ready',
        )
        PipelineMediaPolicy.objects.create(pipeline=pipe, is_enabled=True, images_per_post=1)
        PipelineAlbumSource.objects.create(pipeline=pipe, album=album, position=1)
        proxy = ProxyEndpoint.objects.create(
            pipeline=pipe, account=account, host='8.8.8.8', port=21001,
            is_enabled=True, health_status=ProxyEndpoint.HealthStatus.HEALTHY,
            exit_ip='8.8.8.8', last_checked_at=now,
        )
        AccountProxyPin.objects.create(pipeline=pipe, account=account, proxy=proxy,
                                      pinned_exit_ip='8.8.8.8')
        eligibility = AccountGroupEligibility.objects.create(
            pipeline=pipe, account=account, group=group, state='verified',
            can_post_anonymous=True, verified_at=now - timedelta(minutes=2),
            expires_at=now + timedelta(days=1), evidence_note='Human reviewed access in Group.',
        )
        job = PublishingJob.objects.create(
            pipeline=pipe, facebook_account=account, facebook_group=group,
            request_key='pilot-' + suffix, caption='Pilot placeholder content',
            state=PublishingJob.State.QUEUED,
            scheduled_at=now - timedelta(minutes=1), next_run_at=now - timedelta(minutes=1),
        )
        ready = pilot_readiness_snapshot(pipeline_id=pipe.pk)
        assert ready['status'] == 'ready_for_manual_pilot', ready
        assert ready['summary']['ready'] == 1 and ready['items'][0]['blockers'] == []
        assert job.state == PublishingJob.State.QUEUED
        assert not MediaAllocation.objects.filter(pipeline=pipe).exists()
        print('ACCOUNT + FIXED PROXY/IP + ELIGIBILITY + ALBUM READINESS: PASS')

        proxy.exit_ip = '1.1.1.1'
        proxy.save(update_fields=['exit_ip', 'updated_at'])
        mismatch = pilot_readiness_snapshot(pipeline_id=pipe.pk)
        assert mismatch['status'] == 'blocked'
        assert 'PROXY_PIN_MISSING_OR_MISMATCH' in mismatch['items'][0]['blockers']
        proxy.exit_ip = '8.8.8.8'
        proxy.save(update_fields=['exit_ip', 'updated_at'])
        eligibility.state = AccountGroupEligibility.State.UNKNOWN
        eligibility.save()
        unverified = pilot_readiness_snapshot(pipeline_id=pipe.pk)
        assert 'ANONYMOUS_ELIGIBILITY_UNVERIFIED' in unverified['items'][0]['blockers']
        eligibility.state = AccountGroupEligibility.State.VERIFIED
        eligibility.save()
        print('NO PROXY ROTATION; UNVERIFIED ANONYMOUS RIGHTS BLOCK PILOT: PASS')

        prepared = prepare_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=owner)
        assert prepared['state'] == 'prepared'
        pre_open = pilot_readiness_snapshot(pipeline_id=pipe.pk)
        assert pre_open['items'][0]['stage'] == 'ready'
        opened = mutate_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=owner,
                                action='open', expected_version=prepared['version'])
        assert opened['state'] == 'opened'
        report = mutate_handoff(pipeline_id=pipe.pk, job_id=job.pk, actor=owner,
                                action='report', expected_version=opened['version'],
                                outcome='pending_reported', note='Waiting for Group moderation.')
        job.refresh_from_db()
        allocation = job.media_allocation
        allocation.refresh_from_db()
        awaiting = pilot_readiness_snapshot(pipeline_id=pipe.pk)
        assert report['state'] == 'pending_reported'
        assert awaiting['status'] == 'awaiting_review'
        assert awaiting['items'][0]['verified_publication'] is False
        assert job.state == PublishingJob.State.UNCERTAIN and not job.external_post_id
        assert allocation.state == MediaAllocation.State.UNCERTAIN
        assert account.pk in held_subject_ids(pipeline_id=pipe.pk)[0]
        again = pilot_readiness_snapshot(pipeline_id=pipe.pk)
        assert again['status'] == 'awaiting_review'
        assert again['summary'] == awaiting['summary']
        print('PREPARE -> OPEN -> PENDING REPORT: HOLDS RETAINED, NO FALSE PUBLICATION: PASS')

        incomplete = pilot_readiness_snapshot(pipeline_id=pipe.pk, limit=1)
        assert incomplete['truncated'] is False
        assert incomplete['status'] == 'awaiting_review'
        another = PublishingJob.objects.create(
            pipeline=pipe, facebook_account=account, facebook_group=group,
            request_key='pilot-other-' + suffix, caption='Another queued test',
            scheduled_at=now, next_run_at=now,
        )
        incomplete = pilot_readiness_snapshot(pipeline_id=pipe.pk, limit=1)
        assert incomplete['truncated'] and incomplete['status'] == 'incomplete'
        assert incomplete['total_jobs'] == 2
        full = pilot_readiness_snapshot(pipeline_id=pipe.pk, limit=50)
        other_job_row = next(row for row in full['items'] if row['job_id'] == str(another.pk))
        assert other_job_row['stage'] == 'blocked'
        assert 'ACCOUNT_OR_GROUP_HAS_HELD_JOB' in other_job_row['blockers']
        assert request(pipe, owner).status_code == 200
        assert another.state == PublishingJob.State.QUEUED
        print('BOUNDED SCAN IS NOT FALSE PASS; NO MUTATION: PASS')

    transaction.set_rollback(True)

print('ALL PILOT FIXTURES ROLLED BACK — STEP 9.7.17: PASSED')
