import os

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured


def add_neon_database(databases, base_dir):
    env_file = base_dir.parent / ".env"
    load_dotenv(env_file)

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ImproperlyConfigured(
            "DATABASE_URL chưa được cấu hình trong .env"
        )

    neon_cfg = dj_database_url.parse(
        database_url,
        conn_max_age=60,
        conn_health_checks=True,
        ssl_require=True,
    )
    direct_host = neon_cfg.get("HOST", "").replace("-pooler.", ".")
    neon_cfg["TEST"] = {
        "HOST": direct_host,
        "NAME": "test_neondb",
    }
    databases["neon"] = neon_cfg

    return databases
