from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from modules.pipelines.models import Pipeline
from modules.pipelines.services import (
    create_pipeline_with_ctv,
)


TEST_PASSWORD = "StrongTestPass#2026"


class AdminCTVTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_superuser(
            username="test_admin",
            email="admin@example.test",
            password=TEST_PASSWORD,
        )

        self.client.force_login(self.admin)

    def create_pipeline(self):
        response = self.client.post(
            reverse("admin:pipelines_pipeline_add"),
            {
                "name": "Test Pipeline",
                "status": "active",
                "ctv_username": "test_ctv",
                "ctv_email": "ctv@example.test",
                "ctv_password": TEST_PASSWORD,
                "ctv_password_confirm": TEST_PASSWORD,
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)

        return Pipeline.objects.get(
            name="Test Pipeline"
        )

    def test_admin_creates_pipeline_and_ctv(self):
        pipeline = self.create_pipeline()

        self.assertEqual(
            pipeline.ctv.username,
            "test_ctv",
        )

        self.assertTrue(
            pipeline.ctv.check_password(TEST_PASSWORD)
        )

        self.assertFalse(pipeline.ctv.is_staff)

    def test_admin_changes_ctv_password(self):
        pipeline = self.create_pipeline()

        url = reverse(
            "admin:auth_user_password_change",
            args=[pipeline.ctv_id],
        )

        new_password = "NewStrongPass#2026"

        response = self.client.post(
            url,
            {
                "password1": new_password,
                "password2": new_password,
            },
        )

        self.assertEqual(response.status_code, 302)

        pipeline.ctv.refresh_from_db()

        self.assertTrue(
            pipeline.ctv.check_password(new_password)
        )

    def test_admin_deletes_pipeline_and_ctv(self):
        pipeline = self.create_pipeline()

        ctv_id = pipeline.ctv_id
        pipeline_id = pipeline.pk

        response = self.client.post(
            reverse(
                "admin:pipelines_pipeline_delete",
                args=[pipeline_id],
            ),
            {"post": "yes"},
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            Pipeline.objects.filter(
                pk=pipeline_id
            ).exists()
        )

        User = get_user_model()

        self.assertFalse(
            User.objects.filter(pk=ctv_id).exists()
        )


class CTVAccessTests(TestCase):

    def setUp(self):
        self.pipeline = create_pipeline_with_ctv(
            pipeline=Pipeline(name="CTV Workspace"),
            username="workspace_ctv",
            email="workspace@example.test",
            password=TEST_PASSWORD,
        )

    def test_ctv_can_login(self):
        response = self.client.post(
            reverse("ctv_login"),
            {
                "username": "workspace_ctv",
                "password": TEST_PASSWORD,
            },
        )

        self.assertRedirects(
            response,
            reverse("ctv_workspace"),
        )

        response = self.client.get(
            reverse("ctv_workspace")
        )

        self.assertContains(
            response,
            "CTV Workspace",
        )

    def test_disabled_pipeline_blocks_access(self):
        self.pipeline.status = Pipeline.Status.DISABLED
        self.pipeline.save(update_fields=["status"])

        response = self.client.post(
            reverse("ctv_login"),
            {
                "username": "workspace_ctv",
                "password": TEST_PASSWORD,
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )
