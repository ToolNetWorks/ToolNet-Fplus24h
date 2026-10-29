"""Step 9.7.18: rollback-only, no secrets/network/real publishing.

Exercises CTV/Admin isolation, invalid role combination, metadata redaction,
foreign-key tampering via QuerySet.update, bounded scans, API fail-closed.
"""
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.albums.models import Album, AlbumImage
from modules.api.v1.facebook_accounts.upload_views import FacebookCookieUploadAPIView
from modules.api.v1.publishing.security_audit_views import PublishingSecurityAuditAPIView
from modules.facebook_accounts.credentials import FacebookCookieSecret
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.proxies.models import ProxyEndpoint, ProxyAuthSecret
from modules.publishing.models import PublishingJob
from modules.publishing.manual_handoff_models import ManualPublishingHandoff
from modules.publishing.services.security_audit import security_snapshot, SecurityAuditError

User = get_user_model()
factory = APIRequestFactory()
suffix = uuid.uuid4().hex[:10]


def api(pipe, actor=None, query=''):
    req = factory.get(f'/api/v1/pipelines/{pipe.pk}/security-audit/{query}')
    if actor is not None:
        force_authenticate(req, user=actor)
    return PublishingSecurityAuditAPIView.as_view()(req, pipeline_id=pipe.pk)


def upload(pipe, actor):
    req = factory.post(f'/api/v1/pipelines/{pipe.pk}/facebook-accounts/cookie-upload/',
                       {}, format='multipart')
    force_authenticate(req, user=actor)
    return FacebookCookieUploadAPIView.as_view()(req, pipeline_id=pipe.pk)


with transaction.atomic():
    owner = User.objects.create_user(username='secowner_' + suffix, password='FixtureOnly!1234')
    other = User.objects.create_user(username='secother_' + suffix, password='FixtureOnly!1234')
    staff_only = User.objects.create_user(username='secstaff_' + suffix,
                                           password='FixtureOnly!1234', is_staff=True)
    super_only = User.objects.create_user(username='secsuper_' + suffix,
                                           password='FixtureOnly!1234', is_superuser=True)
    admin = User.objects.create_superuser(username='secadmin_' + suffix,
                                           password='FixtureOnly!1234', email='')
    own = Pipeline.objects.create(name='Security owner ' + suffix,
                                  ctv=owner, status=Pipeline.Status.ACTIVE)
    foreign = Pipeline.objects.create(name='Security foreign ' + suffix,
                                      ctv=other, status=Pipeline.Status.ACTIVE)
    a = FacebookAccount.objects.create(pipeline=own, label='Owner test')
    b = FacebookAccount.objects.create(pipeline=foreign, label='Other test')
    group = FacebookGroup.objects.create(pipeline=own, name='Owner group',
        group_url=f'https://www.facebook.com/groups/security{suffix}/')
    job = PublishingJob.objects.create(pipeline=own, facebook_account=a,
        facebook_group=group, request_key='security-' + suffix,
        scheduled_at=timezone.now(),
        next_run_at=timezone.now())
    handoff = ManualPublishingHandoff.objects.create(pipeline=own, job=job, actor=owner)
    proxy = ProxyEndpoint.objects.create(pipeline=own, account=a,
        host='8.8.8.8', port=8080, exit_ip='8.8.8.8')
    # The audit must never serialize this marker (or ciphertext itself).
    secret_marker = 'PRIVATE_CIPHERTEXT_MUST_NOT_ESCAPE_' + suffix
    cookie_secret = FacebookCookieSecret.objects.create(account=a, ciphertext=secret_marker)
    proxy_secret_marker = 'PRIVATE_PROXY_CIPHERTEXT_MUST_NOT_ESCAPE_' + suffix
    proxy_secret = ProxyAuthSecret.objects.create(proxy=proxy, ciphertext=proxy_secret_marker)
    album = Album.objects.create(pipeline=own, name='Owner album')
    image_id = uuid.uuid4()
    picture = AlbumImage.objects.create(
        pk=image_id, album=album, original_filename='test.webp',
        storage_key=f'pipeline-albums/{own.pk}/{album.pk}/{image_id}.webp',
        mime_type='image/webp', file_size=1024, width=10, height=10,
        sha256='a'*64, upload_status='ready',
    )
    with patch('socket.socket', side_effect=AssertionError('No network expected')):
        ok = security_snapshot(pipeline_id=own.pk, limit=100)
        assert ok['status'] == 'consistent' and ok['complete'] and ok['read_only'] is True, ok
        assert ok['production_security_certified'] is False
        assert ok['contains_credentials'] is False
        assert api(own, owner).status_code == 200
        assert api(own, other).status_code == 404
        assert api(foreign, owner).status_code == 404
        assert api(own).status_code in (401, 403)
        assert api(own, staff_only).status_code == 403
        assert api(own, super_only).status_code == 403
        assert api(own, admin).status_code == 200
        assert api(own, owner, '?limit=0').status_code == 400
        assert api(own, owner, '?limit=101').status_code == 400
        assert api(own, owner)['Cache-Control'] == 'private, no-store'
        assert reverse('pipeline-security-audit', kwargs={'pipeline_id': own.pk}).endswith('/security-audit/')
        print('AUTH/ROLE/TENANT/THROTTLED READ-ONLY API: PASS')

        # Cookie-upload permission must require BOTH admin flags; a superuser
        # without staff may never upload into someone else's Pipeline.
        assert upload(own, other).status_code == 404
        assert upload(own, staff_only).status_code == 404
        assert upload(own, super_only).status_code == 404
        assert upload(own, owner).status_code == 400  # authorized, but missing file
        assert upload(own, admin).status_code == 400  # authorized, but missing file
        print('COOKIE UPLOAD PRIVILEGE ESCALATION: BLOCKED')

        # Deliberately bypass model.full_clean(), simulating an unsafe SQL/bulk
        # update or compromised import. Relational audit must detect corruption.
        PublishingJob.objects.filter(pk=job.pk).update(facebook_account=b)
        ManualPublishingHandoff.objects.filter(pk=handoff.pk).update(actor=other)
        ProxyEndpoint.objects.filter(pk=proxy.pk).update(account=b)
        FacebookCookieSecret.objects.filter(pk=cookie_secret.pk).update(ciphertext='')
        ProxyAuthSecret.objects.filter(pk=proxy_secret.pk).update(ciphertext='')
        AlbumImage.objects.filter(pk=picture.pk).update(storage_key='wrong-tenant/key.webp')
        flagged = security_snapshot(pipeline_id=own.pk, limit=100)
        codes = {row['code'] for row in flagged['findings']}
        assert {'JOB_ACCOUNT_FOREIGN', 'HANDOFF_ACTOR_FOREIGN',
                'PROXY_ACCOUNT_FOREIGN', 'COOKIE_CIPHERTEXT_EMPTY',
                'PROXY_CIPHERTEXT_EMPTY',
                'ALBUM_IMAGE_STORAGE_SCOPE'} <= codes, codes
        assert flagged['status'] == 'attention_required' and flagged['complete']
        serialized = json.dumps(flagged, ensure_ascii=False)
        assert secret_marker not in serialized and proxy_secret_marker not in serialized
        assert '"ciphertext":' not in serialized.lower()
        assert 'wrong-tenant' not in serialized and '8.8.8.8' not in serialized
        assert not any(x.get('object_id') == str(b.pk) for x in flagged['findings'])
        print('CROSS-TENANT CORRUPTION / SECRET REDACTION: PASS')

        # The inspected Pipeline must not inherit a foreign Pipeline's findings.
        other_clean = security_snapshot(pipeline_id=foreign.pk)
        assert other_clean['status'] == 'consistent' and other_clean['findings'] == []

        # More than limit READY images: bounded scan must report incomplete,
        # never healthy, even though a sample looks clean.
        extra_id = uuid.uuid4()
        AlbumImage.objects.create(
            pk=extra_id, album=album, original_filename='second.webp',
            storage_key='foreign-scope/mismatch.webp',
            mime_type='image/webp', file_size=1024, width=10, height=10,
            sha256='b'*64, upload_status='ready',
        )
        small = security_snapshot(pipeline_id=own.pk, limit=1)
        assert small['status'] == 'incomplete' and not small['complete']
        assert 'ALBUM_IMAGE_STORAGE_SCOPE' in small['truncated_categories']
        print('SCAN TRUNCATION FAIL-CLOSED: PASS')

        with patch('modules.api.v1.publishing.security_audit_views.security_snapshot',
                   side_effect=RuntimeError('SECRET_DATABASE_CONNECTION_TEST_MARKER')):
            failed = api(own, owner)
            assert failed.status_code == 503
            assert 'SECRET_DATABASE_CONNECTION_TEST_MARKER' not in json.dumps(failed.data)
            assert failed['Cache-Control'] == 'private, no-store'
        try:
            security_snapshot(pipeline_id=uuid.uuid4())
        except SecurityAuditError:
            pass
        else:
            raise AssertionError('Unknown Pipeline accepted')
        print('FAIL CLOSED / NO DATABASE SECRET LEAK: PASS')
    transaction.set_rollback(True)

print('STEP 9.7.18 SECURITY & TENANT ISOLATION: PASSED (all fixtures rolled back)')
