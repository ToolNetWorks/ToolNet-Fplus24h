import uuid
from django.db import models
from .crypto import encrypt_secret, decrypt_secret, mask_secret


class AIProviderType(models.TextChoices):
    TOOLNET = "toolnet", "ToolNetAPI"
    OPENAI_COMPATIBLE = "openai_compatible", "OpenAI-compatible (Custom)"
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"
    GEMINI = "gemini", "Google Gemini"
    OPENROUTER = "openrouter", "OpenRouter"
    GROQ = "groq", "Groq"


class AIProvider(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Tên Provider", max_length=120)
    provider_type = models.CharField(
        "Loại Provider",
        max_length=32,
        choices=AIProviderType.choices,
        default=AIProviderType.OPENAI_COMPATIBLE,
        db_index=True,
    )
    base_url = models.CharField("Base URL", max_length=500)
    api_key_encrypted = models.TextField("API Key (Encrypted)", blank=True, default="")
    api_keys_encrypted = models.TextField(
        "Danh sách API Keys (Encrypted JSON)", blank=True, default=""
    )
    default_model = models.CharField("Model mặc định", max_length=120)
    available_models = models.JSONField("Danh sách Models", default=list, blank=True)
    is_active = models.BooleanField("Đang hoạt động", default=True, db_index=True)
    is_default = models.BooleanField("Provider mặc định", default=False, db_index=True)
    priority = models.PositiveIntegerField("Độ ưu tiên (1 là cao nhất)", default=10, db_index=True)
    timeout_seconds = models.PositiveIntegerField("Timeout (giây)", default=60)
    last_tested_at = models.DateTimeField("Kiểm tra lần cuối", null=True, blank=True)
    last_status = models.CharField("Trạng thái", max_length=32, default="untested")
    last_error_message = models.TextField("Lỗi gần nhất", blank=True, default="")
    last_latency_ms = models.PositiveIntegerField("Độ trễ (ms)", null=True, blank=True)
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)
    updated_at = models.DateTimeField("Ngày cập nhật", auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["is_default"], condition=models.Q(is_default=True), name="syscfg_one_default_provider")]
        db_table = "system_config_ai_providers"
        verbose_name = "Nhà cung cấp AI"
        verbose_name_plural = "Các nhà cung cấp AI"
        ordering = ["priority", "-is_default", "created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_provider_type_display()})"

    def set_api_key(self, raw_key: str):
        if raw_key and raw_key.strip():
            self.api_key_encrypted = encrypt_secret(raw_key.strip())

    def get_api_key(self) -> str:
        return decrypt_secret(self.api_key_encrypted)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key_encrypted and self.api_key_encrypted.strip())

    @property
    def masked_api_key(self) -> str:
        raw = self.get_api_key()
        return mask_secret(raw) if raw else ""


class StorageConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account_id = models.CharField("Account ID", max_length=120, blank=True, default="")
    endpoint_url = models.CharField("Endpoint URL", max_length=500, blank=True, default="")
    bucket_name = models.CharField("Bucket Name", max_length=120, blank=True, default="")
    access_key_id = models.TextField("Access Key ID (Encrypted)", blank=True, default="")
    secret_access_key_encrypted = models.TextField("Secret Key (Encrypted)", blank=True, default="")
    is_active = models.BooleanField("Đang kích hoạt", default=True)
    last_tested_at = models.DateTimeField("Kiểm tra lần cuối", null=True, blank=True)
    last_status = models.CharField("Trạng thái", max_length=32, default="untested")
    last_error_message = models.TextField("Lỗi gần nhất", blank=True, default="")
    last_latency_ms = models.PositiveIntegerField("Độ trễ (ms)", null=True, blank=True)
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)
    updated_at = models.DateTimeField("Ngày cập nhật", auto_now=True)

    class Meta:
        db_table = "system_config_storage"
        verbose_name = "Cấu hình Cloudflare R2"
        verbose_name_plural = "Cấu hình Cloudflare R2"

    def set_access_key(self, value):
        self.access_key_id = encrypt_secret(value)

    def get_access_key(self):
        return decrypt_secret(self.access_key_id)

    def set_secret_key(self, raw_secret: str):
        if raw_secret and raw_secret.strip():
            self.secret_access_key_encrypted = encrypt_secret(raw_secret.strip())

    def get_secret_key(self) -> str:
        return decrypt_secret(self.secret_access_key_encrypted)

    @property
    def has_secret(self) -> bool:
        return bool(self.secret_access_key_encrypted and self.secret_access_key_encrypted.strip())


class SystemConfigAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_id = models.BigIntegerField("Actor ID", null=True, blank=True)
    actor_username = models.CharField("Actor Username", max_length=150)
    actor_email = models.CharField("Actor Email", max_length=254, blank=True, default="")
    section = models.CharField("Khu vực", max_length=50, db_index=True)
    action = models.CharField("Hành động", max_length=100, db_index=True)
    target_id = models.CharField("Target ID", max_length=100, blank=True, default="")
    target_name = models.CharField("Target Name", max_length=200, blank=True, default="")
    details = models.JSONField("Chi tiết (Đã làm sạch secrets)", default=dict, blank=True)
    ip_address = models.CharField("Địa chỉ IP", max_length=45, blank=True, default="")
    created_at = models.DateTimeField("Thời gian", auto_now_add=True, db_index=True)

    class Meta:
        db_table = "system_config_audit_logs"
        verbose_name = "Audit log cấu hình hệ thống"
        verbose_name_plural = "Audit log cấu hình hệ thống"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["section", "-created_at"], name="syscfg_sec_time_idx"),
            models.Index(fields=["action", "-created_at"], name="syscfg_act_time_idx"),
        ]

    def __str__(self):
        return f"[{self.section}] {self.action} by {self.actor_username} at {self.created_at}"
