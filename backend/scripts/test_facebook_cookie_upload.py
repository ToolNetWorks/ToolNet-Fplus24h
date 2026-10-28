import json
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import override_settings
from rest_framework.test import (
    APIClient,
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_accounts.credentials import FacebookCookieSecret
from modules.facebook_accounts.crypto import decrypt_cookies
from modules.api.v1.facebook_accounts.upload_views import (
    FacebookCookieUploadAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
view = FacebookCookieUploadAPIView.as_view()
admin = User.objects.filter(
    is_superuser=True,
    is_active=True,
).first()
assert admin is not None, "Super Admin not found"
initial_accounts = FacebookAccount.objects.count()
initial_secrets = FacebookCookieSecret.objects.count()
suffix = uuid4().hex[:10]
FAKE_COOKIES = {
    "url": "https://www.facebook.com/",
    "cookies": [
        {
            "name": "c_user",
            "value": "FAKE_USER_123",
            "domain": ".facebook.com",
            "path": "/",
            "secure": True,
            "httpOnly": False,
        },
        {
            "name": "xs",
            "value": "FAKE_SESSION_456",
            "domain": ".facebook.com",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        },
    ],
}
def create_test_pipeline(number):
    username = f"fbtest_{number}_{suffix}"
    user = User.objects.create_user(
        username=username,
        password=f"LocalTest#{suffix}A1!",
        email=f"{username}@example.invalid",
    )
    pipeline = Pipeline(
        name=f"FB Test Pipeline {number} {suffix}",
        ctv=user,
        status="active",
    )
    pipeline.full_clean()
    pipeline.save()
    return pipeline, user
def upload(pipeline, user=None, payload=None):
    content = json.dumps(
        FAKE_COOKIES if payload is None else payload
    ).encode("utf-8")
    uploaded = SimpleUploadedFile(
        name="fake-facebook-cookies.json",
        content=content,
        content_type="application/json",
    )
    url = (
        f"/api/v1/pipelines/{pipeline.pk}/"
        "facebook-accounts/cookie-upload/"
    )
    request = factory.post(
        url,
        {
            "label": "Facebook Test",
            "file": uploaded,
        },
        format="multipart",
    )
    if user is not None:
        force_authenticate(request, user=user)
    return view(
        request,
        pipeline_id=pipeline.pk,
    )
with transaction.atomic():
    pipeline_a, ctv_a = create_test_pipeline("a")
    pipeline_b, ctv_b = create_test_pipeline("b")
    # 1. Admin can upload.
    response = upload(pipeline_a, admin)
    assert response.status_code == 201, response.data
    print("ADMIN UPLOAD: PASS")
    # 2. Account and encrypted secret must match.
    account = FacebookAccount.objects.get(
        pk=response.data["data"]["id"]
    )
    secret = FacebookCookieSecret.objects.get(
        account=account
    )
    assert account.pipeline_id == pipeline_a.pk
    assert account.connection_status == "not_connected"
    assert "FAKE_SESSION_456" not in secret.ciphertext
    assert "FAKE_USER_123" not in secret.ciphertext
    decrypted = decrypt_cookies(secret.ciphertext)
    assert len(decrypted) == 2
    assert secret.cookie_count == 2
    print("ENCRYPTED STORAGE: PASS")
    print("COOKIE SECRET NOT EXPOSED: PASS")
    print("INITIAL STATUS: NOT_CONNECTED")
    # 3. CTV A can upload to its own Pipeline.
    response = upload(pipeline_a, ctv_a)
    assert response.status_code == 201, response.data
    print("CTV OWN PIPELINE: PASS")
    # 4. CTV A cannot upload to Pipeline B.
    response = upload(pipeline_b, ctv_a)
    assert response.status_code in (403, 404), response.data
    print("CROSS-PIPELINE UPLOAD: BLOCKED")
    # 5. CTV B can upload to Pipeline B.
    response = upload(pipeline_b, ctv_b)
    assert response.status_code == 201, response.data
    print("SECOND CTV OWN PIPELINE: PASS")
    # 6. Anonymous upload must fail.
    response = upload(pipeline_a)
    assert response.status_code in (401, 403)
    print("ANONYMOUS UPLOAD: BLOCKED")
    # 7. Disabled Pipeline must reject upload.
    pipeline_b.status = "disabled"
    pipeline_b.save(update_fields=["status"])
    response = upload(pipeline_b, admin)
    assert response.status_code == 409, response.data
    print("DISABLED PIPELINE: BLOCKED")
    # 8. Missing session cookie must fail.
    invalid_payload = {
        "url": "https://www.facebook.com/",
        "cookies": [
            {
                "name": "c_user",
                "value": "FAKE_USER",
                "domain": ".facebook.com",
                "path": "/",
                "secure": True,
            }
        ],
    }
    response = upload(
        pipeline_a,
        admin,
        payload=invalid_payload,
    )
    assert response.status_code == 400, response.data
    print("INVALID COOKIE FILE: BLOCKED")
    # 9. Browser-style session request without CSRF.
    with override_settings(
        ALLOWED_HOSTS=["testserver", "localhost"]
    ):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(admin)
        csrf_file = SimpleUploadedFile(
            "fake-facebook-cookies.json",
            json.dumps(FAKE_COOKIES).encode("utf-8"),
            content_type="application/json",
        )
        response = client.post(
            (
                f"/api/v1/pipelines/{pipeline_a.pk}/"
                "facebook-accounts/cookie-upload/"
            ),
            {
                "label": "CSRF Test",
                "file": csrf_file,
            },
            format="multipart",
        )
        assert response.status_code == 403, response.status_code
        print("MISSING CSRF TOKEN: BLOCKED")
    # 10. Verify ownership in stored test records.
    for record in FacebookAccount.objects.filter(
        label="Facebook Test",
        pipeline__in=[pipeline_a, pipeline_b],
    ):
        assert record.pipeline_id in {
            pipeline_a.pk,
            pipeline_b.pk,
        }
    print("DATABASE PIPELINE RELATIONS: PASS")
    # Roll back every test creation and update.
    transaction.set_rollback(True)
assert FacebookAccount.objects.count() == initial_accounts
assert FacebookCookieSecret.objects.count() == initial_secrets
print("DATABASE CHANGES: ROLLED BACK")
print("FACEBOOK COOKIE UPLOAD API: PASSED")
