"""Authenticated, single-use decisions for a live rules prompt."""
import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from modules.facebook_publishing.models import RulesReview, WorkerPublishJob, WorkerResultState, WorkerRunningOp
from modules.publishing.services.job_engine import flag_uncertain


class RulesReviewConflict(ValueError):
    pass


def review_payload(row):
    worker = row.worker_job
    now = timezone.now()
    live = row.expires_at > now and WorkerRunningOp.objects.filter(
        publish_job=worker, heartbeat_at__gte=now - timedelta(seconds=30)).exists()
    return {'id': str(row.pk), 'job_id': str(worker.job_id), 'state': row.state,
            'account': worker.account.label, 'group': worker.group.name,
            'group_url': worker.group.group_url, 'text': row.display_text,
            'digest': row.digest, 'checkbox_count': row.checkbox_count,
            'checked_count': row.checked_count, 'response_field_count': row.response_field_count,
            'questions': row.question_schema,
            'expires_at': row.expires_at.isoformat(), 'browser_live': live}


@transaction.atomic
def create_review(*, worker_id, prompt, expires_at):
    identity = WorkerPublishJob.objects.values('pipeline_id', 'job_id').get(pk=worker_id)
    # Maintain the Job Engine lock order: Pipeline -> Job -> Worker.
    flag_uncertain(pipeline_id=identity['pipeline_id'], job_id=str(identity['job_id']),
                   code='RULES_CONFIRMATION_REQUIRED')
    worker = WorkerPublishJob.objects.select_related('job').select_for_update(of=('self',)).get(pk=worker_id)
    if worker.state != WorkerResultState.SUBMITTING:
        raise RulesReviewConflict('Job không chờ xác nhận quy tắc.')
    if RulesReview.objects.filter(worker_job=worker).exists():
        raise RulesReviewConflict('Job đã có yêu cầu xác nhận; không gửi lại.')
    worker.state = WorkerResultState.RULES_CONFIRMATION_REQUIRED
    worker.error_code = 'RULES_CONFIRMATION_REQUIRED'
    worker.error_detail = json.dumps({'rules_digest': prompt.digest,
                                     'checkbox_count': prompt.checkbox_count,
                                     'response_field_count': prompt.response_field_count})
    worker.save(update_fields=['state', 'error_code', 'error_detail'])
    return RulesReview.objects.create(worker_job=worker, digest=prompt.digest,
        display_text=prompt.display_text, checkbox_count=prompt.checkbox_count,
        checked_count=prompt.checked_count, response_field_count=prompt.response_field_count,
        question_schema=list(prompt.questions),
        expires_at=expires_at).pk


@transaction.atomic
def decide_review(*, pipeline_id, job_id, actor, digest, decision, consent, answers=None):
    row = (RulesReview.objects.select_for_update(of=('self',))
           .select_related('worker_job__pipeline')
           .filter(worker_job__pipeline_id=pipeline_id, worker_job__job_id=job_id).first())
    if row is None:
        raise RulesReviewConflict('Không có yêu cầu xác nhận cho Job này.')
    pipeline = row.worker_job.pipeline
    if not actor.is_active or not (actor.pk == pipeline.ctv_id or (actor.is_staff and actor.is_superuser)):
        raise RulesReviewConflict('Không có quyền xác nhận Pipeline này.')
    if (row.state != RulesReview.State.PENDING or row.digest != digest or
            row.worker_job.state != WorkerResultState.RULES_CONFIRMATION_REQUIRED):
        raise RulesReviewConflict('Quy tắc đã thay đổi hoặc đã được xử lý.')
    now = timezone.now()
    if row.expires_at <= now or not WorkerRunningOp.objects.filter(
            publish_job=row.worker_job, heartbeat_at__gte=now - timedelta(seconds=30)).exists():
        raise RulesReviewConflict('Phiên browser không còn hoạt động; cần đối soát bài đăng.')
    if decision == 'approve':
        if consent is not True:
            raise RulesReviewConflict('Cần xác nhận đã đọc và đồng ý toàn bộ nội dung.')
        answers = answers or []
        if (len(row.question_schema) != row.response_field_count or
                any(not item.get('supported') for item in row.question_schema) or
                len(answers) != row.response_field_count):
            raise RulesReviewConflict('Câu hỏi chưa được hỗ trợ hoặc chưa có đủ câu trả lời.')
        from modules.publishing.services.post_verification import SECRET_MARKER
        from modules.system_config.crypto import sanitize_text
        if any(not isinstance(x, str) or not x.strip() or len(x) > 500 or
               SECRET_MARKER.search(x) or sanitize_text(x) != x for x in answers):
            raise RulesReviewConflict('Câu trả lời không hợp lệ hoặc chứa thông tin bí mật.')
        from modules.system_config.crypto import encrypt_secret
        row.answers_ciphertext = encrypt_secret(json.dumps(answers, ensure_ascii=False))
        row.state = RulesReview.State.APPROVED
    elif decision == 'reject':
        row.state = RulesReview.State.REJECTED
    else:
        raise RulesReviewConflict('Quyết định không hợp lệ.')
    row.decided_by = actor
    row.decided_at = now
    row.save(update_fields=['state', 'decided_by', 'decided_at', 'answers_ciphertext', 'updated_at'])
    from modules.facebook_publishing.services.audit_log import AuditLogger
    transaction.on_commit(lambda: AuditLogger(worker_id='rules-review', job_id=str(job_id)).log_event(
        'rules_review_decision', actor_id=actor.pk, decision=decision, rules_digest=digest))
    return row.state


@transaction.atomic
def consume_approval(*, review_id, digest):
    row = RulesReview.objects.select_for_update(of=('self',)).select_related('worker_job').get(pk=review_id)
    if (row.state != RulesReview.State.APPROVED or row.digest != digest or
            row.expires_at <= timezone.now() or
            row.worker_job.state != WorkerResultState.RULES_CONFIRMATION_REQUIRED or
            not WorkerRunningOp.objects.filter(publish_job=row.worker_job,
                heartbeat_at__gte=timezone.now() - timedelta(seconds=30)).exists()):
        raise RulesReviewConflict('Xác nhận hết hạn, đã dùng hoặc quy tắc đã thay đổi.')
    from modules.system_config.crypto import decrypt_secret
    try:
        answers = json.loads(decrypt_secret(row.answers_ciphertext))
    except (ValueError, TypeError):
        raise RulesReviewConflict('Không đọc được câu trả lời đã xác nhận.') from None
    if not isinstance(answers, list) or len(answers) != row.response_field_count:
        raise RulesReviewConflict('Câu trả lời không còn khớp màn hình Facebook.')
    row.answers_ciphertext = ''
    row.state = RulesReview.State.SUBMITTING
    row.submit_started_at = timezone.now()
    row.save(update_fields=['state', 'submit_started_at', 'answers_ciphertext', 'updated_at'])
    worker = row.worker_job
    worker.state = WorkerResultState.RULES_CONFIRMED
    worker.save(update_fields=['state'])
    return answers


def finish_review(*, review_id, state):
    if state not in (RulesReview.State.SUBMITTED, RulesReview.State.EXPIRED, RulesReview.State.UNCERTAIN):
        raise RulesReviewConflict('Trạng thái không hợp lệ.')
    RulesReview.objects.filter(pk=review_id, state__in=[RulesReview.State.PENDING,
        RulesReview.State.APPROVED, RulesReview.State.SUBMITTING]).update(
            state=state, answers_ciphertext='', updated_at=timezone.now())


def poll_review(*, review_id, worker_job_id):
    now = timezone.now()
    updated = WorkerRunningOp.objects.filter(publish_job_id=worker_job_id).update(heartbeat_at=now)
    if updated != 1:
        raise RulesReviewConflict('Mất khóa phiên worker; cần đối soát.')
    row = RulesReview.objects.get(pk=review_id, worker_job_id=worker_job_id)
    return row.state, row.expires_at


@transaction.atomic
def stop_review(*, review_id, expired=False):
    row = RulesReview.objects.select_for_update(of=('self',)).select_related('worker_job').get(pk=review_id)
    if expired and row.state in (RulesReview.State.PENDING, RulesReview.State.APPROVED):
        row.state = RulesReview.State.EXPIRED
        row.answers_ciphertext = ''
        row.save(update_fields=['state', 'answers_ciphertext', 'updated_at'])
    worker = row.worker_job
    worker.state = WorkerResultState.UNCERTAIN
    worker.error_code = 'RULES_REVIEW_EXPIRED' if expired else 'RULES_REVIEW_DECLINED'
    worker.save(update_fields=['state', 'error_code'])


@transaction.atomic
def expire_lost_session(*, pipeline_id, job_id):
    """Close a stale review without allowing another submit or another Job."""
    row = (RulesReview.objects.select_for_update(of=('self',)).select_related('worker_job')
           .filter(worker_job__pipeline_id=pipeline_id, worker_job__job_id=job_id).first())
    if row is None:
        raise RulesReviewConflict('Không có phiên xác nhận để đối soát.')
    now = timezone.now()
    if row.expires_at > now and WorkerRunningOp.objects.filter(
            publish_job=row.worker_job, heartbeat_at__gte=now - timedelta(seconds=30)).exists():
        raise RulesReviewConflict('Worker vẫn đang giữ phiên browser.')
    if row.state in (RulesReview.State.PENDING, RulesReview.State.APPROVED):
        row.state = RulesReview.State.EXPIRED
    elif row.state == RulesReview.State.SUBMITTING:
        row.state = RulesReview.State.UNCERTAIN
    row.answers_ciphertext = ''
    row.save(update_fields=['state', 'answers_ciphertext', 'updated_at'])
    worker = row.worker_job
    worker.state = WorkerResultState.UNCERTAIN
    worker.error_code = 'RULES_SESSION_LOST'
    worker.save(update_fields=['state', 'error_code'])
    return row.state
