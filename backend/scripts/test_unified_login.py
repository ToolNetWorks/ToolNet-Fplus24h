"""
Test Unified Login for ToolNet Fplus24h.
Verifies:
- CSRF requirement
- Wrong password rejection (401)
- Disabled user rejection (403)
- Admin login (is_staff=True & is_superuser=True) -> role=admin, redirect=/
- Privilege escalation blocking (staff-only or superuser-only -> 403)
- CTV without Pipeline -> 403
- CTV with locked/disabled Pipeline -> 403
- CTV with ACTIVE Pipeline -> role=ctv, redirect=/workspace/
- CTV cannot access Admin data (/api/v1/auth/me/ -> 403)
- CTV cannot access foreign Pipeline endpoints (404)
- All fixtures rolled back cleanly.
"""
import json
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client

from modules.pipelines.models import Pipeline

User = get_user_model()
suffix = uuid.uuid4().hex[:10]

client = Client(
    enforce_csrf_checks=True,
    HTTP_HOST="127.0.0.1",
    REMOTE_ADDR="198.51.100.99",
)

def get_csrf(c=client):
    res = c.get("/api/v1/auth/csrf/", secure=True)
    assert res.status_code == 200
    return res.json()["csrfToken"]

def do_login(username, password, csrf_token, c=client):
    return c.post(
        "/api/v1/auth/login/",
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
        secure=True,
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_REFERER="https://127.0.0.1/",
    )

with transaction.atomic():
    # Setup test users
    password = "FixturePassword!1234"

    # 1. Admin
    admin_user = User.objects.create_superuser(
        username="test_admin_" + suffix,
        password=password,
        email="admin_" + suffix + "@test.local",
    )
    assert admin_user.is_staff and admin_user.is_superuser

    # 2. Staff-only (invalid role)
    staff_user = User.objects.create_user(
        username="test_staff_" + suffix,
        password=password,
        is_staff=True,
        is_superuser=False,
    )

    # 3. Superuser-only (invalid role)
    super_user = User.objects.create_user(
        username="test_super_" + suffix,
        password=password,
        is_staff=False,
        is_superuser=True,
    )

    # 4. CTV without Pipeline
    ctv_no_pipe = User.objects.create_user(
        username="test_ctv_nopipe_" + suffix,
        password=password,
        is_staff=False,
        is_superuser=False,
    )

    # 5. CTV with Disabled Pipeline
    ctv_disabled = User.objects.create_user(
        username="test_ctv_disabled_" + suffix,
        password=password,
        is_staff=False,
        is_superuser=False,
    )
    disabled_pipeline = Pipeline.objects.create(
        name="Disabled Pipe " + suffix,
        ctv=ctv_disabled,
        status="disabled",
    )

    # 6. CTV with Active Pipeline
    ctv_active = User.objects.create_user(
        username="test_ctv_active_" + suffix,
        password=password,
        is_staff=False,
        is_superuser=False,
    )
    active_pipeline = Pipeline.objects.create(
        name="Active Pipe " + suffix,
        ctv=ctv_active,
        status=Pipeline.Status.ACTIVE,
    )

    # 7. Another CTV with Active Pipeline (foreign)
    ctv_foreign = User.objects.create_user(
        username="test_ctv_foreign_" + suffix,
        password=password,
        is_staff=False,
        is_superuser=False,
    )
    foreign_pipeline = Pipeline.objects.create(
        name="Foreign Pipe " + suffix,
        ctv=ctv_foreign,
        status=Pipeline.Status.ACTIVE,
    )

    # 8. Disabled account
    disabled_account = User.objects.create_user(
        username="test_inactive_" + suffix,
        password=password,
        is_active=False,
    )

    token = get_csrf()

    # --- TEST 1: CSRF Protection ---
    no_csrf_res = client.post(
        "/api/v1/auth/login/",
        data=json.dumps({"username": admin_user.username, "password": password}),
        content_type="application/json",
        secure=True,
    )
    assert no_csrf_res.status_code == 403, "CSRF missing must be 403"
    print("1. CSRF PROTECTION: PASS")

    # --- TEST 2: Wrong Password ---
    wrong_pwd_res = do_login(admin_user.username, "wrong_password_999", token)
    assert wrong_pwd_res.status_code == 401, "Wrong password must be 401"
    assert wrong_pwd_res.json()["success"] is False
    print("2. WRONG PASSWORD REJECTION: PASS")

    # --- TEST 3: Disabled User ---
    inactive_res = do_login(disabled_account.username, password, token)
    assert inactive_res.status_code == 401 or inactive_res.status_code == 403
    assert inactive_res.json()["success"] is False
    print("3. DISABLED USER REJECTION: PASS")

    # --- TEST 4: Admin Login ---
    admin_client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="198.51.100.99")
    admin_token = get_csrf(admin_client)
    admin_login_res = do_login(admin_user.username, password, admin_token, admin_client)
    assert admin_login_res.status_code == 200, f"Admin login failed: {admin_login_res.content}"
    admin_data = admin_login_res.json()
    assert admin_data["success"] is True
    assert admin_data["user"]["role"] == "admin"
    assert admin_data["user"]["redirect_to"] == "/"
    assert admin_data["user"]["pipeline_id"] is None

    # Admin session check
    admin_me_res = admin_client.get("/api/v1/auth/me/", secure=True)
    assert admin_me_res.status_code == 200
    assert admin_me_res.json()["user"]["role"] == "admin"

    admin_landing_res = admin_client.get("/api/v1/auth/landing/", secure=True)
    assert admin_landing_res.status_code == 200
    assert admin_landing_res.json()["data"]["role"] == "admin"
    assert admin_landing_res.json()["data"]["redirect_to"] == "/"
    print("4. ADMIN LOGIN & SESSION -> DASHBOARD (/): PASS")

    # --- TEST 5: Privilege Escalation (Staff-only or Superuser-only) ---
    staff_login_res = do_login(staff_user.username, password, token)
    assert staff_login_res.status_code == 403, "Staff-only must be blocked (403)"
    assert staff_login_res.json()["success"] is False

    super_login_res = do_login(super_user.username, password, token)
    assert super_login_res.status_code == 403, "Superuser-only must be blocked (403)"
    assert super_login_res.json()["success"] is False
    print("5. PRIVILEGE ESCALATION BLOCKING (STAFF/SUPER COMBO): PASS")

    # --- TEST 6: CTV without Pipeline ---
    nopipe_res = do_login(ctv_no_pipe.username, password, token)
    assert nopipe_res.status_code == 403, "CTV without pipeline must be 403"
    assert nopipe_res.json()["success"] is False
    assert "chưa được gắn Pipeline" in nopipe_res.json()["message"]
    print("6. CTV WITHOUT PIPELINE REJECTION: PASS")

    # --- TEST 7: CTV with Disabled Pipeline ---
    disabled_res = do_login(ctv_disabled.username, password, token)
    assert disabled_res.status_code == 403, "CTV with disabled pipeline must be 403"
    assert disabled_res.json()["success"] is False
    assert "khóa" in disabled_res.json()["message"].lower()
    print("7. CTV WITH DISABLED PIPELINE REJECTION: PASS")

    # --- TEST 8: CTV with ACTIVE Pipeline ---
    ctv_client = Client(enforce_csrf_checks=True, HTTP_HOST="127.0.0.1", REMOTE_ADDR="198.51.100.99")
    ctv_token = get_csrf(ctv_client)
    ctv_login_res = do_login(ctv_active.username, password, ctv_token, ctv_client)
    assert ctv_login_res.status_code == 200, f"CTV login failed: {ctv_login_res.content}"
    ctv_data = ctv_login_res.json()
    assert ctv_data["success"] is True
    assert ctv_data["user"]["role"] == "ctv"
    assert ctv_data["user"]["redirect_to"] == "/workspace/"
    assert ctv_data["user"]["pipeline_id"] == str(active_pipeline.pk)

    # CTV session landing check
    ctv_landing_res = ctv_client.get("/api/v1/auth/landing/", secure=True)
    assert ctv_landing_res.status_code == 200
    assert ctv_landing_res.json()["data"]["role"] == "ctv"
    assert ctv_landing_res.json()["data"]["redirect_to"] == "/workspace/"
    assert ctv_landing_res.json()["data"]["pipeline_id"] == str(active_pipeline.pk)
    print("8. CTV LOGIN & SESSION -> WORKSPACE (/workspace/): PASS")

    # --- TEST 9: CTV Access Control & Tenant Isolation ---
    # CTV must NOT access Admin data (/api/v1/auth/me/)
    ctv_me_res = ctv_client.get("/api/v1/auth/me/", secure=True)
    assert ctv_me_res.status_code == 403, "CTV accessing admin_me must be 403"

    # CTV can access their own workspace
    own_workspace_res = ctv_client.get("/api/v1/ctv/workspace/", secure=True)
    assert own_workspace_res.status_code == 200
    assert own_workspace_res.json()["data"]["pipeline"]["id"] == str(active_pipeline.pk)

    # CTV cannot access foreign pipeline
    foreign_access_res = ctv_client.get(
        f"/api/v1/pipelines/{foreign_pipeline.pk}/security-audit/",
        secure=True,
    )
    assert foreign_access_res.status_code == 404, "CTV accessing foreign pipeline must be 404"
    print("9. CTV ACCESS CONTROL & TENANT ISOLATION: PASS")

    transaction.set_rollback(True)

print("ALL TEST FIXTURES: ROLLED BACK")
print("TOOLNET FPLUS24H UNIFIED LOGIN TESTS: ALL PASSED")
