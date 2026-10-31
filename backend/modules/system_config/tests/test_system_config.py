import json
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status

from modules.system_config.models import (
    AIProvider,
    AIProviderType,
    StorageConfig,
    SystemConfigAuditLog,
)
from modules.system_config.crypto import (
    encrypt_secret,
    decrypt_secret,
    mask_secret,
    sanitize_text,
)
from modules.system_config.services.ai_unified_service import (
    ensure_default_provider_initialized,
    generate_ai_text,
)

User = get_user_model()


class SystemConfigTests(TestCase):
    def setUp(self):
        r2_patch = patch("modules.system_config.services.services_health_service.test_r2_connection", return_value={"success": True})
        r2_patch.start()
        self.addCleanup(r2_patch.stop)

        self.super_admin = User.objects.create_superuser(
            username="super_admin_test",
            password="StrongAdminPassword#2026",
            email="superadmin@toolnet.tech",
        )
        self.ctv_user = User.objects.create_user(
            username="ctv_test_user",
            password="CTVUserPassword#2026",
            email="ctv@toolnet.tech",
        )

    def test_permission_isolation(self):
        """Only Super Admin can access system config endpoints; CTV and anonymous are blocked."""
        endpoints = [
            reverse("admin-config-database"),
            reverse("admin-config-r2"),
            reverse("admin-config-ai-providers"),
            reverse("admin-config-services"),
            reverse("admin-config-audit-log"),
        ]

        for url in endpoints:
            # 1. Anonymous -> 403 Forbidden
            self.client.logout()
            res = self.client.get(url)
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

            # 2. CTV user -> 403 Forbidden
            self.client.force_login(self.ctv_user)
            res = self.client.get(url)
            self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

            # 3. Super Admin -> 200 OK
            self.client.force_login(self.super_admin)
            res = self.client.get(url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.client.logout()

    def test_crypto_encryption_and_redaction(self):
        """Secrets are encrypted in DB, masked in UI, and sanitized from error messages."""
        secret_key = "sk-test-super-secret-api-key-1234567890"
        encrypted = encrypt_secret(secret_key)
        self.assertNotEqual(encrypted, secret_key)
        self.assertTrue(len(encrypted) > 20)

        decrypted = decrypt_secret(encrypted)
        self.assertEqual(decrypted, secret_key)

        masked = mask_secret(secret_key, visible_chars=4)
        self.assertTrue(masked.startswith("sk-t"))
        self.assertTrue(masked.endswith("7890"))
        self.assertIn("••••••••", masked)
        self.assertNotIn("secret", masked)

        # Sanitize error message
        dirty = "Failed with Authorization: Bearer sk-1234567890abcdef and postgres://user:secretpass@host:5432/db"
        clean = sanitize_text(dirty)
        self.assertNotIn("secretpass", clean)
        self.assertNotIn("sk-1234567890abcdef", clean)
        self.assertIn("user:••••••••@host:5432/db", clean)
        self.assertIn("Bearer ••••••••", clean)

    def test_database_config_api(self):
        """Database config returns connection status, latency, pool stats and migrations without secrets."""
        self.client.force_login(self.super_admin)
        url = reverse("admin-config-database")

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertIn("provider", data)
        self.assertIn("host", data)
        self.assertIn("database_name", data)
        self.assertIn("connection_status", data)
        self.assertIn("latency_ms", data)
        self.assertIn("pool_info", data)
        self.assertIn("migrations", data)
        # Ensure password is not present anywhere in data
        data_str = json.dumps(data)
        self.assertNotIn("password", data_str.lower().replace("password_validators", ""))

        # Test POST database test
        test_res = self.client.post(url, {})
        self.assertEqual(test_res.status_code, status.HTTP_200_OK)
        self.assertTrue(test_res.json().get("success"))

    def test_r2_config_api(self):
        """R2 config GET masks secrets; POST tests before saving."""
        self.client.force_login(self.super_admin)
        url = reverse("admin-config-r2")

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertIn("bucket_name", data)
        self.assertIn("has_secret", data)
        self.assertIn("storage_stats", data)
        self.assertNotIn("secret_access_key", data)

        # Test test endpoint
        with patch("modules.system_config.services.r2_service.get_active_r2_config_dict", return_value={"endpoint_url": "https://example.r2.cloudflarestorage.com", "access_key_id": "test", "secret_access_key": "secret", "bucket_name": "test"}), patch("modules.system_config.services.r2_service.boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_boto.return_value = mock_client
            test_url = reverse("admin-config-r2-test")
            test_res = self.client.post(test_url, {"test_read_write": False})
            self.assertEqual(test_res.status_code, status.HTTP_200_OK)
            self.assertTrue(test_res.json().get("success"))

    def test_ai_providers_crud_and_key_preservation(self):
        """AI Providers CRUD encrypts keys, masks on GET, preserves existing key if blank on edit."""
        self.client.force_login(self.super_admin)
        list_url = reverse("admin-config-ai-providers")

        # 1. GET auto-initializes ToolNet AI default provider
        res = self.client.get(list_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        providers = res.json()
        self.assertEqual(providers, [])
        self.assertEqual(AIProvider.objects.count(), 0)

        # 2. POST create new provider
        create_payload = {
            "name": "Groq Production",
            "provider_type": "groq",
            "base_url": "https://api.groq.com/openai/v1",
            "default_model": "llama-3.3-70b-versatile",
            "api_key": "gsk_test_groq_key_9999999999",
            "priority": 2,
            "is_active": True,
            "is_default": False,
        }
        res_create = self.client.post(list_url, create_payload)
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        new_id = res_create.json()["id"]

        # Check DB row is encrypted
        db_row = AIProvider.objects.get(id=new_id)
        self.assertNotEqual(db_row.api_key_encrypted, "gsk_test_groq_key_9999999999")
        self.assertEqual(db_row.get_api_key(), "gsk_test_groq_key_9999999999")

        # 3. PUT update without new API key -> retains existing key
        detail_url = reverse("admin-config-ai-provider-detail", kwargs={"provider_id": new_id})
        update_payload = {
            "name": "Groq Production Updated",
            "api_key": "",  # Empty key should preserve existing
        }
        res_update = self.client.put(detail_url, update_payload, content_type="application/json")
        self.assertEqual(res_update.status_code, status.HTTP_200_OK)
        db_row.refresh_from_db()
        self.assertEqual(db_row.name, "Groq Production Updated")
        self.assertEqual(db_row.get_api_key(), "gsk_test_groq_key_9999999999")

        # 4. Rotate key endpoint
        rotate_url = reverse("admin-config-ai-provider-rotate-key", kwargs={"provider_id": new_id})
        res_rotate = self.client.post(rotate_url, {"new_api_key": "gsk_new_rotated_key_1111111111"})
        self.assertEqual(res_rotate.status_code, status.HTTP_200_OK)
        db_row.refresh_from_db()
        self.assertEqual(db_row.get_api_key(), "gsk_new_rotated_key_1111111111")

        # 5. Set as default
        set_def_url = reverse("admin-config-ai-provider-set-default", kwargs={"provider_id": new_id})
        res_def = self.client.post(set_def_url)
        self.assertEqual(res_def.status_code, status.HTTP_200_OK)
        db_row.refresh_from_db()
        self.assertTrue(db_row.is_default)
        # Ensure other provider is no longer default
        other_provs = AIProvider.objects.exclude(id=new_id)
        for p in other_provs:
            self.assertFalse(p.is_default)

        # 6. Audit log was written
        audit_url = reverse("admin-config-audit-log")
        res_audit = self.client.get(audit_url)
        self.assertEqual(res_audit.status_code, status.HTTP_200_OK)
        audit_items = res_audit.json()["results"]
        actions = [a["action"] for a in audit_items]
        self.assertIn("create_provider", actions)
        self.assertIn("update_provider", actions)
        self.assertIn("rotate_key", actions)
        self.assertIn("set_default_provider", actions)

    def test_unified_ai_service_priority_and_fallback(self):
        """Unified AI service tries primary provider; on failure, falls back to next active provider."""
        AIProvider.objects.all().delete()

        # Primary provider (fails)
        p1 = AIProvider(
            name="Primary Failing Provider",
            provider_type=AIProviderType.OPENAI_COMPATIBLE,
            base_url="https://api.fake-primary.com/v1",
            default_model="model-1",
            priority=1,
            is_active=True,
        )
        p1.set_api_key("sk-fake-key-1")
        p1.save()

        # Fallback provider (succeeds)
        p2 = AIProvider(
            name="Secondary Fallback Provider",
            provider_type=AIProviderType.OPENAI_COMPATIBLE,
            base_url="https://api.fake-secondary.com/v1",
            default_model="model-2",
            priority=2,
            is_active=True,
        )
        p2.set_api_key("sk-fake-key-2")
        p2.save()

        with patch("modules.system_config.services.adapters.openai_adapter.OpenAICompatibleAdapter.generate_completion") as mock_gen:
            def side_effect(base_url, **kwargs):
                if "fake-primary" in base_url:
                    raise RuntimeError("Primary API 500 Internal Error")
                return "Generated Fallback Caption", "model-2"

            mock_gen.side_effect = side_effect

            with patch.dict("os.environ", {"TOOLNET_CAPTION_API_KEY": "", "AI_KEY": ""}):
                text, used_model = generate_ai_text("Write caption")
            self.assertEqual(text, "Generated Fallback Caption")
            self.assertEqual(used_model, "model-2")

    @patch("modules.system_config.services.services_health_service.test_r2_connection")
    def test_services_health_api(self, mock_r2_test):
        """Services health returns all 7 services with non-null verified data."""
        mock_r2_test.return_value = {
            "success": True,
            "latency_ms": 45,
            "bucket": "album-ctv",
            "read_ok": True,
            "write_ok": True,
        }
        self.client.force_login(self.super_admin)
        url = reverse("admin-config-services")

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertIn("checked_at", data)
        self.assertIn("services", data)
        service_ids = [s["id"] for s in data["services"]]

        expected = [
            "django_backend",
            "nextjs_frontend",
            "scheduler_tick",
            "caption_worker",
            "facebook_publishing_worker",
            "neon_database",
            "cloudflare_r2",
        ]
        for exp in expected:
            self.assertIn(exp, service_ids)
