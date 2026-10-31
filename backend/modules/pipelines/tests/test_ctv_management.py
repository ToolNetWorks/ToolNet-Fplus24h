import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from modules.pipelines.models import CTVAdminAuditLog, Pipeline


TEST_PASSWORD = "StrongTestPass#2026"
NEW_PASSWORD = "NewStrongPass#2026"


class CTVManagementAPITests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_superuser(
            username="ctv_admin",
            email="ctv_admin@example.test",
            password=TEST_PASSWORD,
        )

        self.client.force_login(self.admin)

    def create_ctv(
        self,
        *,
        name="Pipeline CTV",
        username="ctv_user",
        email="ctv@example.test",
        status="active",
        password=TEST_PASSWORD,
    ):
        response = self.client.post(
            "/api/v1/admin/ctv/",
            data=json.dumps({
                "name": name,
                "status": status,
                "ctv_username": username,
                "ctv_email": email,
                "ctv_password": password,
                "ctv_password_confirm": password,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)

        return Pipeline.objects.select_related("ctv").get(
            name=name
        )

    def test_create_ctv_with_pipeline_and_audit_log(self):
        pipeline = self.create_ctv()

        self.assertEqual(pipeline.ctv.username, "ctv_user")
        self.assertEqual(pipeline.ctv.email, "ctv@example.test")
        self.assertFalse(pipeline.ctv.is_staff)
        self.assertFalse(pipeline.ctv.is_superuser)
        self.assertTrue(
            pipeline.ctv.check_password(TEST_PASSWORD)
        )
        self.assertIsNone(pipeline.ctv.last_login)

        audit = CTVAdminAuditLog.objects.get(
            action=CTVAdminAuditLog.Action.CREATE_CTV
        )

        self.assertEqual(audit.admin_id, self.admin.pk)
        self.assertEqual(audit.admin_username, "ctv_admin")
        self.assertEqual(audit.pipeline_id, pipeline.pk)
        self.assertEqual(audit.pipeline_name, pipeline.name)
        self.assertEqual(audit.ctv_id, pipeline.ctv_id)
        self.assertEqual(audit.ctv_username, "ctv_user")

    def test_list_uses_actual_last_login_and_never_returns_secrets(self):
        pipeline = self.create_ctv()

        ctv_client = Client()
        login_response = ctv_client.post(
            "/api/v1/auth/login/",
            data=json.dumps({
                "username": pipeline.ctv.username,
                "password": TEST_PASSWORD,
            }),
            content_type="application/json",
        )

        self.assertEqual(login_response.status_code, 200)

        response = self.client.get(
            "/api/v1/admin/ctv/?page=1&page_size=10"
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["data"]), 1)

        item = payload["data"][0]

        self.assertEqual(item["pipeline"]["id"], str(pipeline.pk))
        self.assertEqual(item["pipeline"]["name"], pipeline.name)
        self.assertEqual(item["pipeline"]["status"], "active")
        self.assertEqual(item["ctv"]["username"], "ctv_user")
        self.assertEqual(item["ctv"]["email"], "ctv@example.test")
        self.assertTrue(item["ctv"]["is_active"])
        self.assertIsNotNone(item["ctv"]["last_login"])

        content = response.content.decode().lower()

        self.assertNotIn("password", content)
        self.assertNotIn("cookie", content)
        self.assertNotIn("token", content)

    def test_search_by_username_email_and_pipeline_name(self):
        self.create_ctv(
            name="Alpha Pipeline",
            username="alpha_user",
            email="alpha@example.test",
        )
        self.create_ctv(
            name="Beta Pipeline",
            username="beta_user",
            email="beta@example.test",
        )

        for query in ("alpha_user", "alpha@example.test", "Alpha"):
            with self.subTest(query=query):
                response = self.client.get(
                    "/api/v1/admin/ctv/",
                    {"search": query},
                )

                self.assertEqual(response.status_code, 200)

                payload = response.json()

                self.assertEqual(len(payload["data"]), 1)
                self.assertEqual(
                    payload["data"][0]["ctv"]["username"],
                    "alpha_user",
                )

    def test_status_filter_and_pagination(self):
        pipelines = [
            self.create_ctv(
                name=f"Pipeline {index}",
                username=f"ctv_{index}",
                email=f"ctv_{index}@example.test",
            )
            for index in range(3)
        ]

        response = self.client.get(
            "/api/v1/admin/ctv/",
            {"page": 1, "page_size": 2},
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        self.assertEqual(payload["pagination"]["total"], 3)
        self.assertEqual(payload["pagination"]["total_pages"], 2)
        self.assertTrue(payload["pagination"]["has_next"])
        self.assertEqual(len(payload["data"]), 2)

        response = self.client.get(
            "/api/v1/admin/ctv/",
            {"page": 2, "page_size": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)

        response = self.client.patch(
            f"/api/v1/admin/ctv/{pipelines[0].pk}/status/",
            data=json.dumps({"status": "disabled"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            "/api/v1/admin/ctv/",
            {"status": "disabled"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)
        self.assertEqual(
            response.json()["data"][0]["pipeline"]["id"],
            str(pipelines[0].pk),
        )

        response = self.client.get(
            "/api/v1/admin/ctv/",
            {"status": "active"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 2)

    def test_duplicate_username_does_not_create_orphan_ctv(self):
        self.create_ctv(
            name="Original Pipeline",
            username="duplicate_user",
        )

        User = get_user_model()
        user_count = User.objects.count()

        response = self.client.post(
            "/api/v1/admin/ctv/",
            data=json.dumps({
                "name": "Second Pipeline",
                "status": "active",
                "ctv_username": "duplicate_user",
                "ctv_email": "second@example.test",
                "ctv_password": TEST_PASSWORD,
                "ctv_password_confirm": TEST_PASSWORD,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            Pipeline.objects.filter(
                name="Second Pipeline"
            ).exists()
        )
        self.assertEqual(User.objects.count(), user_count)

    def test_lock_blocks_workspace_and_unlock_restores_access(self):
        pipeline = self.create_ctv()

        ctv_client = Client()
        ctv_client.force_login(pipeline.ctv)

        response = ctv_client.get("/api/v1/ctv/workspace/")
        self.assertEqual(response.status_code, 200)

        response = self.client.patch(
            f"/api/v1/admin/ctv/{pipeline.pk}/status/",
            data=json.dumps({"status": "disabled"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        pipeline.refresh_from_db()
        pipeline.ctv.refresh_from_db()

        self.assertEqual(pipeline.status, Pipeline.Status.DISABLED)
        self.assertFalse(pipeline.ctv.is_active)

        response = ctv_client.get("/api/v1/ctv/workspace/")
        self.assertEqual(response.status_code, 403)

        self.assertTrue(
            CTVAdminAuditLog.objects.filter(
                action=CTVAdminAuditLog.Action.LOCK_CTV,
                pipeline_id=pipeline.pk,
            ).exists()
        )

        response = self.client.patch(
            f"/api/v1/admin/ctv/{pipeline.pk}/status/",
            data=json.dumps({"status": "active"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        pipeline.refresh_from_db()
        pipeline.ctv.refresh_from_db()

        self.assertEqual(pipeline.status, Pipeline.Status.ACTIVE)
        self.assertTrue(pipeline.ctv.is_active)

        response = ctv_client.get("/api/v1/ctv/workspace/")
        self.assertEqual(response.status_code, 200)

        self.assertTrue(
            CTVAdminAuditLog.objects.filter(
                action=CTVAdminAuditLog.Action.UNLOCK_CTV,
                pipeline_id=pipeline.pk,
            ).exists()
        )

    def test_reset_password_validation_and_audit(self):
        pipeline = self.create_ctv()

        response = self.client.post(
            f"/api/v1/admin/ctv/{pipeline.pk}/password/",
            data=json.dumps({
                "new_password": "123",
                "confirm_password": "123",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            CTVAdminAuditLog.objects.filter(
                action=CTVAdminAuditLog.Action.RESET_PASSWORD
            ).exists()
        )

        response = self.client.post(
            f"/api/v1/admin/ctv/{pipeline.pk}/password/",
            data=json.dumps({
                "new_password": NEW_PASSWORD,
                "confirm_password": "Mismatch#2026",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            f"/api/v1/admin/ctv/{pipeline.pk}/password/",
            data=json.dumps({
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        pipeline.ctv.refresh_from_db()

        self.assertTrue(
            pipeline.ctv.check_password(NEW_PASSWORD)
        )
        self.assertNotIn(
            NEW_PASSWORD,
            response.content.decode(),
        )

        audit = CTVAdminAuditLog.objects.get(
            action=CTVAdminAuditLog.Action.RESET_PASSWORD
        )

        self.assertEqual(audit.pipeline_id, pipeline.pk)
        self.assertEqual(audit.ctv_username, pipeline.ctv.username)
        self.assertEqual(audit.admin_id, self.admin.pk)

    def test_audit_log_endpoint_requires_super_admin(self):
        pipeline = self.create_ctv()

        self.client.patch(
            f"/api/v1/admin/ctv/{pipeline.pk}/status/",
            data=json.dumps({"status": "disabled"}),
            content_type="application/json",
        )

        response = self.client.get(
            "/api/v1/admin/ctv/audit-log/"
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        self.assertTrue(payload["success"])
        self.assertEqual(
            [item["action"] for item in payload["data"]],
            ["lock_ctv", "create_ctv"],
        )
        self.assertEqual(
            payload["data"][0]["admin"]["username"],
            "ctv_admin",
        )
        self.assertIsNotNone(
            payload["data"][0]["created_at"]
        )

        content = response.content.decode().lower()

        self.assertNotIn("password", content)
        self.assertNotIn("cookie", content)
        self.assertNotIn("token", content)

        ctv_client = Client()
        ctv_client.force_login(pipeline.ctv)

        response = ctv_client.get(
            "/api/v1/admin/ctv/audit-log/"
        )
        self.assertEqual(response.status_code, 403)

    def test_only_super_admin_can_access_and_manage_ctv(self):
        User = get_user_model()

        staff_user = User.objects.create_user(
            username="staff_only",
            email="staff@example.test",
            password=TEST_PASSWORD,
            is_staff=True,
            is_superuser=False,
        )

        staff_client = Client()
        staff_client.force_login(staff_user)

        response = staff_client.get("/api/v1/admin/ctv/")
        self.assertEqual(response.status_code, 403)

        response = staff_client.post(
            "/api/v1/admin/ctv/",
            data=json.dumps({
                "name": "Blocked Pipeline",
                "status": "active",
                "ctv_username": "blocked_ctv",
                "ctv_email": "blocked@example.test",
                "ctv_password": TEST_PASSWORD,
                "ctv_password_confirm": TEST_PASSWORD,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Pipeline.objects.filter(
                name="Blocked Pipeline"
            ).exists()
        )

        pipeline = self.create_ctv(
            name="Managed Pipeline",
            username="managed_ctv",
        )

        ctv_client = Client()
        ctv_client.force_login(pipeline.ctv)

        response = ctv_client.get("/api/v1/admin/ctv/")
        self.assertEqual(response.status_code, 403)

        response = ctv_client.patch(
            f"/api/v1/admin/ctv/{pipeline.pk}/status/",
            data=json.dumps({"status": "disabled"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

        anonymous = Client()

        response = anonymous.get("/api/v1/admin/ctv/")
        self.assertEqual(response.status_code, 403)
