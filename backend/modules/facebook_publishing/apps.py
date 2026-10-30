from django.apps import AppConfig


class FacebookPublishingConfig(AppConfig):
    default_auto_field = 'django.db.models.UUIDField'
    name = 'modules.facebook_publishing'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from .models import WorkerResultState  # noqa: F401
