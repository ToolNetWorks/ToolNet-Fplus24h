from django.apps import AppConfig


class PublishingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modules.publishing"
    label = "publishing"
    verbose_name = "Pipeline Publishing"
