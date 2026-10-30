"""Live runtime verification for automatic Scheduler + AI Caption operation.

Creates an ISOLATED test Pipeline (never production), with its own CTV, account,
group, proxy, eligibility, schedule and caption settings (auto_generate=True,
auto_approve=True). It then waits for the LIVE systemd services to act:

  toolnet-scheduler-tick.service  -> creates the QUEUED Job
  toolnet-caption-tick.service    -> calls the real AI provider, auto-approves
  toolnet-recovery-tick.timer     -> quarantines an expired worker lease

No Facebook posting occurs: the only adapter is fail-closed. Fixtures are
removed at the end unless --keep is passed, so no recurring test Jobs remain.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint
from modules.publishing.caption_models import (
    CaptionRevision, CaptionSample, JobCaption, PipelineCaptionSettings,
    CaptionSettingsEvent,
)
from modules.publishing.models import (
    PublishingAlertScan, PublishingAttempt, PublishingJob,
)
from modules.publishing.alert_models import PublishingAlertEvent, PublishingAlertIncident
from modules.publishing.services.caption_engine import (
    create_sample, ready_for_dispatch, update_settings,
)
from modules.publishing.adapters.facebook_groups import (
    FacebookGroupPublishingAdapter, GroupsApiUnavailable,
)
from modules.publishing.manual_handoff_models import (
    ManualPublishingEvent, ManualPublishingHandoff,
)
from modules.publishing.review_models import PublishingReviewCase, PublishingReviewEvent
from modules.publishing.scheduler_models import (
    AccountGroupEligibility, AccountProxyPin, GroupHealth, PipelineSchedule,
    ScheduledAssignment, ScheduledBatch,
)
from modules.publishing.scheduler_tick_models import SchedulerTickAudit
from modules.publishing.services.job_engine import claim_due_job
from modules.publishing.worker_models import WorkerLeaseEvent

User = get_user_model()


@transaction.atomic
def setup_fixtures():
    admin = User.objects.filter(is_superuser=True, is_staff=True).first()
    assert admin, 'Admin account required.'
    now = timezone.now()
    suffix = uuid.uuid4().hex[:8]
    ctv = User.objects.create_user(
        username=f'runtime_ctv_{suffix}', password=uuid.uuid4().hex)
    pipeline = Pipeline.objects.create(
        name=f'Runtime Verify {suffix}', ctv=ctv,
        status=Pipeline.Status.ACTIVE)
    account = FacebookAccount.objects.create(
        pipeline=pipeline, label=f'Runtime Acc {suffix}',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED)
    group = FacebookGroup.objects.create(
        pipeline=pipeline, name=f'Runtime Group {suffix}',
        group_url=f'https://www.facebook.com/groups/runtime_verify_{suffix}/')
    proxy = ProxyEndpoint.objects.create(
        pipeline=pipeline, account=account, protocol=ProxyEndpoint.Protocol.HTTP,
        host='proxy.runtime-verify.example', port=8080, is_enabled=True,
        health_status=ProxyEndpoint.HealthStatus.HEALTHY,
        exit_ip='203.0.113.10', last_checked_at=now)
    eligibility = AccountGroupEligibility.objects.create(
        pipeline=pipeline, account=account, group=group,
        state=AccountGroupEligibility.State.VERIFIED,
        can_post_anonymous=True, can_post_nonmember=True,
        verified_at=now - timedelta(hours=1), expires_at=now + timedelta(days=7),
        evidence_note='Isolated runtime verification fixture; not production.')
    schedule = PipelineSchedule.objects.create(
        pipeline=pipeline, name='Runtime schedule', enabled=True,
        interval_minutes=60, max_groups_per_run=1, timezone_name='Asia/Ho_Chi_Minh',
        start_at=now - timedelta(days=1), next_run_at=now - timedelta(seconds=60),
        caption_template='Nội dung theo lịch cho {group_name} ngày {date}.',
        require_anonymous=True, require_nonmember=True)
    update_settings(
        pipeline_id=pipeline.pk, actor=admin, destination='@runtime_verify',
        enabled=True, auto_generate=True, auto_approve=True,
        writing_guidance='Caption ngắn gọn, tích cực, tự nhiên.')
    for index in range(5):
        create_sample(
            pipeline_id=pipeline.pk, actor=ctv,
            text=f'Caption mẫu {index + 1}: năng lượng tích cực mỗi ngày, '
                 f'chia sẻ cơ hội hợp tác minh bạch.')
    return {
        'pipeline_id': str(pipeline.pk),
        'ctv_id': str(ctv.pk),
        'account_id': str(account.pk),
        'group_id': str(group.pk),
        'proxy_id': str(proxy.pk),
        'eligibility_id': str(eligibility.pk),
        'schedule_id': str(schedule.pk),
        'started_at': now.isoformat(),
    }


def wait_for_auto_caption(pipeline_id, timeout_seconds):
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        job = (PublishingJob.objects.filter(pipeline_id=pipeline_id)
               .order_by('created_at', 'pk').first())
        if job:
            job.refresh_from_db()
            caption = JobCaption.objects.filter(job_id=job.pk).first()
            last = {
                'job_id': str(job.pk),
                'job_state': job.state,
                'caption_state': caption.state if caption else None,
            }
            if caption and caption.state == JobCaption.State.APPROVED:
                return job, caption, last
        time.sleep(10)
    raise RuntimeError('Timed out waiting for automatic caption: ' + json.dumps(last))


def journal_lines(unit, since_iso, pipeline_id):
    try:
        raw = subprocess.run(
            ['journalctl', '-u', unit, '--since', since_iso,
             '--no-pager', '-o', 'cat'],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception as exc:
        return [f'journalctl error: {exc.__class__.__name__}']
    return [line for line in raw.splitlines() if pipeline_id in line][-5:]


def cleanup_fixtures(pipeline_id):
    pipeline = Pipeline.objects.filter(pk=pipeline_id).first()
    if pipeline is None:
        return {'already_absent': True}
    job_ids = list(PublishingJob.objects.filter(pipeline=pipeline)
                   .values_list('pk', flat=True))
    counts = {
        'jobs': len(job_ids),
        'captions': JobCaption.objects.filter(pipeline=pipeline).count(),
        'revisions': CaptionRevision.objects.filter(job_caption__pipeline=pipeline).count(),
        'schedules': PipelineSchedule.objects.filter(pipeline=pipeline).count(),
        'batches': ScheduledBatch.objects.filter(pipeline=pipeline).count(),
        'assignments': ScheduledAssignment.objects.filter(batch__pipeline=pipeline).count(),
        'ticks': SchedulerTickAudit.objects.filter(pipeline=pipeline).count(),
    }
    PublishingAlertEvent.objects.filter(incident__pipeline=pipeline).delete()
    PublishingAlertIncident.objects.filter(pipeline=pipeline).delete()
    PublishingAlertScan.objects.filter(pipeline=pipeline).delete()
    SchedulerTickAudit.objects.filter(pipeline=pipeline).delete()
    PublishingReviewEvent.objects.filter(case__pipeline=pipeline).delete()
    PublishingReviewCase.objects.filter(pipeline=pipeline).delete()
    ManualPublishingEvent.objects.filter(handoff__pipeline=pipeline).delete()
    ManualPublishingHandoff.objects.filter(pipeline=pipeline).delete()
    WorkerLeaseEvent.objects.filter(pipeline=pipeline).delete()
    CaptionRevision.objects.filter(job_caption__pipeline=pipeline).delete()
    JobCaption.objects.filter(pipeline=pipeline).delete()
    ScheduledAssignment.objects.filter(batch__pipeline=pipeline).delete()
    ScheduledBatch.objects.filter(pipeline=pipeline).delete()
    PublishingAttempt.objects.filter(job__pipeline=pipeline).delete()
    PublishingJob.objects.filter(pipeline=pipeline).delete()
    AccountProxyPin.objects.filter(pipeline=pipeline).delete()
    GroupHealth.objects.filter(pipeline=pipeline).delete()
    AccountGroupEligibility.objects.filter(pipeline=pipeline).delete()
    PipelineSchedule.objects.filter(pipeline=pipeline).delete()
    ProxyEndpoint.objects.filter(pipeline=pipeline).delete()
    CaptionSettingsEvent.objects.filter(pipeline=pipeline).delete()
    CaptionSample.objects.filter(pipeline=pipeline).delete()
    PipelineCaptionSettings.objects.filter(pipeline=pipeline).delete()
    FacebookGroup.objects.filter(pipeline=pipeline).delete()
    FacebookAccount.objects.filter(pipeline=pipeline).delete()
    ctv = pipeline.ctv
    pipeline.delete()
    ctv.delete()
    counts['remaining_jobs'] = PublishingJob.objects.filter(
        pipeline_id=pipeline_id).count()
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=360)
    parser.add_argument('--keep', action='store_true')
    opts = parser.parse_args()

    evidence = {'fixtures': setup_fixtures()}
    pipeline_id = evidence['fixtures']['pipeline_id']
    try:
        job, caption, last = wait_for_auto_caption(pipeline_id, opts.timeout)
        evidence['wait_last'] = last
        evidence['job'] = {
            'id': str(job.pk),
            'state': job.state,
            'caption': job.caption,
            'attempt_count': job.attempt_count,
            'external_post_id': job.external_post_id,
            'scheduled_at': job.scheduled_at.isoformat(),
            'updated_at': job.updated_at.isoformat(),
        }
        evidence['caption'] = {
            'state': caption.state,
            'text': caption.text,
            'destination_snapshot': caption.destination_snapshot,
            'settings_version': caption.settings_version,
            'model_name': caption.model_name,
            'approved_at': caption.approved_at.isoformat() if caption.approved_at else None,
            'revision': caption.revision,
            'revisions': list(CaptionRevision.objects.filter(job_caption=caption)
                              .order_by('revision')
                              .values('revision', 'action')),
        }
        evidence['ready_for_dispatch'] = ready_for_dispatch(job)

        with transaction.atomic():
            claim = claim_due_job(
                pipeline_id=job.pipeline_id, worker_id='runtime-verify',
                lease_seconds=60)
            job.refresh_from_db()
            evidence['claim_gate'] = {
                'selected': claim is not None,
                'state_inside_claim': job.state,
                'attempt_inside_claim': job.attempt_count,
                'rolled_back': True,
            }
            transaction.set_rollback(True)
        job.refresh_from_db()
        evidence['claim_gate']['state_after_rollback'] = job.state
        evidence['claim_gate']['attempt_after_rollback'] = job.attempt_count

        adapter = FacebookGroupPublishingAdapter()
        evidence['facebook'] = {'capabilities': adapter.capabilities()}
        try:
            adapter.dispatch()
            evidence['facebook']['dispatch_error'] = None
        except GroupsApiUnavailable as exc:
            evidence['facebook']['dispatch_error'] = exc.__class__.__name__
        evidence['facebook']['published_jobs'] = PublishingJob.objects.filter(
            pipeline_id=pipeline_id, state=PublishingJob.State.PUBLISHED).count()

        stuck = PublishingJob.objects.create(
            pipeline_id=pipeline_id,
            facebook_account_id=evidence['fixtures']['account_id'],
            facebook_group_id=evidence['fixtures']['group_id'],
            request_key='runtime-stuck-' + uuid.uuid4().hex,
            state=PublishingJob.State.CLAIMED, attempt_count=1,
            scheduled_at=timezone.now(), next_run_at=timezone.now())
        PublishingJob.objects.filter(pk=stuck.pk).update(
            worker_id='dead-worker', claim_token='stale-token',
            lease_expires_at=timezone.now() - timedelta(minutes=5))
        PublishingAttempt.objects.create(
            job=stuck, number=1, state=PublishingAttempt.State.CLAIMED)
        recovery = subprocess.run(
            [sys.executable, 'manage.py', 'publishing_recovery_tick',
             '--apply', '--pipeline-id', pipeline_id],
            cwd=backend_dir, capture_output=True, text=True, timeout=120)
        stuck.refresh_from_db()
        evidence['recovery'] = {
            'returncode': recovery.returncode,
            'stdout': recovery.stdout.strip(),
            'stuck_state': stuck.state,
            'stuck_error_code': stuck.error_code,
            'lease_events': WorkerLeaseEvent.objects.filter(job=stuck).count(),
        }

        since = evidence['fixtures']['started_at']
        evidence['logs'] = {
            'scheduler': journal_lines(
                'toolnet-scheduler-tick.service', since, pipeline_id),
            'caption': journal_lines(
                'toolnet-caption-tick.service', since, pipeline_id),
        }
        evidence['completed_at'] = timezone.now().isoformat()
    finally:
        if opts.keep:
            evidence['cleanup'] = {'skipped': True}
        else:
            evidence['cleanup'] = cleanup_fixtures(pipeline_id)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
