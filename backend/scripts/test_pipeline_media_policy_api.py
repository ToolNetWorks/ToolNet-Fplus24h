"""Database rollback tests; do not access R2 or Facebook."""
import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.pipelines.models import Pipeline
from modules.albums.models import Album, AlbumImage
from modules.publishing.models import PipelineAlbumSource, PipelineMediaPolicy
from modules.api.v1.publishing.media_policy_views import PipelineMediaPolicyAPIView

factory = APIRequestFactory()
view = PipelineMediaPolicyAPIView.as_view()
suffix = uuid.uuid4().hex[:10]
User = get_user_model()


def make_pipeline(label):
    user = User.objects.create_user(
        username=f'mediacfg_{label}_{suffix}', password=f'Test#{suffix}Aa1!'
    )
    pipeline = Pipeline.objects.create(
        name=f'Media Config Test {label} {suffix}', ctv=user,
        status=Pipeline.Status.ACTIVE,
    )
    return pipeline, user


def call(method, pipeline, user, data=None):
    uri = f'/api/v1/pipelines/{pipeline.pk}/media-policy/'
    request = (factory.get(uri) if method == 'get' else
               factory.put(uri, data=data, format='json'))
    if user is not None:
        force_authenticate(request, user=user)
    return view(request, pipeline_id=pipeline.pk)


def payload(version, sources, **changes):
    base = {
        'version': version,
        'is_enabled': True,
        'album_selection': 'in_order',
        'image_selection': 'random',
        'reuse_policy': 'no_repeat',
        'images_per_post': 2,
        'sources': sources,
    }
    base.update(changes)
    return base


with transaction.atomic():
    pipeline_a, ctv_a = make_pipeline('a')
    pipeline_b, ctv_b = make_pipeline('b')
    a1 = Album.objects.create(pipeline=pipeline_a, name='Alpha')
    a2 = Album.objects.create(pipeline=pipeline_a, name='Beta')
    foreign = Album.objects.create(pipeline=pipeline_b, name='Other tenant')

    for ix, album in enumerate((a1, a2), start=1):
        AlbumImage.objects.create(
            album=album,
            original_filename=f'test-{ix}.png',
            storage_key=f'test/media-policy/{suffix}/{ix}.png',
            mime_type='image/png', file_size=1024, width=100, height=100,
            sha256=('a' if ix == 1 else 'b') * 64,
            position=ix, upload_status=AlbumImage.UploadStatus.READY,
        )

    initial = call('get', pipeline_a, ctv_a)
    assert initial.status_code == 200, initial.data
    assert initial.data['data']['version'] is None
    assert initial.data['data']['sources'] == []
    assert not PipelineMediaPolicy.objects.filter(pipeline=pipeline_a).exists()
    print('GET WITHOUT SIDE EFFECTS: PASS')

    src = [{'album_id': str(a1.pk)}, {'album_id': str(a2.pk)}]
    response = call('put', pipeline_a, ctv_a, payload(None, src))
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['version'] and data['is_enabled']
    assert [s['position'] for s in data['sources']] == [1, 2]
    assert [s['ready_image_count'] for s in data['sources']] == [1, 1]
    original_source_ids = {s['album_id']: s['id'] for s in data['sources']}
    print('CREATE POLICY + READY COUNTS: PASS')

    reversed_src = list(reversed(src))
    changed = call('put', pipeline_a, ctv_a, payload(data['version'], reversed_src))
    assert changed.status_code == 200, changed.data
    current = changed.data['data']
    assert [s['album_id'] for s in current['sources']] == [str(a2.pk), str(a1.pk)]
    assert {s['album_id']: s['id'] for s in current['sources']} == original_source_ids
    print('REORDER PRESERVES SOURCE IDS: PASS')

    stale = call('put', pipeline_a, ctv_a, payload(data['version'], src))
    assert stale.status_code == 409
    print('STALE POLICY VERSION: BLOCKED')

    invalid = call('put', pipeline_a, ctv_a, payload(
        current['version'], src + [{'album_id': str(foreign.pk)}]
    ))
    assert invalid.status_code == 404, invalid.data
    assert PipelineAlbumSource.objects.filter(pipeline=pipeline_a).count() == 2
    print('CROSS-PIPELINE ALBUM: BLOCKED')

    duplicate = call('put', pipeline_a, ctv_a, payload(
        current['version'], src + [src[0]]
    ))
    assert duplicate.status_code == 400
    print('DUPLICATE SOURCE: BLOCKED')

    empty_enabled = call('put', pipeline_a, ctv_a, payload(current['version'], []))
    assert empty_enabled.status_code == 400
    print('EMPTY ACTIVE SOURCES: BLOCKED')

    too_many = call('put', pipeline_a, ctv_a, payload(
        current['version'], src, images_per_post=3
    ))
    assert too_many.status_code == 400
    print('INSUFFICIENT READY IMAGES: BLOCKED')

    stranger = call('get', pipeline_a, ctv_b)
    assert stranger.status_code == 404
    print('CROSS-PIPELINE CTV ACCESS: BLOCKED')

    anonymous = call('get', pipeline_a, None)
    assert anonymous.status_code in (401, 403)
    print('ANONYMOUS ACCESS: BLOCKED')

    disabled = call('put', pipeline_a, ctv_a, payload(
        current['version'], [], is_enabled=False, images_per_post=1
    ))
    assert disabled.status_code == 200, disabled.data
    assert not disabled.data['data']['is_enabled']
    assert disabled.data['data']['sources'] == []
    print('DISABLE + CLEAR SOURCES: PASS')

    transaction.set_rollback(True)

print('DATABASE CHANGES: ROLLED BACK')
print('MEDIA POLICY API: PASSED')
