"""Step 9.7.19 rollback-only baseline smoke test; no Facebook/R2 I/O.

This tests bounded, tenant-safe sampling, deterministic fail-closed handling,
read-only behavior, HTTP authorization, and no SQL/credential leakage.
"""
import io
import json
import time
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.publishing.performance_views import PipelinePerformanceAPIView
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.services.performance_stability import (
    PerformanceStabilityError, performance_snapshot,
)

User = get_user_model()
factory = APIRequestFactory()
suffix = uuid.uuid4().hex[:10]


def request(pipeline, actor=None, query=''):
    req = factory.get('/api/v1/pipelines/%s/performance/%s' % (pipeline.pk, query))
    if actor is not None:
        force_authenticate(req, user=actor)
    return PipelinePerformanceAPIView.as_view()(req, pipeline_id=pipeline.pk)


def expect_error(fn, cls):
    try:
        fn()
    except cls:
        return
    raise AssertionError('Expected %s' % cls.__name__)


with transaction.atomic():
    ctv = User.objects.create_user(username='perf_' + suffix, password='FixtureOnly!1234')
    other = User.objects.create_user(username='perf_other_' + suffix, password='FixtureOnly!1234')
    only_super = User.objects.create_user(username='perf_super_' + suffix,
                                           password='FixtureOnly!1234', is_superuser=True)
    admin = User.objects.create_superuser(username='perf_admin_' + suffix,
                                          password='FixtureOnly!1234', email='')
    own = Pipeline.objects.create(name='Perf fixture ' + suffix, ctv=ctv, status=Pipeline.Status.ACTIVE)
    foreign = Pipeline.objects.create(name='Perf other ' + suffix, ctv=other, status=Pipeline.Status.ACTIVE)

    with patch('socket.socket', side_effect=AssertionError('External network not allowed')):
        record = performance_snapshot(pipeline_id=own.pk, repeats=2, limit=25,
                                      threshold_ms=15000)
        assert record['pipeline_id'] == str(own.pk)
        assert record['read_only'] is True and record['facebook_dispatch_enabled'] is False
        assert record['load_test_performed'] is False
        assert record['production_capacity_certified'] is False
        assert record['status'] == 'not_configured', record
        assert len(record['probes']) == 6
        assert all(p['runs'] == 2 and p['query_count_max'] >= 0 for p in record['probes'])
        assert all(p['status'] == 'pass' for p in record['probes']), record
        assert record['summary']['jobs'] == 0 and record['summary']['schedules'] == 0
        assert not PublishingJob.objects.filter(pipeline=own).exists()
        assert not PublishingJob.objects.filter(pipeline=foreign).exists()
        print('READ-ONLY BASELINE / EMPTY IS NOT PROOF OF CAPACITY: PASS')

        response = request(own, ctv)
        assert response.status_code == 200, response.data
        assert response.data['data']['pipeline_id'] == str(own.pk)
        assert response['Cache-Control'] == 'private, no-store'
        assert request(own, other).status_code == 404
        assert request(foreign, ctv).status_code == 404
        assert request(own).status_code in (401, 403)
        assert request(own, only_super).status_code == 403
        assert request(own, admin).status_code == 200
        assert request(own, ctv, '?repeats=5').status_code == 400
        assert reverse('pipeline-performance', kwargs={'pipeline_id': own.pk}).endswith('/performance/')
        print('AUTH + TENANT + NO CACHE + BOUNDED API: PASS')

        for kwargs in ({'repeats': 0}, {'repeats': 6}, {'limit': 0}, {'limit': 101},
                       {'threshold_ms': 99}, {'threshold_ms': 15001}):
            expect_error(lambda kwargs=kwargs: performance_snapshot(
                pipeline_id=own.pk, **kwargs), PerformanceStabilityError)
        expect_error(lambda: performance_snapshot(pipeline_id=uuid.uuid4()), PerformanceStabilityError)
        print('STRICT INPUT BOUNDS: PASS')

        marker = 'SENSITIVE_DATABASE_ERROR_DO_NOT_EXPOSE_' + suffix
        with patch('modules.publishing.services.performance_stability.security_snapshot',
                   side_effect=RuntimeError(marker)):
            broken = performance_snapshot(pipeline_id=own.pk, repeats=1)
            assert broken['status'] == 'error'
            assert broken['summary']['errors'] == 1
            assert marker not in json.dumps(broken)
            assert broken['probes'][-1]['status'] == 'error'
        print('FAIL-CLOSED EXCEPTION / ERROR REDACTION: PASS')

        with patch('modules.publishing.services.performance_stability.security_snapshot',
                   return_value={'complete': False, 'status': 'incomplete'}):
            partial = performance_snapshot(pipeline_id=own.pk, repeats=1)
            assert partial['status'] == 'incomplete', partial
            assert partial['summary']['incomplete'] >= 1
        print('PARTIAL SCAN NOT PASSED AS HEALTHY: PASS')

        def slow_probe():
            time.sleep(.12)
            return {'complete': True, 'attention': False}
        with patch('modules.publishing.services.performance_stability._workloads',
                   return_value={'database_ping': slow_probe}):
            slow = performance_snapshot(pipeline_id=own.pk, repeats=1, threshold_ms=100)
            assert slow['status'] == 'attention' and slow['summary']['slow'] == 1
            assert slow['probes'][0]['status'] == 'slow'
        print('LATENCY THRESHOLD: PASS')

        # Create a valid Job and check the baseline is not accidentally cross-tenant.
        a = FacebookAccount.objects.create(pipeline=own, label='Perf Account')
        g = FacebookGroup.objects.create(pipeline=own, name='Perf Group',
                 group_url='https://www.facebook.com/groups/perftest%s/' % suffix)
        PublishingJob.objects.create(pipeline=own, facebook_account=a, facebook_group=g,
                                     request_key='perf-' + suffix,
                                     scheduled_at=timezone.now(),
                                     next_run_at=timezone.now())
        before = PublishingJob.objects.filter(pipeline=own).count()
        one = performance_snapshot(pipeline_id=own.pk, repeats=1, threshold_ms=15000)
        assert one['summary']['jobs'] == before and one['summary']['schedules'] == 0
        assert PublishingJob.objects.filter(pipeline=own).count() == before
        assert PublishingJob.objects.filter(pipeline=foreign).count() == 0
        out = io.StringIO()
        call_command('publishing_performance', pipeline_id=own.pk, repeats=1,
                     limit=25, threshold_ms=15000, stdout=out)
        assert json.loads(out.getvalue())['pipeline_id'] == str(own.pk)
        expect_error(lambda: call_command('publishing_performance', pipeline_id=foreign.pk,
                     repeats=1, threshold_ms=15000, strict=True, stdout=io.StringIO()), CommandError)
        print('CLI + JOB COUNTS + STRICT EMPTY PIPELINE: PASS')

    transaction.set_rollback(True)
print('STEP 9.7.19: PASSED — ALL FIXTURES ROLLED BACK')
