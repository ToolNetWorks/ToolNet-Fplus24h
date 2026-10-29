"""9.7.17: read-only readiness and pilot evidence, scoped to ONE Pipeline.

No Facebook I/O, no HAR replay, no cookie material, no state changes. A manual
handoff report is not independent proof of public publication.
"""
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q

from modules.pipelines.models import Pipeline
from modules.publishing.models import (
    PublishingJob, PipelineMediaPolicy, PipelineAlbumSource,
)
from modules.publishing.scheduler_models import AccountGroupEligibility, AccountProxyPin
from modules.publishing.manual_handoff_models import ManualPublishingHandoff
from modules.publishing.verification_models import TrustedPostVerification
from modules.publishing.readback_models import PostSubmissionReference, PostReadbackAudit
from modules.proxies.models import ProxyEndpoint
from modules.albums.models import AlbumImage


class PilotReadinessError(ValueError):
    pass


def _verified_publication(job, receipts, references, verified_readbacks):
    receipt = receipts.get(job.pk)
    reference = references.get(job.pk)
    return bool(
        job.state == PublishingJob.State.PUBLISHED
        and job.external_post_id
        and receipt and reference
        and receipt.external_post_id == reference.external_post_id == job.external_post_id
        and reference.account_id_snapshot == job.facebook_account_id
        and reference.group_id_snapshot == job.facebook_group_id
        and job.pk in verified_readbacks
    )


def pilot_readiness_snapshot(*, pipeline_id, limit=50, now=None):
    """Bounded, read-only pilot review: no provider/worker status implied.

    Output contains labels and IDs needed to locate failures. It NEVER includes
    proxy IP, hostname, credentials, post content, tokens or media object keys.
    A partially scanned Pipeline can NEVER be marked pilot-ready.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise PilotReadinessError('limit phải từ 1 đến 100.')
    now = timezone.now() if now is None else now
    if timezone.is_naive(now):
        raise PilotReadinessError('now cần có múi giờ.')
    pipeline = Pipeline.objects.filter(pk=pipeline_id).values('id', 'status').first()
    if pipeline is None:
        raise PilotReadinessError('Pipeline không tồn tại.')

    base = PublishingJob.objects.filter(pipeline_id=pipeline_id)
    total = base.count()
    jobs = list(base.select_related('facebook_account', 'facebook_group', 'media_allocation')
                .order_by('-scheduled_at', '-pk')[:limit + 1])
    truncated = len(jobs) > limit
    jobs = jobs[:limit]
    account_ids = {job.facebook_account_id for job in jobs}
    group_ids = {job.facebook_group_id for job in jobs}
    job_ids = [job.pk for job in jobs]
    proxies = {row.account_id: row for row in ProxyEndpoint.objects.filter(
        pipeline_id=pipeline_id, account_id__in=account_ids)}
    pins = {row.account_id: row for row in AccountProxyPin.objects.filter(
        pipeline_id=pipeline_id, account_id__in=account_ids)}
    pairs = {(row.account_id, row.group_id): row for row in AccountGroupEligibility.objects.filter(
        pipeline_id=pipeline_id, account_id__in=account_ids, group_id__in=group_ids)}
    # Account/Group holds are checked against OTHER jobs, not a prepared handoff itself.
    holds = list(PublishingJob.objects.filter(pipeline_id=pipeline_id).filter(
        Q(state__in=[PublishingJob.State.CLAIMED, PublishingJob.State.READY,
                     PublishingJob.State.DISPATCHING, PublishingJob.State.UNCERTAIN])
        | Q(state=PublishingJob.State.PUBLISHED, external_post_id='')
        | Q(state=PublishingJob.State.QUEUED, manual_handoff__state='prepared')
    ).values_list('id', 'facebook_account_id', 'facebook_group_id'))
    handoffs = {row.job_id: row for row in ManualPublishingHandoff.objects.filter(
        pipeline_id=pipeline_id, job_id__in=job_ids)}
    receipts = {row.job_id: row for row in TrustedPostVerification.objects.filter(
        pipeline_id=pipeline_id, job_id__in=job_ids)}
    references = {row.job_id: row for row in PostSubmissionReference.objects.filter(
        pipeline_id=pipeline_id, job_id__in=job_ids)}
    verified_readbacks = set(PostReadbackAudit.objects.filter(
        pipeline_id=pipeline_id, job_id__in=job_ids,
        outcome=PostReadbackAudit.Outcome.VERIFIED,
    ).values_list('job_id', flat=True))
    media_policy = PipelineMediaPolicy.objects.filter(pipeline_id=pipeline_id, is_enabled=True).first()
    album_ids = list(PipelineAlbumSource.objects.filter(
        pipeline_id=pipeline_id, is_enabled=True, album__is_enabled=True,
    ).values_list('album_id', flat=True))
    available_images = AlbumImage.objects.filter(
        album_id__in=album_ids, album__pipeline_id=pipeline_id,
        upload_status=AlbumImage.UploadStatus.READY,
    ).count() if album_ids else 0

    rows = []
    counts = {'ready': 0, 'blocked': 0, 'awaiting_review': 0, 'verified': 0, 'closed': 0}
    for job in jobs:
        blockers = []
        handoff = handoffs.get(job.pk)
        if job.state == PublishingJob.State.PUBLISHED:
            stage = 'verified' if _verified_publication(job, receipts, references, verified_readbacks) else 'blocked'
            if stage == 'blocked':
                blockers.append('PUBLISHED_WITHOUT_TRUST_CHAIN')
        elif job.state in (PublishingJob.State.FAILED, PublishingJob.State.CANCELLED):
            stage = 'closed'
        elif handoff and handoff.state not in (
            ManualPublishingHandoff.State.PREPARED, ManualPublishingHandoff.State.ABANDONED,
        ):
            stage = 'awaiting_review'
        elif job.state in (
            PublishingJob.State.UNCERTAIN, PublishingJob.State.DISPATCHING,
            PublishingJob.State.CLAIMED, PublishingJob.State.READY,
        ):
            stage = 'awaiting_review'
        elif job.state != PublishingJob.State.QUEUED:
            stage = 'blocked'
            blockers.append('UNSUPPORTED_JOB_STATE')
        else:
            if pipeline['status'] != Pipeline.Status.ACTIVE:
                blockers.append('PIPELINE_INACTIVE')
            if job.attempt_count != 0:
                blockers.append('PREVIOUS_ATTEMPT_EXISTS')
            if job.next_run_at > now:
                blockers.append('NOT_DUE')
            if any(other_id != job.pk and (account_id == job.facebook_account_id
                   or group_id == job.facebook_group_id)
                   for other_id, account_id, group_id in holds):
                blockers.append('ACCOUNT_OR_GROUP_HAS_HELD_JOB')
            if job.facebook_account.connection_status != 'connected':
                blockers.append('ACCOUNT_NOT_CONNECTED')
            if not job.facebook_group.is_enabled:
                blockers.append('GROUP_DISABLED')
            eligibility = pairs.get((job.facebook_account_id, job.facebook_group_id))
            if not eligibility or not (
                eligibility.state == AccountGroupEligibility.State.VERIFIED
                and eligibility.can_post_anonymous
                and eligibility.evidence_note.strip()
                and eligibility.verified_at and eligibility.verified_at <= now
                and eligibility.expires_at and eligibility.expires_at > now
            ):
                blockers.append('ANONYMOUS_ELIGIBILITY_UNVERIFIED')
            proxy = proxies.get(job.facebook_account_id)
            pin = pins.get(job.facebook_account_id)
            if not proxy or not (
                proxy.is_enabled and proxy.health_status == ProxyEndpoint.HealthStatus.HEALTHY
                and proxy.exit_ip and proxy.last_checked_at
                and now - timedelta(hours=24) <= proxy.last_checked_at <= now
            ):
                blockers.append('PROXY_UNHEALTHY_OR_STALE')
            if not proxy or not pin or pin.proxy_id != proxy.pk or pin.pinned_exit_ip != proxy.exit_ip:
                blockers.append('PROXY_PIN_MISSING_OR_MISMATCH')
            if not media_policy or not album_ids or available_images < (media_policy.images_per_post if media_policy else 1):
                blockers.append('MEDIA_SOURCE_NOT_READY')
            if handoff and handoff.state == ManualPublishingHandoff.State.PREPARED:
                if not job.media_allocation_id or job.media_allocation.state != 'reserved':
                    blockers.append('PREPARED_MEDIA_INCONSISTENT')
                stage = 'blocked' if blockers else 'ready'
            elif handoff:
                stage = 'closed' if handoff.state == ManualPublishingHandoff.State.ABANDONED else 'blocked'
                if stage == 'blocked':
                    blockers.append('HANDOFF_CONFLICT')
            else:
                stage = 'blocked' if blockers else 'ready'
        counts[stage] += 1
        rows.append({
            'job_id': str(job.pk), 'account': job.facebook_account.label,
            'group': job.facebook_group.name, 'job_state': job.state,
            'handoff_state': handoff.state if handoff else None,
            'stage': stage, 'blockers': blockers,
            'scheduled_at': job.scheduled_at.isoformat(),
            'verified_publication': stage == 'verified',
        })

    if truncated:
        status = 'incomplete'
    elif total == 0:
        status = 'not_configured'
    elif counts['blocked']:
        status = 'blocked'
    elif counts['awaiting_review']:
        status = 'awaiting_review'
    elif counts['ready']:
        status = 'ready_for_manual_pilot'
    elif counts['verified'] and not counts['closed']:
        status = 'verified_records_only'
    else:
        status = 'no_active_jobs'
    return {
        'pipeline_id': str(pipeline_id), 'checked_at': now.isoformat(),
        'status': status, 'total_jobs': total,
        'scanned_jobs': len(jobs), 'truncated': truncated,
        'summary': counts, 'items': rows,
        'read_only': True, 'automatic_facebook_posting': False,
        'no_real_publication_test_performed': True,
        'note': 'Đây là kiểm tra điều kiện và lịch sử nội bộ, không chứng minh bài Facebook hiển thị.',
    }
