"""Rollback-only ORM/API test for Step 9.7.8. No Facebook network or state changes."""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.review_models import PublishingReviewCase, PublishingReviewEvent
from modules.publishing.services.review_sla import review_sla_snapshot, SLAQueryError
from modules.api.v1.publishing.review_sla_views import ReviewSLAAPIView

User = get_user_model()
now = timezone.now()
suffix = uuid.uuid4().hex[:10]
factory = APIRequestFactory()


def build_pipeline(tag):
    ctv = User.objects.create_user(username=f'sla_{tag}_{suffix}', password=f'Test#{suffix}Aa1!')
    p = Pipeline.objects.create(name=f'SLA {tag} {suffix}', ctv=ctv, status=Pipeline.Status.ACTIVE)
    account = FacebookAccount.objects.create(pipeline=p, label=f'Account {tag}',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED)
    group = FacebookGroup.objects.create(pipeline=p, name=f'Group {tag}',
        group_url=f'https://www.facebook.com/groups/slatest{suffix}{tag}/')
    return p, ctv, account, group


def new_case(pipeline, acc, group, tag, state, status, idle_hours, assignee=None, post_id=''):
    job = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=acc, facebook_group=group,
        request_key=f'sla-{tag}-{suffix}', scheduled_at=now, next_run_at=now,
        state=state, external_post_id=post_id,
        claim_token='SECRET-CLAIM-DO-NOT-LEAK',
    )
    case = PublishingReviewCase.objects.create(
        pipeline=pipeline, job=job, assigned_to=assignee, status=status,
        closed_at=now if status == PublishingReviewCase.Status.CLOSED else None,
    )
    stamp = now - timedelta(hours=idle_hours)
    PublishingReviewCase.objects.filter(pk=case.pk).update(
        updated_at=stamp, created_at=stamp - timedelta(hours=1),
    )
    return case, job


def api(pipeline, user=None, query=''):
    req = factory.get(f'/api/v1/pipelines/{pipeline.pk}/review-sla/{query}')
    if user is not None:
        force_authenticate(req, user=user)
    return ReviewSLAAPIView.as_view()(req, pipeline_id=pipeline.pk)


with transaction.atomic():
    p, ctv, acc, grp = build_pipeline('owner')
    foreign, outsider, other_acc, other_grp = build_pipeline('other')
    a, ja = new_case(p, acc, grp, 'a', 'uncertain', 'open', 25)
    b, jb = new_case(p, acc, grp, 'b', 'uncertain', 'in_review', 7, assignee=ctv)
    c, jc = new_case(p, acc, grp, 'c', 'uncertain', 'awaiting_verification', 26, assignee=ctv)
    d, jd = new_case(p, acc, grp, 'd', 'failed', 'open', 0, assignee=ctv)
    closed, jclosed = new_case(p, acc, grp, 'closed', 'failed', 'closed', 50, assignee=ctv)
    f, jf = new_case(foreign, other_acc, other_grp, 'foreign', 'uncertain', 'open', 60)
    PublishingReviewEvent.objects.create(
        case=b, actor=ctv, kind=PublishingReviewEvent.Kind.EVIDENCE,
        note='Observed the group in a human review; no confirmed posting.',
        job_state_snapshot='uncertain',
    )
    PublishingReviewEvent.objects.create(
        case=c, actor=ctv, kind=PublishingReviewEvent.Kind.EVIDENCE,
        note='Unable to verify actual Facebook post id.', job_state_snapshot='uncertain',
    )
    before = dict(PublishingReviewCase.objects.filter(pipeline=p).values_list('pk', 'version'))
    states = dict(PublishingJob.objects.filter(pipeline=p).values_list('pk', 'state'))
    with patch('socket.socket', side_effect=AssertionError('Unexpected network')):
        overview = review_sla_snapshot(pipeline_id=p.pk, now=now)
        assert overview['summary']['total'] == 4, overview
        assert overview['summary']['critical'] == 1
        assert overview['summary']['overdue'] == 3
        assert overview['summary']['unassigned'] == 1
        assert overview['summary']['awaiting_verification'] == 1
        assert overview['summary']['terminal_not_closed'] == 1
        assert overview['auto_resolution_enabled'] is False
        assert overview['facebook_verification_enabled'] is False
        rows = {i['case_id']: i for i in overview['items']}
        assert rows[str(a.pk)]['severity'] == 'critical'
        assert rows[str(a.pk)]['next_action'] == 'assign_owner'
        assert rows[str(b.pk)]['severity'] == 'warning'
        assert rows[str(b.pk)]['evidence_count'] == 1
        assert rows[str(b.pk)]['next_action'] == 'request_independent_verification'
        assert rows[str(c.pk)]['next_action'] == 'await_independent_verification'
        assert rows[str(d.pk)]['next_action'] == 'document_terminal_evidence'
        assert not any(i['case_id'] in (str(closed.pk), str(f.pk)) for i in overview['items'])
        assert not any(i['external_post_verified'] for i in overview['items'])
        assert 'SECRET-CLAIM-DO-NOT-LEAK' not in str(overview)
        print('SLA THRESHOLDS / EVIDENCE READINESS / NO FALSE POST: PASS')

        critical = review_sla_snapshot(pipeline_id=p.pk, filter_by='critical', now=now)
        assert critical['pagination']['total'] == 1
        overdue = review_sla_snapshot(pipeline_id=p.pk, filter_by='overdue', now=now)
        assert overdue['pagination']['total'] == 3
        awaiting = review_sla_snapshot(pipeline_id=p.pk, filter_by='awaiting', now=now)
        assert awaiting['pagination']['total'] == 1
        paged = review_sla_snapshot(pipeline_id=p.pk, page_size=2, page=2, now=now)
        assert len(paged['items']) == 2 and paged['pagination']['total_pages'] == 2
        print('FILTERS / PAGINATION: PASS')

        for kwargs in ({'page': 0}, {'page_size': 100}, {'filter_by': 'bad'}, {'page': 12}):
            try:
                review_sla_snapshot(pipeline_id=p.pk, now=now, **kwargs)
            except SLAQueryError:
                pass
            else:
                raise AssertionError(f'Invalid SLA query accepted: {kwargs}')
        print('QUERY VALIDATION: PASS')

        owned = api(p, ctv)
        assert owned.status_code == 200 and owned.data['data']['summary']['total'] == 4
        assert owned['Cache-Control'] == 'private, no-store'
        assert 'claim_token' not in str(owned.data)
        assert api(p, outsider).status_code == 404
        assert api(p).status_code in (401, 403)
        assert api(p, ctv, '?page_size=51').status_code == 400
        assert api(foreign, outsider).status_code == 200
        assert str(f.pk) not in str(owned.data)
        print('CTV AUTH / TENANT ISOLATION / NO CREDENTIAL LEAK: PASS')

    assert dict(PublishingReviewCase.objects.filter(pipeline=p).values_list('pk', 'version')) == before
    assert dict(PublishingJob.objects.filter(pipeline=p).values_list('pk', 'state')) == states
    assert PublishingReviewEvent.objects.filter(case__pipeline=p).count() == 2
    print('PURE READ ONLY / NO EVENT OR STATE MUTATION: PASS')
    transaction.set_rollback(True)

print('ALL SLA FIXTURES ROLLED BACK')
print('STEP 9.7.8 REVIEW SLA: PASSED')
