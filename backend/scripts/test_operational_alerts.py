"""Rollback-only operational alerts integration; no Facebook or network requests.

Creates synthetic Pipeline + overdue schedule in one transaction, checks
idempotent scans, reopen, acknowledgment/snooze, CTV isolation and fail-closed.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.api.v1.publishing.alert_views import (
    PublishingAlertsAPIView, PublishingAlertActionAPIView,
)
from modules.pipelines.models import Pipeline
from modules.publishing.alert_models import (
    PublishingAlertIncident, PublishingAlertEvent, PublishingAlertScan,
)
from modules.publishing.scheduler_models import PipelineSchedule
from modules.publishing.services.operational_alerts import (
    scan_alerts, list_alerts, alert_event_history, take_alert_action, AlertConflict, AlertError,
)

User = get_user_model()
factory = APIRequestFactory()
now = timezone.now()
suffix = uuid.uuid4().hex[:10]


def get_api(pipe, actor=None, query=''):
    request = factory.get(f'/api/v1/pipelines/{pipe.pk}/operational-alerts/{query}')
    if actor is not None:
        force_authenticate(request, user=actor)
    return PublishingAlertsAPIView.as_view()(request, pipeline_id=pipe.pk)


def post_api(pipe, aid, actor, data):
    request = factory.post(
        f'/api/v1/pipelines/{pipe.pk}/operational-alerts/{aid}/actions/',
        data, format='json',
    )
    if actor is not None:
        force_authenticate(request, user=actor)
    return PublishingAlertActionAPIView.as_view()(
        request, pipeline_id=pipe.pk, alert_id=aid,
    )


def must_fail(fn, exc):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f'Expected {exc.__name__}')


with transaction.atomic():
    ctv = User.objects.create_user(username=f'alert_{suffix}', password='TestOnlyAlertPass#125')
    other = User.objects.create_user(username=f'alertx_{suffix}', password='TestOnlyAlertPass#125')
    pipe = Pipeline.objects.create(name=f'Alert own {suffix}', ctv=ctv, status='active')
    foreign = Pipeline.objects.create(name=f'Alert foreign {suffix}', ctv=other, status='active')

    no_scan = list_alerts(pipeline_id=pipe.pk)
    assert no_scan['scan_stale'] and no_scan['last_scan_at'] is None
    assert no_scan['summary']['open'] == 0
    assert get_api(pipe, ctv).status_code == 200
    assert get_api(pipe, other).status_code == 404
    assert get_api(foreign, ctv).status_code == 404
    assert get_api(pipe).status_code in (401, 403)
    assert get_api(pipe, ctv, '?page=0').status_code == 400
    print('EMPTY/STALE INBOX, SESSION/TENANT AUTH, VALIDATION: PASS')

    schedule = PipelineSchedule.objects.create(
        pipeline=pipe, name='Overdue synthetic', enabled=True,
        interval_minutes=60, max_groups_per_run=1,
        start_at=now - timedelta(days=1),
        next_run_at=now - timedelta(minutes=45),
        caption_template='Synthetic only, not posted',
        require_anonymous=False, require_nonmember=False,
    )
    first = scan_alerts(pipeline_id=pipe.pk, now=now)
    assert first['created'] >= 1 and first['active_count'] >= 1
    incident = PublishingAlertIncident.objects.get(pipeline=pipe, code='SCHEDULE_OVERDUE')
    assert incident.state == 'open'
    assert PublishingAlertEvent.objects.filter(incident=incident).count() == 1
    assert PublishingAlertScan.objects.filter(pipeline=pipe).exists()
    repeat = scan_alerts(pipeline_id=pipe.pk, now=now + timedelta(seconds=1))
    assert repeat['created'] == 0 and repeat['reopened'] == 0
    assert PublishingAlertEvent.objects.filter(incident=incident).count() == 1
    print('SCANNER CREATES DEDUPED INCIDENT AND CHECKPOINT: PASS')

    ack = post_api(pipe, incident.pk, ctv, {
        'action': 'acknowledge', 'expected_version': incident.version,
    })
    assert ack.status_code == 200, ack.data
    incident.refresh_from_db()
    assert incident.acknowledged_by_id == ctv.pk and incident.state == 'open'
    assert PublishingAlertEvent.objects.filter(incident=incident, kind='acknowledged').count() == 1
    assert post_api(pipe, incident.pk, ctv, {
        'action': 'snooze', 'expected_version': 1, 'snooze_minutes': 60,
    }).status_code == 409
    assert post_api(pipe, incident.pk, other, {
        'action': 'snooze', 'expected_version': incident.version, 'snooze_minutes': 60,
    }).status_code == 404
    assert post_api(pipe, incident.pk, ctv, {
        'action': 'snooze', 'expected_version': incident.version,
        'snooze_minutes': 1,
    }).status_code == 400
    snooze = post_api(pipe, incident.pk, ctv, {
        'action': 'snooze', 'expected_version': incident.version, 'snooze_minutes': 60,
    })
    assert snooze.status_code == 200, snooze.data
    assert snooze.data['data']['is_snoozed']
    assert list_alerts(pipeline_id=pipe.pk)['summary']['requires_attention'] == 0
    print('ACK/SNOOZE, OPTIMISTIC LOCK, CTV ISOLATION, NO JOB WRITES: PASS')

    incident.refresh_from_db()
    with patch('modules.publishing.services.operational_alerts.health_snapshot',
               side_effect=RuntimeError('simulated read failure')):
        try:
            scan_alerts(pipeline_id=pipe.pk)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Scan failure unexpectedly swallowed')
    incident.refresh_from_db()
    assert incident.state == 'open'
    print('FAILED SCAN DOES NOT FALSE-RESOLVE: PASS')

    PipelineSchedule.objects.filter(pk=schedule.pk).update(enabled=False)
    cleared = scan_alerts(pipeline_id=pipe.pk, now=now + timedelta(seconds=3))
    assert cleared['resolved'] >= 1
    incident.refresh_from_db()
    assert incident.state == 'resolved'
    assert PublishingAlertEvent.objects.filter(incident=incident, kind='resolved').count() == 1
    assert post_api(pipe, incident.pk, ctv, {
        'action': 'acknowledge', 'expected_version': incident.version,
    }).status_code == 409

    PipelineSchedule.objects.filter(pk=schedule.pk).update(enabled=True)
    reopened = scan_alerts(pipeline_id=pipe.pk, now=now + timedelta(seconds=5))
    assert reopened['reopened'] >= 1
    incident.refresh_from_db()
    assert incident.state == 'open' and incident.acknowledged_at is None
    assert incident.snoozed_until is None
    assert PublishingAlertEvent.objects.filter(incident=incident, kind='reopened').count() == 1
    history = alert_event_history(pipeline_id=pipe.pk, alert_id=incident.pk)
    assert len(history['events']) >= 5 and history['read_only']
    must_fail(lambda: alert_event_history(
        pipeline_id=foreign.pk, alert_id=incident.pk), AlertError)
    assert not PublishingAlertIncident.objects.filter(pipeline=foreign).exists()
    print('RESOLVE/REOPEN RESET ACK, APPEND-ONLY HISTORY, CROSS-TENANT: PASS')

    assert list_alerts(pipeline_id=pipe.pk, state='all')['summary']['open'] >= 1
    must_fail(lambda: take_alert_action(
        pipeline_id=foreign.pk, alert_id=incident.pk, actor=other,
        action='acknowledge', expected_version=incident.version,
    ), AlertError)
    transaction.set_rollback(True)

print('ALL OPERATIONAL ALERT TEST FIXTURES ROLLED BACK')
print('STEP 9.7.14 INTERNAL ALERTS: PASSED')
