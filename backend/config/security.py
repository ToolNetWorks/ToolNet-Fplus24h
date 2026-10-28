"""
ToolNet Publisher - Security Configuration
Cloudflare Tunnel HTTPS support.
"""

DEBUG = False

ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    ".trycloudflare.com",
]

CSRF_TRUSTED_ORIGINS = [
    "https://*.trycloudflare.com",
]

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True

SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)
