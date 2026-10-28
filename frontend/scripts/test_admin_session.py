import getpass
import json
import sys
from http.cookies import SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:3000"


def request(path, method="GET", data=None, headers=None):
    payload = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
    req = Request(
        BASE_URL + path,
        data=payload,
        headers=headers or {},
        method=method,
    )
    try:
        return urlopen(req, timeout=15)
    except HTTPError as exc:
        return exc


def get_cookie(response, name):
    for header in response.headers.get_all("Set-Cookie", []):
        cookie = SimpleCookie()
        cookie.load(header)
        if name in cookie:
            return cookie[name].value
    return None


def main():
    print("=== CSRF TEST ===")
    response = request("/api/v1/auth/csrf/")
    if response.status != 200:
        sys.exit(f"CSRF FAILED: HTTP {response.status}")
    csrf_data = json.loads(response.read())
    csrf_token = csrf_data.get("csrfToken")
    csrf_cookie = get_cookie(response, "csrftoken")
    if not csrf_token or not csrf_cookie:
        sys.exit("CSRF COOKIE OR TOKEN MISSING")
    print("CSRF: PASS")

    username = input("Admin username: ").strip()
    password = getpass.getpass("Admin password: ")
    if not username or not password:
        sys.exit("Missing credentials")

    print("=== LOGIN TEST ===")
    response = request(
        "/api/v1/auth/login/",
        method="POST",
        data={
            "username": username,
            "password": password,
        },
        headers={
            "Content-Type": "application/json",
            "X-CSRFToken": csrf_token,
            "Cookie": f"csrftoken={csrf_cookie}",
        },
    )
    password = ""
    if response.status != 200:
        sys.exit(f"LOGIN FAILED: HTTP {response.status}")
    session = get_cookie(response, "sessionid")
    if not session:
        sys.exit("SESSION COOKIE MISSING")
    print("ADMIN LOGIN: PASS")

    print("=== SESSION TEST ===")
    headers = {
        "Cookie": f"sessionid={session}",
    }
    response = request(
        "/api/v1/auth/me/",
        headers=headers,
    )
    if response.status != 200:
        sys.exit(f"SESSION FAILED: HTTP {response.status}")
    print("ADMIN SESSION: PASS")

    print("=== DASHBOARD TEST ===")
    response = request("/", headers=headers)
    if response.status != 200:
        sys.exit(f"DASHBOARD FAILED: HTTP {response.status}")
    print("DASHBOARD ACCESS: PASS")

    print("AUTHENTICATION E2E: PASSED")


if __name__ == "__main__":
    try:
        main()
    except (URLError, TimeoutError, ValueError) as exc:
        print("TEST FAILED:", type(exc).__name__)
        sys.exit(1)
