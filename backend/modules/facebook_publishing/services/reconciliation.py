"""Result reconciliation for the Facebook Publishing Worker.

Cross-checks WorkerPublishJob state against the authoritative PublishingJob state
and handles uncertain results with careful reconciliation logic.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from modules.publishing.models import PublishingJob
from modules.facebook_publishing.models import (
    WorkerPublishJob, WorkerResultState,
)
from modules.facebook_publishing.services.audit_log import AuditLogger

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    worker_state: str
    publishing_job_state: str
    action: str
    detail: str


class ReconciliationError(Exception):
    pass


def reconcile_job_states(
    *, pipeline_id, job_id, worker_job: WorkerPublishJob,
    audit: Optional[AuditLogger] = None,
) -> ReconciliationResult:
    """Cross-check WorkerPublishJob state against PublishingJob state.

    Ensures the Worker's internal state is consistent with the authoritative
    job engine state before any transition is applied.
    """
    try:
        publishing_job = PublishingJob.objects.get(
            pk=job_id, pipeline_id=pipeline_id,
        )
    except PublishingJob.DoesNotExist:
        raise ReconciliationError(
            f'PublishingJob {job_id} not found in Pipeline {pipeline_id}.'
        )

    worker_state = worker_job.state
    pub_state = publishing_job.state

    if worker_state == WorkerResultState.PUBLISHED:
        if pub_state == PublishingJob.State.PUBLISHED:
            action = 'confirm_consistent'
            detail = 'Both Worker and Job Engine report PUBLISHED.'
        elif pub_state in (PublishingJob.State.UNCERTAIN,
                           PublishingJob.State.DISPATCHING):
            action = 'awaiting_job_engine_confirmation'
            detail = 'Worker PUBLISHED but Job Engine state is uncertain; manual review needed.'
        else:
            action = 'inconsistent_published'
            detail = f'Worker reports PUBLISHED but Job Engine is {pub_state}.'
    elif worker_state == WorkerResultState.SUBMITTED_UNVERIFIED:
        if pub_state == PublishingJob.State.DISPATCHING:
            action = 'consistent_submitted'
            detail = 'Worker submitted, Job Engine dispatching — awaiting verification.'
        else:
            action = 'transition_to_uncertain'
            detail = f'Worker SUBMITTED_UNVERIFIED but Job Engine is {pub_state}.'
    elif worker_state == WorkerResultState.PENDING_APPROVAL:
        if pub_state in (PublishingJob.State.DISPATCHING,
                         PublishingJob.State.UNCERTAIN):
            action = 'awaiting_admin_approval'
            detail = 'Post requires admin approval; Job Engine should be UNCERTAIN.'
        else:
            action = 'state_mismatch'
            detail = f'Worker PENDING_APPROVAL but Job Engine is {pub_state}.'
    elif worker_state == WorkerResultState.UNCERTAIN:
        if pub_state in (PublishingJob.State.UNCERTAIN,
                         PublishingJob.State.DISPATCHING):
            action = 'consistent_uncertain'
            detail = 'Worker and Job Engine both uncertain; do not auto-resend.'
        else:
            action = 'transition_to_uncertain'
            detail = f'Worker UNCERTAIN but Job Engine is {pub_state}; will transition.'
    elif worker_state == WorkerResultState.REJECTED:
        action = 'record_rejection'
        detail = 'Post was rejected; no retry.'
    elif worker_state == WorkerResultState.FAILED:
        action = 'record_failure'
        detail = 'Worker failed to publish.'
    else:
        action = 'no_action'
        detail = f'Worker state {worker_state}, Job Engine state {pub_state}.'

    if audit:
        audit.log_event(
            'reconciliation_result',
            worker_state=worker_state,
            publishing_job_state=pub_state,
            action=action,
            detail=detail,
        )

    return ReconciliationResult(
        worker_state=worker_state,
        publishing_job_state=pub_state,
        action=action,
        detail=detail,
    )


def safe_transition_to_uncertain(
    *, pipeline_id, job_id, worker_job: WorkerPublishJob,
    claim_token: str, error_code: str, audit: Optional[AuditLogger] = None,
):
    """Transition a WorkerPublishJob and PublishingJob to UNCERTAIN.

    Never auto-resends. Uses the job_engine's flag_uncertain for the authoritative
    state transition.
    """
    result = reconcile_job_states(
        pipeline_id=pipeline_id, job_id=job_id,
        worker_job=worker_job, audit=audit,
    )

    from modules.publishing.services.job_engine import flag_uncertain, JobEngineError, JobConflict

    try:
        flag_uncertain(
            pipeline_id=pipeline_id, job_id=job_id,
            code=error_code,
        )
        if audit:
            audit.log_transition(
                from_state=result.worker_state,
                to_state=WorkerResultState.UNCERTAIN,
                error_code=error_code,
            )
        worker_job.state = WorkerResultState.UNCERTAIN
        worker_job.error_code = error_code
        worker_job.finalized_at = worker_job.finalized_at if worker_job.finalized_at else None
        from django.utils import timezone
        worker_job.finalized_at = timezone.now()
        worker_job.save(update_fields=['state', 'error_code', 'finalized_at'])
    except (JobEngineError, JobConflict) as exc:
        if audit:
            audit.log_error(
                'reconciliation_failed',
                f'Could not flag job as uncertain: {exc}',
                error_code=error_code,
            )
        raise ReconciliationError(
            f'Could not transition to UNCERTAIN: {exc}'
        ) from exc

    return result
