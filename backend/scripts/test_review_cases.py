"""Isolated rollback-only review workflow test; never visits Facebook."""
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
from modules.publishing.services.reconciliation import held_subject_ids, reconciliation_snapshot
from modules.publishing.services.review_cases import (
    open_case, get_case, list_cases, take_action, CaseConflict, CaseError,
)
from modules.api.v1.publishing.review_case_views import (
    ReviewCaseListCreateAPIView, ReviewCaseDetailAPIView, ReviewCaseActionAPIView,
)

User = get_user_model()
suffix = uuid.uuid4().hex[:10]
now = timezone.now()
factory = APIRequestFactory()


def make_pipeline(tag):
    user = User.objects.create_user(username=f'review_{tag}_{suffix}', password=f'Test#{suffix}Aa1!')
    return Pipeline.objects.create(name=f'Review {tag} {suffix}', ctv=user, status='active'), user


def request(view, method, path, pipeline, user=None, data=None, case=None):
    req = factory.post(path, data or {}, format='json') if method == 'POST' else factory.get(path)
    if user is not None:
        force_authenticate(req, user=user)
    kw = {'pipeline_id': pipeline.pk}
    if case is not None:
        kw['case_id'] = case
    return view.as_view()(req, **kw)


with transaction.atomic():
    pipeline, ctv = make_pipeline('owned')
    foreign, outsider = make_pipeline('foreign')
    account = FacebookAccount.objects.create(pipeline=pipeline, label='Reviewer Account', connection_status='connected')
    group = FacebookGroup.objects.create(pipeline=pipeline, name='Review Group',
        group_url=f'https://www.facebook.com/groups/review{suffix}/')
    foreign_account = FacebookAccount.objects.create(pipeline=foreign, label='Other Account')
    foreign_group = FacebookGroup.objects.create(pipeline=foreign, name='Other Group',
        group_url=f'https://www.facebook.com/groups/foreignreview{suffix}/')
    job = PublishingJob.objects.create(
        pipeline=pipeline, facebook_account=account, facebook_group=group,
        request_key=f'review-{suffix}', caption='Sensitive content should stay private',
        scheduled_at=now, next_run_at=now, state='uncertain',
        error_code='UNVERIFIED_RESULT', claim_token='TEST-SECRET-DO-NOT-EXPOSE',
    )
    other = PublishingJob.objects.create(
        pipeline=foreign, facebook_account=foreign_account, facebook_group=foreign_group,
        request_key=f'other-{suffix}', scheduled_at=now, next_run_at=now, state='uncertain',
    )
    with patch('socket.socket', side_effect=AssertionError('Unexpected network')):
        opened, created = open_case(pipeline_id=pipeline.pk, job_id=job.pk, actor=ctv)
        assert created and opened['status'] == 'open'
        replay, created = open_case(pipeline_id=pipeline.pk, job_id=job.pk, actor=ctv)
        assert not created and opened['id'] == replay['id']
        assert PublishingReviewCase.objects.filter(pipeline=pipeline).count() == 1
        assert PublishingReviewEvent.objects.filter(case_id=opened['id']).count() == 1
        assert 'TEST-SECRET-DO-NOT-EXPOSE' not in str(opened)
        print('CREATE IDEMPOTENT / SAFE OUTPUT: PASS')

        case_id = opened['id']
        assigned = take_action(pipeline_id=pipeline.pk, case_id=case_id, actor=ctv,
            action='assign_me', expected_version=1)
        assert assigned['status'] == 'in_review' and assigned['version'] == 2
        try:
            take_action(pipeline_id=pipeline.pk, case_id=case_id, actor=ctv,
                action='add_evidence', expected_version=1, note='Old version must fail')
        except CaseConflict:
            pass
        else:
            raise AssertionError('Stale version accepted')
        print('OWNER ASSIGNMENT / OPTIMISTIC LOCK: PASS')

        with transaction.atomic():
            try:
                take_action(pipeline_id=pipeline.pk, case_id=case_id, actor=ctv,
                    action='add_evidence', expected_version=2, note='Evidence check at 08:00',
                    evidence_url='https://evil.example.com/phishing')
            except CaseError:
                pass
            else:
                raise AssertionError('Untrusted evidence link accepted')
        case = get_case(pipeline_id=pipeline.pk, case_id=case_id)
        assert case['version'] == 2
        evidence = take_action(pipeline_id=pipeline.pk, case_id=case_id, actor=ctv,
            action='add_evidence', expected_version=2,
            note='Checked group manually, result remains uncertain.',
            evidence_url='https://www.facebook.com/groups/review123/permalink/456/')
        assert evidence['version'] == 3 and evidence['events'][-1]['kind'] == 'evidence'
        escalated = take_action(pipeline_id=pipeline.pk, case_id=case_id,
            actor=ctv, action='request_verification', expected_version=3)
        assert escalated['status'] == 'awaiting_verification'
        print('EVIDENCE / ESCALATION / AUDIT: PASS')

        try:
            take_action(pipeline_id=pipeline.pk, case_id=case_id, actor=ctv,
                action='close', expected_version=4)
        except CaseConflict:
            pass
        else:
            raise AssertionError('Uncertain job could be closed')
        assert account.pk in held_subject_ids(pipeline_id=pipeline.pk)[0]
        assert PublishingJob.objects.get(pk=job.pk).state == 'uncertain'
        print('UNCERTAIN JOB CANNOT CLOSE OR RELEASE HOLD: PASS')

        listing = list_cases(pipeline_id=pipeline.pk)
        assert listing['pagination']['total'] == 1
        assert list_cases(pipeline_id=foreign.pk)['pagination']['total'] == 0
        try:
            open_case(pipeline_id=pipeline.pk, job_id=other.pk, actor=ctv)
        except CaseError:
            pass
        else:
            raise AssertionError('Foreign job accepted')
        print('TENANT ISOLATION / LIST PAGINATION: PASS')

        list_path = f'/api/v1/pipelines/{pipeline.pk}/review-cases/'
        valid = request(ReviewCaseListCreateAPIView, 'GET', list_path, pipeline, ctv)
        assert valid.status_code == 200 and valid.data['data']['pagination']['total'] == 1
        forbidden = request(ReviewCaseListCreateAPIView, 'GET', list_path, pipeline, outsider)
        assert forbidden.status_code == 404
        unauth = request(ReviewCaseListCreateAPIView, 'GET', list_path, pipeline)
        assert unauth.status_code in (401, 403)
        other_detail = request(ReviewCaseDetailAPIView, 'GET', list_path, foreign, outsider, case=case_id)
        assert other_detail.status_code == 404
        assert 'claim_token' not in str(valid.data)
        print('CTV AUTH / FOREIGN / ANONYMOUS: BLOCKED: PASS')

        # Only already-terminal, independently established job state can end review.
        job.state = PublishingJob.State.FAILED
        job.error_code = 'PREFLIGHT_FAILED'
        job.finalized_at = timezone.now()
        job.save()
        closed = take_action(pipeline_id=pipeline.pk, case_id=case_id, actor=ctv,
            action='close', expected_version=4)
        assert closed['status'] == 'closed' and closed['held'] is False
        assert closed['events'][-1]['kind'] == 'closed'
        assert PublishingJob.objects.get(pk=job.pk).state == 'failed'
        assert account.pk not in held_subject_ids(pipeline_id=pipeline.pk)[0]
        final_snapshot = reconciliation_snapshot(pipeline_id=pipeline.pk, now=timezone.now())
        assert final_snapshot['summary']['failed'] == 1
        assert final_snapshot['summary']['review_required_jobs'] == 0
        try:
            take_action(pipeline_id=pipeline.pk, case_id=case_id, actor=ctv,
                action='add_evidence', expected_version=5,
                note='Editing closed record is disallowed')
        except CaseConflict:
            pass
        else:
            raise AssertionError('Closed case edited')
        print('TERMINAL JOB CASE CLOSURE / IMMUTABLE AUDIT: PASS')

    transaction.set_rollback(True)

print('ALL REVIEW FIXTURES ROLLED BACK')
print('STEP 9.7.7 HUMAN REVIEW WORKFLOW: PASSED')
