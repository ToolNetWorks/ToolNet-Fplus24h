import re
import unicodedata
from urllib.parse import quote, unquote, urlsplit
from django.core.exceptions import ValidationError
FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "web.facebook.com",
}
def normalize_facebook_group_url(url: str) -> tuple[str, str]:
    if not isinstance(url, str) or not url.strip():
        raise ValidationError(
            "Vui lòng nhập link Facebook Group."
        )
    try:
        parsed = urlsplit(url.strip())
    except ValueError as exc:
        raise ValidationError(
            "URL không hợp lệ."
        ) from exc
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in FACEBOOK_HOSTS
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.netloc.count("@") > 0
    ):
        raise ValidationError(
            "Chỉ hỗ trợ link HTTPS của Facebook Group."
        )
    try:
        if parsed.port is not None:
            raise ValidationError(
                "URL không được chứa port."
            )
    except ValueError as exc:
        raise ValidationError(
            "Port không hợp lệ."
        ) from exc
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2 or parts[0].lower() != "groups":
        raise ValidationError(
            "Link phải có dạng facebook.com/groups/ten-group/"
        )
    group_key = unicodedata.normalize(
        "NFC",
        unquote(parts[1]),
    )
    if (
        not 1 <= len(group_key) <= 150
        or group_key in {".", ".."}
        or not re.fullmatch(r"[\w.-]+", group_key, re.UNICODE)
    ):
        raise ValidationError(
            "Mã hoặc tên Group không hợp lệ."
        )
    group_key = group_key.casefold()
    canonical_url = (
        "https://www.facebook.com/groups/"
        + quote(group_key, safe="-._~")
        + "/"
    )
    return group_key, canonical_url
