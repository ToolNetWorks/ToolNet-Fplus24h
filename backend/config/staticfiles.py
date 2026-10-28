"""
ToolNet Publisher - Static Files Configuration

WhiteNoise serves collected static assets.
Gunicorn serves the Django application.
"""

from pathlib import Path


def configure_staticfiles(settings):
    base_dir = Path(settings["BASE_DIR"])

    middleware = list(settings["MIDDLEWARE"])

    whitenoise = (
        "whitenoise.middleware.WhiteNoiseMiddleware"
    )

    if whitenoise not in middleware:
        security = (
            "django.middleware.security.SecurityMiddleware"
        )

        if security not in middleware:
            raise RuntimeError(
                "SecurityMiddleware is required."
            )

        index = middleware.index(security)
        middleware.insert(index + 1, whitenoise)

    settings["MIDDLEWARE"] = middleware

    settings["STATIC_URL"] = "/static/"

    settings["STATIC_ROOT"] = (
        base_dir / "staticfiles"
    )

    storages = dict(
        settings.get("STORAGES", {})
    )

    storages["staticfiles"] = {
        "BACKEND": (
            "whitenoise.storage."
            "CompressedManifestStaticFilesStorage"
        )
    }

    settings["STORAGES"] = storages

    return settings
