"""Rollback-only Step 9.7.13 test: scoped API, read-only telemetry, no Facebook I/O."""
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.publishing.operations_health_views import OperationsHealthAPIView
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import PipelineSchedule
from modules.publishing.services.operations_health import health_snapshot

User = get_user_model()
factory = APIRequestFactory()
suffix = uuid.uuid4().hex[:10]
now = timezone.now()


def request(pipeline, user=None, query=''):
    path = f'/api/v1/pipelines/{pipeline.pk}/operations-health/{query}'
    req = factory.get(path)
    if user is not None:
        force_authenticate(req, user=user)
    return OperationsHealthAPIView.as_view()(req, pipeline_id=pipeline.pk)


with transaction.atomic():
    ctv = User.objects.create_user(username=f'opsui_{suffix}', password='TestOnly!abc12345')
    stranger = User.objects.create_user(username=f'opsother_{suffix}', password='TestOnly!abc12345')
    own = Pipeline.objects.create(name=f'Ops UI {suffix}', ctv=ctv, status=Pipeline.Status.ACTIVE)
    foreign = Pipeline.objects.create(name=f'Ops Other {suffix}', ctv=stranger, status=Pipeline.Status.ACTIVE)

    with patch('socket.socket', side_effect=AssertionError('Network access not expected')):
        resp = request(own, ctv)
        assert resp.status_code == 200, resp.data
        data = resp.data['data']
        assert data['pipeline_id'] == str(own.pk) and data['database']['connected']
        assert data['status'] == 'healthy' and data['schedules']['total'] == 0
        assert data['jobs_by_state'] == {} and data['tick']['last_at'] is None
        assert resp['Cache-Control'] == 'private, no-store'
        assert request(own, stranger).status_code == 404
        assert request(foreign, ctv).status_code == 404
        assert request(own).status_code in (401, 403)
        assert request(own, ctv, '?limit=0').status_code == 400
        assert request(own, ctv, '?limit=251').status_code == 400
        print('TENANT/SESSION/QUERY/NO-CACHE: PASS')

        # A pipeline with no scheduled work is IDLE, not evidence of posting.
        account = FacebookAccount.objects.create(pipeline=own, label='Test Account', connection_status='connected')
        group = FacebookGroup.objects.create(pipeline=own, name='Test Group',
            group_url=f'https://www.facebook.com/groups/opsui{suffix}/')
        job = PublishingJob.objects.create(
            pipeline=own, facebook_account=account, facebook_group=group,
            request_key=f'ops-ui-{suffix}', scheduled_at=now, next_run_at=now,
            state=PublishingJob.State.UNCERTAIN, error_code='UNVERIFIED_RESULT',
        )
        PublishingJob.objects.filter(pk=job.pk).update(updated_at=now - timedelta(hours=49))
        schedule = PipelineSchedule.objects.create(
            pipeline=own, name='Overdue Test', enabled=True,
            start_at=now - timedelta(hours=3), next_run_at=now - timedelta(minutes=45),
            interval_minutes=60, max_groups_per_run=1,
            caption_template='Test caption', require_anonymous=False,
            require_nonmember=False,
        )
        before = (PublishingJob.objects.filter(pipeline=own).count(),
                  PipelineSchedule.objects.filter(pipeline=own).count())
        resp = request(own, ctv)
        assert resp.status_code == 200
        data = resp.data['data']
        assert data['status'] == 'attention'
        assert 'SCHEDULE_OVERDUE' in data['alerts']
        assert 'UNRESOLVED_JOBS_OVER_48H' in data['alerts']
        assert data['jobs_by_state'].get('uncertain') == 1
        assert data['schedules']['overdue_15m'] == 1
        assert before == (PublishingJob.objects.filter(pipeline=own).count(),
                          PipelineSchedule.objects.filter(pipeline=own).count())
        job.refresh_from_db()
        schedule.refresh_from_db()
        assert job.state == PublishingJob.State.UNCERTAIN
        assert schedule.next_run_at == now - timedelta(minutes=45)
        assert health_snapshot(pipeline_id=foreign.pk)['jobs_by_state'] == {}
        serialized = json.dumps(data)
        assert all(secret not in serialized.lower() for secret in (
            'claim_token', 'fb_dtsg', 'authorization', 'database_url', 'cookie',
        ))
        print('REALISTIC ALERTS / READ-ONLY / NO SECRETS / TENANT ISOLATION: PASS')

    transaction.set_rollback(True)

print('ALL OPERATIONS DASHBOARD TEST FIXTURES ROLLED BACK')
print('STEP 9.7.13 OPERATIONS DASHBOARD: PASSED')
