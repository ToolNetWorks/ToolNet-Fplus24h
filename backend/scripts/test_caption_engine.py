"""9.7.19A rollback-only smoke tests. No AI network or Facebook requests.

Run: python manage.py shell -c "exec(open('scripts/test_caption_engine.py').read())"
"""
import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.publishing.models import PublishingJob
from modules.publishing.caption_models import JobCaption, CaptionSample
from modules.publishing.services.caption_engine import (
    CaptionError, CaptionConflict, check_destination, finalize_caption,
    update_settings, create_sample, generate_job_caption, approve_job_caption,
    ready_for_dispatch,
)
from modules.api.v1.publishing.caption_views import (
    CaptionSettingsAPIView, CaptionSamplesAPIView, CaptionJobAPIView,
)

User = get_user_model()
request_factory = APIRequestFactory()


def call(view, method, path, pipe_id, user, job_id=None, payload=None):
    maker = getattr(request_factory, method)
    request = maker(path, data=payload, format='json') if payload is not None else maker(path)
    force_authenticate(request, user=user)
    values = {'pipeline_id': pipe_id}
    if job_id: values['job_id'] = job_id
    return view.as_view()(request, **values)


suffix = uuid.uuid4().hex[:10]
assert check_destination('@hiu9h') == '@hiu9h'
assert finalize_caption('Hôm nay em buồn', '@hiu9h') == 'Hôm nay em buồn\n\nLiên hệ: @hiu9h'
assert finalize_caption(finalize_caption('Hôm nay em buồn', '@hiu9h'), '@hiu9h') == \
       finalize_caption('Hôm nay em buồn', '@hiu9h')
try:
    finalize_caption('Liên hệ @sai_trang', '@hiu9h')
    raise AssertionError('Foreign destination must be rejected')
except CaptionError:
    pass
print('DESTINATION EXACT-ONE, IDEMPOTENT, FOREIGN-DESTINATION: PASS')

with transaction.atomic():
    ctv = User.objects.create_user(username='capctv_' + suffix, password='FixtureOnly!2026')
    other = User.objects.create_user(username='capother_' + suffix, password='FixtureOnly!2026')
    admin = User.objects.create_superuser(username='capadmin_' + suffix,
                                            password='FixtureOnly!2026', email='')
    pipe = Pipeline.objects.create(name='Caption pilot ' + suffix,
                                   ctv=ctv, status=Pipeline.Status.ACTIVE)
    foreign = Pipeline.objects.create(name='Caption foreign ' + suffix,
                                      ctv=other, status=Pipeline.Status.ACTIVE)
    a = FacebookAccount.objects.create(pipeline=pipe, label='Caption account',
                                       connection_status=FacebookAccount.ConnectionStatus.CONNECTED)
    g = FacebookGroup.objects.create(pipeline=pipe, name='Caption group',
        group_url=f'https://www.facebook.com/groups/caption{suffix}/')
    job = PublishingJob.objects.create(pipeline=pipe, facebook_account=a,
        facebook_group=g, request_key='caption-' + suffix, state=PublishingJob.State.QUEUED,
        scheduled_at=timezone.now(), next_run_at=timezone.now())

    config = update_settings(pipeline_id=pipe.pk, actor=admin, destination='@hiu9h',
        enabled=True, auto_generate=True, auto_approve=False, writing_guidance='Giọng văn tự nhiên')
    assert config['enabled'] and config['destination'] == '@hiu9h'
    assert not ready_for_dispatch(job)
    assert call(CaptionSettingsAPIView, 'get', '/test/', pipe.pk, ctv).status_code == 200
    assert call(CaptionSettingsAPIView, 'get', '/test/', foreign.pk, ctv).status_code == 404
    assert call(CaptionSettingsAPIView, 'put', '/test/', pipe.pk, ctv,
        payload=dict(config)).status_code == 404
    assert call(CaptionSettingsAPIView, 'put', '/test/', pipe.pk, admin,
        payload=dict(config)).status_code == 200
    assert reverse('caption-config', kwargs={'pipeline_id':pipe.pk}).endswith('/caption-config/')
    print('CTV ADMIN DESTINATION-LOCK AND TENANT ISOLATION: PASS')

    create_sample(pipeline_id=pipe.pk, actor=ctv,
                  text='Hôm nay em buồn, ai trò chuyện với em không? @hiu9h')
    assert call(CaptionSamplesAPIView, 'get', '/test/', pipe.pk, ctv).status_code == 200
    assert call(CaptionSamplesAPIView, 'get', '/test/', foreign.pk, ctv).status_code == 404
    assert CaptionSample.objects.filter(pipeline=pipe).count() == 1
    try:
        update_settings(pipeline_id=pipe.pk, actor=admin, destination='@khac',
            enabled=True, auto_generate=True, auto_approve=False, writing_guidance='')
        raise AssertionError('Changing destination with queued Job should fail')
    except CaptionConflict:
        pass
    print('SAMPLE LIBRARY + NO DESTINATION ROTATION WHILE JOB IS PENDING: PASS')

    with patch('modules.publishing.services.caption_engine._provider',
               return_value=('Em đang hơi buồn, có ai muốn tâm sự cùng em không?', 'fixture-model')):
        created = generate_job_caption(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv)
    assert created['state'] == JobCaption.State.DRAFT
    assert created['text'].count('@hiu9h') == 1
    job.refresh_from_db()
    assert job.caption == '' and not ready_for_dispatch(job)
    assert call(CaptionJobAPIView, 'get', '/test/', foreign.pk, other,
                job_id=job.pk).status_code == 404
    updated = approve_job_caption(pipeline_id=pipe.pk, job_id=job.pk, actor=ctv,
                                  expected_revision=created['revision'])
    assert updated['state'] == JobCaption.State.APPROVED
    job.refresh_from_db()
    assert job.caption == updated['text'] and ready_for_dispatch(job)
    assert job.caption.endswith('Liên hệ: @hiu9h')
    print('AI DRAFT, HUMAN APPROVAL, VERSION, JOB CAPTION AND DISPATCH GUARD: PASS')

    transaction.set_rollback(True)
print('ROLLBACK: PASS — NO FIXTURE ROWS PERSISTED')
