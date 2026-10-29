"""Rollback-only Django login regression test. No Facebook, R2, or proxy I/O."""
import json
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from modules.pipelines.models import Pipeline

suffix = uuid.uuid4().hex[:10]
User = get_user_model()


def sign_in(username, password):
    c = Client(enforce_csrf_checks=True, SERVER_NAME="localhost")
    token_response = c.get('/api/v1/auth/csrf/', secure=True)
    assert token_response.status_code == 200, token_response.status_code
    token = token_response.json()['csrfToken']
    reply = c.post('/api/v1/auth/login/', data=json.dumps({
        'username': username, 'password': password,
    }), content_type='application/json', HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://localhost", secure=True)
    return c, reply


with transaction.atomic():
    admin = User.objects.create_superuser(
        username=f'access_admin_{suffix}', password='DummyTest-only-123!@#', email='')
    ctv = User.objects.create_user(
        username=f'access_ctv_{suffix}', password='DummyTest-only-123!@#')
    disabled = User.objects.create_user(
        username=f'access_disabled_{suffix}', password='DummyTest-only-123!@#')
    half_admin = User.objects.create_user(
        username=f'access_super_only_{suffix}', password='DummyTest-only-123!@#',
        is_superuser=True, is_staff=False)
    pipeline = Pipeline.objects.create(
        name=f'Access Fixture {suffix}', ctv=ctv, status=Pipeline.Status.ACTIVE)
    disabled_pipeline = Pipeline.objects.create(
        name=f'Access Disabled Fixture {suffix}', ctv=disabled, status=Pipeline.Status.DISABLED)

    c, res = sign_in(admin.username, 'DummyTest-only-123!@#')
    assert res.status_code == 200 and res.json()['user']['role'] == 'admin', res.content[:250]
    assert c.get('/api/v1/auth/landing/', secure=True).json()['data']['redirect_to'] == '/'
    assert c.get('/api/v1/auth/me/', secure=True).status_code == 200
    print('ADMIN LOGIN AND REDIRECT: PASS')

    c, res = sign_in(ctv.username, 'DummyTest-only-123!@#')
    assert res.status_code == 200 and res.json()['user']['role'] == 'ctv', res.content[:250]
    landing = c.get('/api/v1/auth/landing/', secure=True)
    assert landing.status_code == 200 and landing.json()['data']['redirect_to'] == '/workspace/'
    assert c.get('/api/v1/auth/me/', secure=True).status_code == 403
    assert c.get('/api/v1/ctv/workspace/', secure=True).status_code == 200
    assert c.get('/api/v1/admin/overview/', secure=True).status_code in (401, 403)
    print('CTV LOGIN, WORKSPACE, NO ADMIN PRIVILEGES: PASS')

    c, res = sign_in(ctv.username, 'incorrect-password')
    assert res.status_code == 401
    print('BAD PASSWORD: BLOCKED')

    c, res = sign_in(disabled.username, 'DummyTest-only-123!@#')
    assert res.status_code == 403
    print('DISABLED PIPELINE: BLOCKED')

    c, res = sign_in(half_admin.username, 'DummyTest-only-123!@#')
    assert res.status_code == 403
    print('SUPERUSER WITHOUT STAFF: BLOCKED')

    pipeline.status = Pipeline.Status.DISABLED
    pipeline.save(update_fields=['status', 'updated_at'])
    c, res = sign_in(ctv.username, 'DummyTest-only-123!@#')
    assert res.status_code == 403
    print('LOCKED EXISTING CTV: BLOCKED')

    transaction.set_rollback(True)

print('AUTH FIXTURE TRANSACTION ROLLED BACK: PASS')
