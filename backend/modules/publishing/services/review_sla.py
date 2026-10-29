"""Read-only, per-Pipeline review-case aging and verification readiness.

Safety: never changes Job, MediaAllocation, Case or Event state. Evidence
submitted by a CTV is an unverified observation, NOT Facebook publication.
"""
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.utils import timezone

from modules.publishing.models import PublishingJob
from modules.publishing.review_models import PublishingReviewCase, PublishingReviewEvent


class SLAQueryError(ValueError):
    pass


PENDING = (
    PublishingReviewCase.Status.OPEN,
    PublishingReviewCase.Status.IN_REVIEW,
    PublishingReviewCase.Status.AWAITING,
)


def review_sla_snapshot(*, pipeline_id, page=1, page_size=20, filter_by='all', now=None):
    """Compute age from last case update, without writing state or calling Facebook.

    Windows: unassigned/open >=2h; in_review >=6h; awaiting >=24h.
    Critical: no activity >=48h, or unassigned/open >=24h.
    These are operational defaults, not claims about Facebook availability.
    """
    if type(page) is not int or page < 1:
        raise SLAQueryError('page phải là số nguyên >= 1.')
    if type(page_size) is not int or not 1 <= page_size <= 50:
        raise SLAQueryError('page_size phải nằm trong 1..50.')
    if filter_by not in ('all', 'overdue', 'critical', 'awaiting'):
        raise SLAQueryError('Bộ lọc không hợp lệ.')
    now = timezone.now() if now is None else now
    if timezone.is_naive(now):
        raise SLAQueryError('Thời gian phải có múi giờ.')

    open_old = Q(status=PublishingReviewCase.Status.OPEN,
                 updated_at__lte=now - timedelta(hours=2))
    review_old = Q(status=PublishingReviewCase.Status.IN_REVIEW,
                   updated_at__lte=now - timedelta(hours=6))
    awaiting_old = Q(status=PublishingReviewCase.Status.AWAITING,
                     updated_at__lte=now - timedelta(hours=24))
    overdue = open_old | review_old | awaiting_old
    critical = Q(updated_at__lte=now - timedelta(hours=48)) | Q(
        status=PublishingReviewCase.Status.OPEN,
        updated_at__lte=now - timedelta(hours=24),
    )

    source = PublishingReviewCase.objects.filter(
        pipeline_id=pipeline_id, status__in=PENDING,
    )
    summary = source.aggregate(
        total=Count('pk'),
        unassigned=Count('pk', filter=Q(assigned_to__isnull=True)),
        awaiting_verification=Count('pk', filter=Q(status=PublishingReviewCase.Status.AWAITING)),
        overdue=Count('pk', filter=overdue),
        critical=Count('pk', filter=critical),
        terminal_not_closed=Count('pk', filter=(
            Q(job__state=PublishingJob.State.FAILED)
            | Q(job__state=PublishingJob.State.CANCELLED)
            | (Q(job__state=PublishingJob.State.PUBLISHED) & ~Q(job__external_post_id=''))
        )),
    )

    qs = source.annotate(priority=Case(
        When(critical, then=Value(2)),
        When(overdue, then=Value(1)),
        default=Value(0), output_field=IntegerField(),
    ))
    if filter_by == 'overdue':
        qs = qs.filter(overdue)
    elif filter_by == 'critical':
        qs = qs.filter(critical)
    elif filter_by == 'awaiting':
        qs = qs.filter(status=PublishingReviewCase.Status.AWAITING)

    queryset = qs.select_related('job', 'job__facebook_account',
                                  'job__facebook_group', 'assigned_to').annotate(
        evidence_count=Count('events', filter=Q(events__kind=PublishingReviewEvent.Kind.EVIDENCE)),
    ).order_by('-priority', 'updated_at', 'pk')
    pages = Paginator(queryset, page_size)
    current = pages.get_page(page)
    if current.number != page:
        raise SLAQueryError('Trang không tồn tại.')

    items = []
    for case in current.object_list:
        job = case.job
        idle_minutes = max(0, int((now - case.updated_at).total_seconds() // 60))
        age_minutes = max(0, int((now - case.created_at).total_seconds() // 60))
        has_verified_post = job.state == PublishingJob.State.PUBLISHED and bool(job.external_post_id)
        terminal = job.state in (PublishingJob.State.FAILED, PublishingJob.State.CANCELLED) or has_verified_post
        has_evidence = case.evidence_count > 0
        if terminal:
            next_action = 'close_after_review' if has_evidence else 'document_terminal_evidence'
        elif case.assigned_to_id is None:
            next_action = 'assign_owner'
        elif not has_evidence:
            next_action = 'collect_evidence'
        elif case.status == PublishingReviewCase.Status.AWAITING:
            next_action = 'await_independent_verification'
        else:
            next_action = 'request_independent_verification'
        items.append({
            'case_id': str(case.pk), 'job_id': str(case.job_id),
            'case_status': case.status, 'job_state': job.state,
            'account': {'id': str(job.facebook_account_id), 'label': job.facebook_account.label},
            'group': {'id': str(job.facebook_group_id), 'name': job.facebook_group.name},
            'assigned_to': case.assigned_to.username if case.assigned_to_id else None,
            'age_minutes': age_minutes, 'idle_minutes': idle_minutes,
            'severity': 'critical' if case.priority == 2 else 'warning' if case.priority == 1 else 'normal',
            'evidence_count': case.evidence_count,
            'external_post_verified': has_verified_post,
            'next_action': next_action,
            'updated_at': case.updated_at.isoformat(),
        })
    return {
        'pipeline_id': str(pipeline_id),
        'summary': summary,
        'items': items,
        'pagination': {
            'page': current.number, 'page_size': page_size,
            'total': pages.count, 'total_pages': pages.num_pages,
            'has_next': current.has_next(), 'has_previous': current.has_previous(),
        },
        'threshold_hours': {'open': 2, 'in_review': 6, 'awaiting_verification': 24, 'critical': 48},
        'read_only': True,
        'auto_resolution_enabled': False,
        'facebook_verification_enabled': False,
    }
