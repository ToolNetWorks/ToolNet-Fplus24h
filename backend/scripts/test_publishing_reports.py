"""Read-only 9.7.5 reporting integration test; all fixtures rolled back."""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.models import PublishingJob
from modules.publishing.scheduler_models import (
    PipelineSchedule, ScheduledBatch, ScheduledAssignment, GroupHealth,
)
from modules.publishing.services.reports import (
    report_summary, report_batches, report_batch_detail, report_groups,
    report_accounts,
)
from modules.api.v1.publishing.report_views import (
    PipelineReportSummaryAPIView, PipelineReportBatchesAPIView,
    PipelineReportBatchDetailAPIView, PipelineReportGroupsAPIView,
    PipelineReportAccountsAPIView,
)

User = get_user_model()
factory = APIRequestFactory()
suffix = uuid.uuid4().hex[:10]
now = timezone.now()


def make_pipeline(tag):
    ctv = User.objects.create_user(
        username=f'report_{tag}_{suffix}', password=f'Test#{suffix}Aa1!'
    )
    pipeline = Pipeline.objects.create(
        name=f'Reports {tag} {suffix}', ctv=ctv, status=Pipeline.Status.ACTIVE,
    )
    return pipeline, ctv


def invoke(view, pipeline, user=None, path='summary/', batch_id=None, query=''):
    url = f'/api/v1/pipelines/{pipeline.pk}/reports/{path}{query}'
    req = factory.get(url)
    if user is not None:
        force_authenticate(req, user=user)
    kwargs = {'pipeline_id': pipeline.pk}
    if batch_id is not None:
        kwargs['batch_id'] = batch_id
    return view.as_view()(req, **kwargs)


with transaction.atomic():
    pipeline, ctv = make_pipeline('a')
    foreign, outsider = make_pipeline('b')
    account = FacebookAccount.objects.create(
        pipeline=pipeline, label='Account A',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    )
    other_account = FacebookAccount.objects.create(
        pipeline=foreign, label='Foreign Account',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    )
    group_a = FacebookGroup.objects.create(
        pipeline=pipeline, name='Linux A',
        group_url=f'https://www.facebook.com/groups/report{suffix}a/',
    )
    group_b = FacebookGroup.objects.create(
        pipeline=pipeline, name='Linux B',
        group_url=f'https://www.facebook.com/groups/report{suffix}b/',
    )
    group_c = FacebookGroup.objects.create(
        pipeline=pipeline, name='Paused C',
        group_url=f'https://www.facebook.com/groups/report{suffix}c/',
    )
    foreign_group = FacebookGroup.objects.create(
        pipeline=foreign, name='Private Other Group',
        group_url=f'https://www.facebook.com/groups/report{suffix}foreign/',
    )
    GroupHealth.objects.create(
        pipeline=pipeline, group=group_c, state='paused',
        evidence_note='Internal test pause',
    )
    proxy = ProxyEndpoint.objects.create(
        pipeline=pipeline, account=account, host='8.8.8.8', port=8888,
        is_enabled=True, protocol='http',
        health_status=ProxyEndpoint.HealthStatus.HEALTHY,
    )
    schedule = PipelineSchedule.objects.create(
        pipeline=pipeline, name='Report fixture', enabled=False,
        start_at=now - timedelta(hours=1),
        next_run_at=now + timedelta(days=1), interval_minutes=1440,
        max_groups_per_run=10, caption_template='Test {group_name}',
        require_anonymous=True, require_nonmember=True,
    )
    batch = ScheduledBatch.objects.create(
        pipeline=pipeline, schedule=schedule, slot_at=now - timedelta(hours=1),
        assigned_count=2,
        skipped=[{'group_id': str(group_c.pk), 'code': 'GROUP_PAUSED'},
                 {'group_id': str(group_b.pk), 'code': 'GROUP_COOLDOWN'}],
    )
    job_published = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group_a,
        request_key=f'pub-{suffix}', caption='Published in test fixture',
        scheduled_at=now - timedelta(minutes=40),
        next_run_at=now - timedelta(minutes=40),
        state=PublishingJob.State.PUBLISHED,
        external_post_id=f'report-pub-{suffix}', finalized_at=now,
        claim_token=f'SUPERSECRET-{suffix}',
    )
    job_queued = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group_b,
        request_key=f'queue-{suffix}', caption='Queued in test fixture',
        scheduled_at=now, next_run_at=now,
        state=PublishingJob.State.QUEUED,
    )
    job_foreign = PublishingJob.objects.create(
        pipeline=foreign, facebook_account=other_account,
        facebook_group=foreign_group, request_key=f'foreign-{suffix}',
        caption='Never export this', scheduled_at=now, next_run_at=now,
    )
    for idx, job in enumerate([job_published, job_queued]):
        ScheduledAssignment.objects.create(
            batch=batch, job=job, account=account,
            group=job.facebook_group, proxy=proxy,
            exit_ip_snapshot='8.8.8.8', scheduled_at=now + timedelta(minutes=idx),
        )

    with patch('socket.socket', side_effect=AssertionError('Unexpected network')):
        overview = report_summary(pipeline_id=pipeline.pk, days=30, now=now)
        assert overview['jobs']['total'] == 2
        assert overview['jobs']['queued'] == 1
        assert overview['jobs']['published_verified'] == 1
        assert overview['batches'] == 1
        assert overview['skip_events'] == 2
        assert overview['skip_reasons']['GROUP_PAUSED'] == 1
        assert overview['manual_jobs'] == 0
    print('NEON REPORT COUNTS / VERIFIED POST SEMANTICS: PASS')

    batch_page = report_batches(pipeline_id=pipeline.pk, days=30, now=now)
    assert batch_page['pagination']['total'] == 1
    assert batch_page['data'][0]['assigned_count'] == 2
    assert batch_page['data'][0]['skip_events'] == 2
    print('BATCH PAGINATION AND SKIP EVENTS: PASS')

    detail = report_batch_detail(pipeline_id=pipeline.pk, batch_id=batch.pk)
    assert len(detail['assignments']) == 2
    assert len(detail['skipped']) == 2
    assert sum(row['published_verified'] for row in detail['assignments']) == 1
    assert f'SUPERSECRET-{suffix}' not in str(detail)
    assert 'Never export this' not in str(detail)
    print('BATCH DETAIL NO CLAIM TOKEN OR FOREIGN JOB: PASS')

    groups = report_groups(pipeline_id=pipeline.pk, days=30, now=now)
    by_id = {row['group_id']: row for row in groups['data']}
    assert len(groups['data']) == 3
    assert by_id[str(group_a.pk)]['published_verified'] == 1
    assert by_id[str(group_c.pk)]['health_state'] == 'paused'
    assert by_id[str(group_c.pk)]['skip_events'] == 1
    assert by_id[str(group_b.pk)]['queued'] == 1
    assert not any(row['group_id'] == str(foreign_group.pk) for row in groups['data'])
    print('PER-GROUP REPORT + HEALTH + TENANT ISOLATION: PASS')

    accounts = report_accounts(pipeline_id=pipeline.pk, days=30, now=now)
    assert len(accounts['data']) == 1
    assert accounts['data'][0]['published_verified'] == 1
    assert accounts['data'][0]['queued'] == 1
    assert accounts['data'][0]['proxy_assigned'] is True
    assert 'host' not in accounts['data'][0]
    print('ACCOUNT REPORT NO PROXY CREDENTIALS: PASS')

    filtered = report_summary(pipeline_id=pipeline.pk, days=30,
                              schedule_id=schedule.pk, now=now)
    assert filtered['scheduled_jobs'] == 2
    assert filtered['manual_jobs'] == 0
    try:
        report_batch_detail(pipeline_id=foreign.pk, batch_id=batch.pk)
    except Http404:
        print('FOREIGN BATCH DETAIL: BLOCKED')
    else:
        raise AssertionError('Cross-pipeline batch exposure')

    path = f'/api/v1/pipelines/{pipeline.pk}/reports/summary/'
    owned = invoke(PipelineReportSummaryAPIView, pipeline, ctv)
    assert owned.status_code == 200, owned.data
    assert owned.data['data']['jobs']['total'] == 2
    assert owned['Cache-Control'] == 'private, no-store'
    assert 'claim_token' not in str(owned.data)
    assert 'SUPERSECRET-' not in str(owned.data)
    assert 'Private Other Group' not in str(owned.data)
    print('AUTHENTICATED CTV REPORT: PASS')

    forbidden = invoke(PipelineReportSummaryAPIView, pipeline, outsider)
    assert forbidden.status_code == 404
    foreign_batch = invoke(PipelineReportBatchDetailAPIView, foreign, outsider,
                           path=f'batches/{batch.pk}/', batch_id=batch.pk)
    assert foreign_batch.status_code == 404
    print('CTV CROSS-PIPELINE API: BLOCKED')

    anon = invoke(PipelineReportSummaryAPIView, pipeline, None)
    assert anon.status_code in (401, 403)
    invalid = invoke(PipelineReportSummaryAPIView, pipeline, ctv, query='?days=365')
    assert invalid.status_code == 400
    bad_uuid = invoke(PipelineReportSummaryAPIView, pipeline, ctv,
                      query=f'?schedule_id={foreign.pk}')
    assert bad_uuid.status_code == 404
    print('ANONYMOUS / INVALID WINDOW / FOREIGN SCHEDULE: BLOCKED')

    for cls, path in (
        (PipelineReportBatchesAPIView, 'batches/'),
        (PipelineReportGroupsAPIView, 'groups/'),
        (PipelineReportAccountsAPIView, 'accounts/'),
    ):
        res = invoke(cls, pipeline, ctv, path)
        assert res.status_code == 200, res.data
        assert res.data['data']['pagination']['total'] >= 1
    print('SCOPED BATCH/GROUP/ACCOUNT LIST API: PASS')

    assert PublishingJob.objects.filter(pipeline=pipeline).count() == 2
    assert ScheduledBatch.objects.filter(pipeline=pipeline).count() == 1
    transaction.set_rollback(True)

print('ALL REPORT FIXTURES ROLLED BACK')
print('STEP 9.7.5 REPORTING: PASSED')
