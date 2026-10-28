import json
from urllib.parse import urlsplit
MAX_COOKIE_FILE_SIZE = 64 * 1024
MAX_COOKIES = 100
FACEBOOK_DOMAINS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
}
REQUIRED_SESSION_COOKIES = {
    "c_user",
    "xs",
}
class CookieFileError(ValueError):
    pass
def parse_facebook_cookie_file(content: bytes) -> list[dict]:
    if not content:
        raise CookieFileError("File cookie rỗng.")
    if len(content) > MAX_COOKIE_FILE_SIZE:
        raise CookieFileError("File cookie vượt quá 64 KB.")
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CookieFileError(
            "File không phải JSON hợp lệ."
        ) from exc
    if not isinstance(payload, dict):
        raise CookieFileError("JSON phải là object.")
    url = payload.get("url", "")
    parsed_url = urlsplit(url) if isinstance(url, str) else None
    if (
        parsed_url is None
        or parsed_url.scheme != "https"
        or parsed_url.hostname not in FACEBOOK_DOMAINS
        or parsed_url.username
        or parsed_url.password
    ):
        raise CookieFileError("URL Facebook không hợp lệ.")
    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        raise CookieFileError("Thiếu danh sách cookies.")
    if not 1 <= len(cookies) <= MAX_COOKIES:
        raise CookieFileError(
            "Số lượng cookie không hợp lệ."
        )
    normalized = []
    names = set()
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise CookieFileError(
                "Cookie phải là object."
            )
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain")
        path = cookie.get("path", "/")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
            or not value
            or not isinstance(domain, str)
            or domain.lstrip(".").lower() != "facebook.com"
            or not isinstance(path, str)
            or not path.startswith("/")
            or not cookie.get("secure", False)
            or name in names
        ):
            raise CookieFileError(
                "Cookie không hợp lệ hoặc bị trùng."
            )
        names.add(name)
        normalized.append({
            "name": name,
            "value": value,
            "domain": ".facebook.com",
            "path": path,
            "secure": True,
            "httpOnly": bool(cookie.get("httpOnly", False)),
            "sameSite": cookie.get("sameSite", "Lax"),
        })
    if not REQUIRED_SESSION_COOKIES.issubset(names):
        raise CookieFileError(
            "File thiếu cookie phiên đăng nhập cần thiết."
        )
    return normalized
