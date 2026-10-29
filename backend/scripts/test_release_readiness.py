"""Step 9.7.20 rollback test: no Facebook, R2, Job writes or external deployment."""
import json
import uuid
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.publishing.release_views import PipelineReleaseReadinessAPIView, ReleaseReadThrottle
from modules.pipelines.models import Pipeline
from modules.publishing.services.release_readiness import release_snapshot, ReleaseReadinessError

User = get_user_model()
factory = APIRequestFactory()
suffix = uuid.uuid4().hex[:12]
BASE = 'modules.publishing.services.release_readiness.'


def request(pipe, actor=None, params=''):
    req = factory.get(f'/api/v1/pipelines/{pipe.pk}/release-readiness/{params}')
    if actor is not None:
        force_authenticate(req, user=actor)
    return PipelineReleaseReadinessAPIView.as_view()(req, pipeline_id=pipe.pk)


OPS = {
    'status': 'healthy', 'database': {'connected': True},
    'integrity': {'complete': True, 'status': 'consistent'},
}
SEC = {'complete': True, 'status': 'consistent'}
WORKER = {'truncated': False, 'summary': {'expired_or_missing_lease': 0}}
PILOT = {'truncated': False, 'summary': {'verified': 1, 'awaiting_review': 0, 'blocked': 0}}
PERF = {'status': 'pass', 'load_test_performed': False}


with transaction.atomic():
    owner = User.objects.create_user(username='release_' + suffix, password='TestOnly!Demo123')
    other = User.objects.create_user(username='relother_' + suffix, password='TestOnly!Demo123')
    staff_only = User.objects.create_user(username='relstaff_' + suffix,
                                          password='TestOnly!Demo123', is_staff=True)
    admin = User.objects.create_superuser(username='reladmin_' + suffix,
                                          password='TestOnly!Demo123', email='')
    pipe = Pipeline.objects.create(name='Release gate ' + suffix, ctv=owner,
                                   status=Pipeline.Status.ACTIVE)
    foreign = Pipeline.objects.create(name='Foreign gate ' + suffix, ctv=other,
                                      status=Pipeline.Status.ACTIVE)

    with patch(BASE + 'health_snapshot', return_value=OPS), \
         patch(BASE + 'security_snapshot', return_value=SEC), \
         patch(BASE + 'worker_guard_snapshot', return_value=WORKER), \
         patch(BASE + 'pilot_readiness_snapshot', return_value=PILOT), \
         patch(BASE + 'performance_snapshot', return_value=PERF), \
         patch.object(ReleaseReadThrottle, 'allow_request', return_value=True):
        result = release_snapshot(pipeline_id=pipe.pk)
        assert result['status'] == 'pending_operator_signoff', result
        assert not result['release_approved'] and not result['external_signoff_recorded']
        assert result['automatic_facebook_posting_enabled'] is False
        assert result['summary']['passed'] == 8 and result['summary']['manual_required'] == 4
        assert len(result['checks']) == 12
        assert all(x['status'] == 'manual_required' for x in result['checks'][-4:])
        assert result['summary']['verified_pilot_records'] == 1
        assert request(pipe, owner).status_code == 200
        assert request(pipe, other).status_code == 404
        assert request(foreign, owner).status_code == 404
        assert request(pipe).status_code in (401, 403)
        assert request(pipe, staff_only).status_code == 403
        assert request(pipe, admin).status_code == 200
        assert request(pipe, owner, '?limit=500').status_code == 400
        assert request(pipe, owner)['Cache-Control'] == 'private, no-store'
        assert reverse('pipeline-release-readiness', kwargs={'pipeline_id': pipe.pk}).endswith('/release-readiness/')
        print('TENANT ISOLATION / ADMIN ROLES / HTTP NO-CACHE / MANUAL SIGNOFF: PASS')

        stdout = StringIO()
        call_command('publishing_release_gate', pipeline_id=pipe.pk, stdout=stdout)
        assert '"release_approved": false' in stdout.getvalue()
        try:
            call_command('publishing_release_gate', pipeline_id=pipe.pk, strict=True,
                         stdout=StringIO(), stderr=StringIO())
        except CommandError:
            pass
        else:
            raise AssertionError('--strict must not approve without external signoff')
        print('CLI DEFAULT READ-ONLY / STRICT NEVER AUTO-APPROVES: PASS')

        with patch(BASE + 'pilot_readiness_snapshot', return_value={
            **PILOT, 'summary': {**PILOT['summary'], 'verified': 0},
        }):
            no_pilot = release_snapshot(pipeline_id=pipe.pk)
            assert no_pilot['status'] == 'blocked'
            assert 'INDEPENDENT_POST_EVIDENCE' in [
                x['code'] for x in no_pilot['checks'] if x['status'] == 'blocked']
        with patch(BASE + 'pilot_readiness_snapshot', return_value={
            **PILOT, 'truncated': True,
        }):
            partial = release_snapshot(pipeline_id=pipe.pk)
            assert partial['status'] == 'blocked' and partial['summary']['verified_pilot_records'] == 0
        with patch(BASE + 'worker_guard_snapshot', return_value={
            'truncated': False, 'summary': {'expired_or_missing_lease': 2},
        }):
            assert release_snapshot(pipeline_id=pipe.pk)['status'] == 'blocked'
        with patch(BASE + 'security_snapshot', side_effect=RuntimeError('SENSITIVE_DATABASE_DSN_SHOULD_NOT_LEAK')):
            failure = release_snapshot(pipeline_id=pipe.pk)
            assert failure['status'] == 'blocked'
            assert 'CHECK_FAILED_SECURITY' in failure['errors']
            assert 'SENSITIVE_DATABASE_DSN_SHOULD_NOT_LEAK' not in json.dumps(failure)
        with patch(BASE + 'performance_snapshot', return_value={'status': 'incomplete'}):
            assert release_snapshot(pipeline_id=pipe.pk)['status'] == 'blocked'
        skip = release_snapshot(pipeline_id=pipe.pk, include_performance=False)
        assert skip['status'] == 'blocked'
        assert any(c['status'] == 'not_checked' for c in skip['checks'])
        for invalid in (0, 101, True):
            try:
                release_snapshot(pipeline_id=pipe.pk, limit=invalid)
            except ReleaseReadinessError:
                pass
            else:
                raise AssertionError('Limit validation missing')
        print('NO PILOT / PARTIAL SCAN / STALE WORKER / PROBE ERROR / SKIP PERFORMANCE: BLOCKED')
    transaction.set_rollback(True)

print('ALL FIXTURES ROLLED BACK — STEP 9.7.20: PASSED')
