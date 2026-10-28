"""Transactional rollback test; never calls Facebook or R2."""
import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.albums.models import Album, AlbumImage
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.models import (
    PipelineMediaPolicy, PipelineAlbumSource, PublishingJob, MediaAllocation,
)
from modules.api.v1.publishing.job_views import (
    PublishingJobListCreateAPIView, PublishingJobDetailAPIView,
    PublishingJobCancelAPIView,
)
from modules.publishing.management.commands.publishing_worker import prepare_one

factory = APIRequestFactory()
list_view = PublishingJobListCreateAPIView.as_view()
detail_view = PublishingJobDetailAPIView.as_view()
cancel_view = PublishingJobCancelAPIView.as_view()
User = get_user_model()
suffix = uuid.uuid4().hex[:10]


def make_pipeline(tag):
    user = User.objects.create_user(
        username=f'pubapi_{tag}_{suffix}', password=f'Test#{suffix}Aa1!'
    )
    p = Pipeline.objects.create(
        name=f'Publish API {tag} {suffix}', ctv=user,
        status=Pipeline.Status.ACTIVE,
    )
    return p, user


def request(method, pipeline, user, data=None, job=None, query=''):
    uri = f'/api/v1/pipelines/{pipeline.pk}/publishing-jobs/'
    if job:
        uri += f'{job.pk}/'
    if method == 'POST_CREATE':
        req = factory.post(uri, data, format='json')
        view = list_view
    elif method == 'POST_CANCEL':
        req = factory.post(uri + 'cancel/', {}, format='json')
        view = cancel_view
    else:
        req = factory.get(uri + query)
        view = detail_view if job else list_view
    if user:
        force_authenticate(req, user=user)
    kw = {'pipeline_id': pipeline.pk}
    if job:
        kw['job_id'] = job.pk
    return view(req, **kw)


with transaction.atomic():
    a, ua = make_pipeline('a')
    b, ub = make_pipeline('b')
    acct = FacebookAccount.objects.create(
        pipeline=a, label='Test connected account',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    )
    grp = FacebookGroup.objects.create(
        pipeline=a, name='Test Publishing Group',
        group_url=f'https://www.facebook.com/groups/pubapitest{suffix}/',
    )
    album = Album.objects.create(pipeline=a, name='Test Media Album')
    image_id = uuid.uuid4()
    AlbumImage.objects.create(
        id=image_id, album=album,
        original_filename='sample.webp',
        storage_key=f'pipeline-albums/{a.pk}/{album.pk}/{image_id}.webp',
        mime_type='image/webp', file_size=2048, width=50, height=50,
        sha256='a' * 64, upload_status=AlbumImage.UploadStatus.READY,
        position=1,
    )
    PipelineMediaPolicy.objects.create(pipeline=a, is_enabled=True, images_per_post=1)
    PipelineAlbumSource.objects.create(pipeline=a, album=album, position=1)
    body = {
        'account_id': str(acct.pk), 'group_id': str(grp.pk),
        'request_key': f'job-api-{suffix}', 'caption': 'Test scheduled post',
        'max_attempts': 3,
    }
    response = request('POST_CREATE', a, ua, body)
    assert response.status_code == 201, response.data
    assert response.data['data']['state'] == 'queued'
    assert 'claim_token' not in str(response.data)
    job = PublishingJob.objects.get(pk=response.data['data']['id'])
    print('CREATE QUEUED JOB: PASS')

    second = request('POST_CREATE', a, ua, body)
    assert second.status_code == 201
    assert PublishingJob.objects.filter(pipeline=a).count() == 1
    print('IDEMPOTENT CREATE: PASS')

    other = request('GET', b, ub)
    assert other.status_code == 200
    assert other.data['pagination']['total'] == 0
    forbidden = request('GET', a, ub)
    assert forbidden.status_code == 404
    foreign_detail = request('GET', b, ub, job=job)
    assert foreign_detail.status_code == 404
    print('CROSS-PIPELINE JOB ACCESS: BLOCKED')

    listing = request('GET', a, ua)
    assert listing.status_code == 200 and listing.data['summary']['queued'] == 1
    assert listing.data['data'][0]['id'] == str(job.pk)
    assert 'claim_token' not in str(listing.data)
    print('SCOPED LIST + NO CLAIM TOKEN: PASS')

    detail = request('GET', a, ua, job=job)
    assert detail.status_code == 200 and detail.data['data']['attempts'] == []
    print('JOB DETAIL: PASS')

    pending = request('GET', a, ua, query='?state=queued')
    assert pending.status_code == 200 and pending.data['pagination']['total'] == 1
    print('STATUS FILTER: PASS')

    # Worker function is internal and only PREPARES the image allocation.
    prepared = prepare_one(
        pipeline_id=a.pk,
        worker_id='test-worker',
        lease_seconds=600,
    )
    assert prepared is not None and prepared['state'] == 'ready'
    job.refresh_from_db()
    assert job.state == PublishingJob.State.READY
    assert job.media_allocation_id is not None
    assert MediaAllocation.objects.get(pk=job.media_allocation_id).state == 'reserved'
    assert job.external_post_id == ''
    print('WORKER PREPARE ONLY: PASS')
    print('FACEBOOK DISPATCH: NOT CALLED')

    cannot_cancel = request('POST_CANCEL', a, ua, job=job)
    assert cannot_cancel.status_code == 409
    print('READY JOB CANNOT BE CANCELLED BLINDLY: PASS')

    job2 = PublishingJob.objects.create(
        pipeline=a, facebook_account=acct, facebook_group=grp,
        request_key=f'job2-{suffix}', caption='Cancel me',
        scheduled_at=timezone.now(), next_run_at=timezone.now(),
    )
    cancelled = request('POST_CANCEL', a, ua, job=job2)
    assert cancelled.status_code == 200 and cancelled.data['data']['state'] == 'cancelled'
    print('QUEUED CANCELLATION: PASS')

    unauthorized = request('GET', a, None)
    assert unauthorized.status_code in (401, 403)
    print('ANONYMOUS ACCESS: BLOCKED')

    transaction.set_rollback(True)

print('DATABASE CHANGES: ROLLED BACK')
print('PUBLISHING JOB API + PREP WORKER: PASSED')
