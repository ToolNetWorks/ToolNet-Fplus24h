"""Rollback-only smoke test of tenant scope and read-only behavior."""
import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from modules.pipelines.models import Pipeline
from modules.publishing.models import PublishingJob
from modules.publishing.services.operations_health import health_snapshot, OperationsHealthError

with transaction.atomic():
    key = uuid.uuid4().hex[:10]
    user = get_user_model().objects.create_user(username='ops_' + key, password='TemporaryTestOnly!123')
    user2 = get_user_model().objects.create_user(username='ops2_' + key, password='TemporaryTestOnly!123')
    own = Pipeline.objects.create(name='Operations ' + key, ctv=user, status=Pipeline.Status.ACTIVE)
    other = Pipeline.objects.create(name='Operations foreign ' + key, ctv=user2, status=Pipeline.Status.ACTIVE)
    own_before = PublishingJob.objects.filter(pipeline=own).count()
    result = health_snapshot(pipeline_id=own.pk, sample_limit=1000)
    assert result['pipeline_id'] == str(own.pk)
    assert result['database']['connected']
    assert result['jobs_by_state'] == {}
    assert result['status'] == 'healthy', result
    assert PublishingJob.objects.filter(pipeline=own).count() == own_before
    assert result['pipeline_id'] != str(other.pk)
    try:
        health_snapshot(pipeline_id=uuid.uuid4())
    except OperationsHealthError:
        pass
    else:
        raise AssertionError('Unknown pipeline was accepted')
    transaction.set_rollback(True)
print('STEP 9.7.12 OPERATIONS HEALTH: PASS (all fixtures rolled back)')
