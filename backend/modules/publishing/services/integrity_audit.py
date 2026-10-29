"""Read-only, bounded Pipeline integrity audit (Step 9.7.11).

No Facebook/network calls, no HAR/cookies/tokens, no Job state transitions.
The scan is deliberately bounded; incomplete scans never report a clean PASS.
This is an operational consistency check, not proof that Facebook content is public.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob, PublishingAttempt, MediaAllocation
from modules.publishing.review_models import PublishingReviewCase
from modules.publishing.scheduler_models import (
    AccountProxyPin, PipelineSchedule, ScheduledBatch, ScheduledAssignment,
)
from modules.publishing.verification_models import TrustedPostVerification
from modules.publishing.readback_models import PostSubmissionReference, PostReadbackAudit

MAX_SAMPLE_LIMIT = 1000


class IntegrityAuditError(ValueError):
    pass


def integrity_snapshot(*, pipeline_id, sample_limit=250, now=None):
    """Return safe metadata and detected invariants for ONE Pipeline only.

    Querysets are scoped by pipeline_id, with explicit checks for cross-tenant
    foreign-key inconsistencies inside sampled records. ``complete`` is False
    if any examined category exceeds the bounded limit. NEVER treat partial
    data as zero anomalies or as complete health verification.
    """
    if type(sample_limit) is not int or not 1 <= sample_limit <= MAX_SAMPLE_LIMIT:
        raise IntegrityAuditError('sample_limit phải trong khoảng 1..1000.')
    now = timezone.now() if now is None else now
    if timezone.is_naive(now):
        raise IntegrityAuditError('now phải có múi giờ.')
    if not Pipeline.objects.filter(pk=pipeline_id).exists():
        raise IntegrityAuditError('Pipeline không tồn tại.')

    errors = []
    scanned = {}
    truncated = []

    def sample(name, queryset):
        rows = list(queryset.order_by('pk')[:sample_limit + 1])
        scanned[name] = min(len(rows), sample_limit)
        if len(rows) > sample_limit:
            truncated.append(name)
        return rows[:sample_limit]

    def issue(code, kind, obj, severity='critical'):
        errors.append({
            'code': code, 'severity': severity,
            'object_type': kind, 'object_id': str(obj.pk),
        })

    jobs = PublishingJob.objects.filter(pipeline_id=pipeline_id)
    job_counts = jobs.aggregate(
        total=Count('pk'),
        queued=Count('pk', filter=Q(state=PublishingJob.State.QUEUED)),
        uncertain=Count('pk', filter=Q(state=PublishingJob.State.UNCERTAIN)),
        published=Count('pk', filter=Q(state=PublishingJob.State.PUBLISHED)),
        failed=Count('pk', filter=Q(state=PublishingJob.State.FAILED)),
    )
    sampled_jobs = sample('jobs', jobs.select_related(
        'facebook_account', 'facebook_group', 'media_allocation',
    ))
    published_ids = [job.pk for job in sampled_jobs
                     if job.state == PublishingJob.State.PUBLISHED]
    receipts_by_job = {
        receipt.job_id: receipt
        for receipt in TrustedPostVerification.objects.filter(
            pipeline_id=pipeline_id, job_id__in=published_ids,
        )
    }
    submissions_by_job = {
        ref.job_id: ref
        for ref in PostSubmissionReference.objects.filter(
            pipeline_id=pipeline_id, job_id__in=published_ids,
        )
    }
    readback_verified_ids = set(PostReadbackAudit.objects.filter(
        pipeline_id=pipeline_id, job_id__in=published_ids,
        outcome=PostReadbackAudit.Outcome.VERIFIED,
    ).values_list('job_id', flat=True))
    for job in sampled_jobs:
        if (job.facebook_account.pipeline_id != pipeline_id
                or job.facebook_group.pipeline_id != pipeline_id
                or (job.media_allocation_id
                    and job.media_allocation.pipeline_id != pipeline_id)):
            issue('JOB_FOREIGN_RESOURCE', 'job', job)
        if job.state == PublishingJob.State.PUBLISHED:
            if not job.external_post_id:
                issue('PUBLISHED_WITHOUT_POST_ID', 'job', job)
            if job.attempt_count < 1:
                issue('PUBLISHED_MISSING_ATTEMPT', 'job', job)
            if not job.finalized_at:
                issue('PUBLISHED_WITHOUT_FINAL_TIME', 'job', job)
            if not job.media_allocation_id or job.media_allocation.state != MediaAllocation.State.CONSUMED:
                issue('PUBLISHED_MEDIA_NOT_CONSUMED', 'job', job)
            # A historical published Job might predate trusted readback; this
            # is still an audit finding, not an instruction to rewrite it.
            receipt = receipts_by_job.get(job.pk)
            ref = submissions_by_job.get(job.pk)
            if receipt is None or ref is None:
                issue('PUBLISHED_WITHOUT_TRUST_CHAIN', 'job', job)
            elif (receipt.external_post_id != job.external_post_id
                  or ref.external_post_id != job.external_post_id
                  or ref.account_id_snapshot != job.facebook_account_id
                  or ref.group_id_snapshot != job.facebook_group_id):
                issue('PUBLISHED_TRUST_CHAIN_MISMATCH', 'job', job)
            if job.pk not in readback_verified_ids:
                issue('PUBLISHED_WITHOUT_VERIFIED_READBACK', 'job', job)
        elif job.state in (PublishingJob.State.CLAIMED, PublishingJob.State.READY):
            if job.lease_expires_at and job.lease_expires_at < now:
                issue('EXPIRED_LEASE_NOT_QUARANTINED', 'job', job, 'warning')
        elif job.state in (PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN):
            if job.media_allocation_id and job.media_allocation.state == MediaAllocation.State.CONSUMED:
                issue('UNVERIFIED_MEDIA_ALREADY_CONSUMED', 'job', job)
            if (job.state == PublishingJob.State.UNCERTAIN
                    and job.updated_at < now - timedelta(hours=48)):
                issue('UNRESOLVED_JOB_OVER_48H', 'job', job, 'warning')

    for attempt in sample('attempts', PublishingAttempt.objects.filter(
        job__pipeline_id=pipeline_id,
    ).select_related('job', 'media_allocation')):
        if (attempt.job.pipeline_id != pipeline_id
                or (attempt.media_allocation_id
                    and attempt.media_allocation.pipeline_id != pipeline_id)):
            issue('ATTEMPT_FOREIGN_RESOURCE', 'attempt', attempt)
        if (attempt.job.state == PublishingJob.State.PUBLISHED
                and attempt.number == attempt.job.attempt_count
                and attempt.state != PublishingAttempt.State.PUBLISHED):
            issue('PUBLISHED_ATTEMPT_NOT_FINAL', 'attempt', attempt)

    for batch in sample('batches', ScheduledBatch.objects.filter(
        pipeline_id=pipeline_id,
    ).select_related('schedule').annotate(actual_count=Count('assignments'))):
        if batch.schedule.pipeline_id != pipeline_id:
            issue('BATCH_FOREIGN_SCHEDULE', 'batch', batch)
        if batch.assigned_count != batch.actual_count:
            issue('BATCH_ASSIGNMENT_COUNT_MISMATCH', 'batch', batch)

    for assignment in sample('assignments', ScheduledAssignment.objects.filter(
        batch__pipeline_id=pipeline_id,
    ).select_related('batch', 'job', 'account', 'group', 'proxy')):
        if any(x != pipeline_id for x in (
            assignment.batch.pipeline_id, assignment.job.pipeline_id,
            assignment.account.pipeline_id, assignment.group.pipeline_id,
            assignment.proxy.pipeline_id,
        )):
            issue('ASSIGNMENT_FOREIGN_RESOURCE', 'assignment', assignment)
        if (assignment.job.facebook_account_id != assignment.account_id
                or assignment.job.facebook_group_id != assignment.group_id):
            issue('ASSIGNMENT_JOB_IDENTITY_MISMATCH', 'assignment', assignment)
        if assignment.proxy.account_id != assignment.account_id:
            issue('ASSIGNMENT_PROXY_ACCOUNT_MISMATCH', 'assignment', assignment)

    for reference in sample('submissions', PostSubmissionReference.objects.filter(
        pipeline_id=pipeline_id,
    ).select_related('job')):
        if (reference.job.pipeline_id != pipeline_id
                or reference.account_id_snapshot != reference.job.facebook_account_id
                or reference.group_id_snapshot != reference.job.facebook_group_id):
            issue('SUBMISSION_JOB_IDENTITY_MISMATCH', 'submission', reference)

    for receipt in sample('receipts', TrustedPostVerification.objects.filter(
        pipeline_id=pipeline_id,
    ).select_related('job')):
        if (receipt.job.pipeline_id != pipeline_id
                or receipt.job.state != PublishingJob.State.PUBLISHED
                or receipt.job.external_post_id != receipt.external_post_id):
            issue('RECEIPT_JOB_MISMATCH', 'receipt', receipt)

    for case in sample('review_cases', PublishingReviewCase.objects.filter(
        pipeline_id=pipeline_id,
    ).select_related('job')):
        if case.job.pipeline_id != pipeline_id:
            issue('CASE_FOREIGN_JOB', 'review_case', case)
        if case.status == PublishingReviewCase.Status.CLOSED and (
            case.job.state not in (PublishingJob.State.FAILED, PublishingJob.State.CANCELLED,
                                    PublishingJob.State.PUBLISHED)
            or (case.job.state == PublishingJob.State.PUBLISHED and not case.job.external_post_id)
        ):
            issue('CLOSED_CASE_WITH_UNRESOLVED_JOB', 'review_case', case)

    for pin in sample('proxy_pins', AccountProxyPin.objects.filter(
        pipeline_id=pipeline_id,
    ).select_related('account', 'proxy')):
        if (pin.account.pipeline_id != pipeline_id or pin.proxy.pipeline_id != pipeline_id
                or pin.proxy.account_id != pin.account_id):
            issue('PROXY_PIN_FOREIGN_RESOURCE', 'proxy_pin', pin)
        if pin.proxy.exit_ip != pin.pinned_exit_ip:
            issue('PROXY_EXIT_IP_CHANGED', 'proxy_pin', pin, 'warning')

    for schedule in sample('schedules', PipelineSchedule.objects.filter(
        pipeline_id=pipeline_id, enabled=True,
    )):
        if schedule.next_run_at < now - timedelta(minutes=2 * schedule.interval_minutes):
            issue('SCHEDULER_OVERDUE', 'schedule', schedule, 'warning')

    # Include independent audit rows as a scan category; the ledger must be
    # consistent even if no Job is currently in the sample window.
    for check in sample('readbacks', PostReadbackAudit.objects.filter(
        pipeline_id=pipeline_id,
    ).select_related('job')):
        if check.job.pipeline_id != pipeline_id:
            issue('READBACK_FOREIGN_JOB', 'readback', check)

    severity = {
        'critical': sum(x['severity'] == 'critical' for x in errors),
        'warning': sum(x['severity'] == 'warning' for x in errors),
    }
    complete = len(truncated) == 0
    return {
        'pipeline_id': str(pipeline_id),
        'status': ('incomplete' if not complete else
                   'attention_required' if errors else 'consistent'),
        'complete': complete,
        'summary': {
            **job_counts,
            'critical': severity['critical'], 'warnings': severity['warning'],
            'findings_in_sample': len(errors),
        },
        'findings': errors,
        'scanned': scanned,
        'truncated_categories': truncated,
        'sample_limit_per_category': sample_limit,
        'read_only': True,
        'facebook_publication_verified_by_audit': False,
        'note': 'Kiểm toán chỉ kiểm tra nhất quán nội bộ, không đọc trạng thái bài đăng Facebook.',
    }
