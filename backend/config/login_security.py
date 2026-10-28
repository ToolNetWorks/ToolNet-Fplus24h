"""
ToolNet Publisher - Login Security

Persistent login attempt tracking using Neon PostgreSQL.
"""

from datetime import timedelta

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)

AXES_LOCKOUT_PARAMETERS = [
    ["username", "ip_address"],
]

AXES_HANDLER = (
    "axes.handlers.database.AxesDatabaseHandler"
)

AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_RETRY_AFTER_HEADER = True
