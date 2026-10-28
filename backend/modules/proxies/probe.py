"""
Proxy health check via a fixed HTTPS egress-IP endpoint.
Security:
- No user-defined test URLs.
- Reject non-public proxy addresses.
- Connect to pinned, validated DNS results.
- Verify TLS certificate of destination.
- Never log or return credentials.
"""
import base64
import http.client
import ipaddress
import json
import socket
import ssl
import struct
import time
from dataclasses import dataclass

TARGET_HOST = "api.ipify.org"
TARGET_PORT = 443
TIMEOUT_SECONDS = 10
MAX_BODY = 1024
MAX_CONNECT_HEADERS = 8192


class ProxyProbeError(Exception):
    pass


@dataclass(frozen=True)
class ProbeResult:
    healthy: bool
    exit_ip: str | None
    latency_ms: int
    message: str


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("Deadline reached")
    return value


def public_addresses(host, port):
    try:
        answers = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ProxyProbeError(
            "Không phân giải được hostname Proxy."
        ) from exc
    if not answers:
        raise ProxyProbeError(
            "Không phân giải được hostname Proxy."
        )
    results = []
    for family, kind, protocol, _, address in answers:
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise ProxyProbeError(
                "Loại địa chỉ Proxy không được hỗ trợ."
            )
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global:
            raise ProxyProbeError(
                "Proxy trỏ đến IP không công khai."
            )
        results.append(
            (family, kind, protocol, address)
        )
    return results


def open_pinned_socket(host, port, deadline):
    last_error = None
    for family, kind, protocol, address in public_addresses(
        host, port
    ):
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(remaining(deadline))
            # Use the validated DNS result directly.
            # No second DNS lookup before connect.
            sock.connect(address)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise ProxyProbeError(
        "Không kết nối được đến Proxy."
    ) from last_error


def read_exact(sock, count, deadline):
    result = bytearray()
    while len(result) < count:
        sock.settimeout(remaining(deadline))
        block = sock.recv(count - len(result))
        if not block:
            raise ProxyProbeError(
                "Proxy đóng kết nối sớm."
            )
        result.extend(block)
    return bytes(result)


def http_connect(sock, username, password, deadline):
    headers = [
        f"CONNECT {TARGET_HOST}:{TARGET_PORT} HTTP/1.1",
        f"Host: {TARGET_HOST}:{TARGET_PORT}",
    ]
    if username and password:
        token = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        headers.append(
            f"Proxy-Authorization: Basic {token}"
        )
    request = "\r\n".join(headers) + "\r\n\r\n"
    sock.settimeout(remaining(deadline))
    sock.sendall(request.encode("ascii"))
    response = bytearray()
    while not response.endswith(b"\r\n\r\n"):
        if len(response) >= MAX_CONNECT_HEADERS:
            raise ProxyProbeError(
                "Phản hồi Proxy quá dài."
            )
        response.extend(
            read_exact(sock, 1, deadline)
        )
    status = bytes(response).split(
        b"\r\n", 1
    )[0].split(b" ", 2)
    if (
        len(status) < 2
        or status[0] not in (
            b"HTTP/1.0",
            b"HTTP/1.1",
        )
    ):
        raise ProxyProbeError(
            "Phản hồi HTTP Proxy không hợp lệ."
        )
    if status[1] == b"407":
        raise ProxyProbeError(
            "Proxy từ chối xác thực."
        )
    if status[1] != b"200":
        raise ProxyProbeError(
            "Proxy không cho phép kết nối HTTPS."
        )


def socks5_connect(sock, username, password, deadline):
    has_auth = bool(username and password)
    sock.settimeout(remaining(deadline))
    sock.sendall(
        b"\x05\x01" +
        (b"\x02" if has_auth else b"\x00")
    )
    reply = read_exact(sock, 2, deadline)
    expected = (
        b"\x05\x02"
        if has_auth
        else b"\x05\x00"
    )
    if reply != expected:
        raise ProxyProbeError(
            "SOCKS5 từ chối phương thức xác thực."
        )
    if has_auth:
        user_bytes = username.encode("utf-8")
        pass_bytes = password.encode("utf-8")
        if not (
            1 <= len(user_bytes) <= 255
            and 1 <= len(pass_bytes) <= 255
        ):
            raise ProxyProbeError(
                "Thông tin xác thực SOCKS5 quá dài."
            )
        auth_request = (
            b"\x01" +
            bytes([len(user_bytes)]) +
            user_bytes +
            bytes([len(pass_bytes)]) +
            pass_bytes
        )
        sock.settimeout(remaining(deadline))
        sock.sendall(auth_request)
        if read_exact(sock, 2, deadline) != b"\x01\x00":
            raise ProxyProbeError(
                "SOCKS5 từ chối xác thực."
            )
    target = TARGET_HOST.encode("ascii")
    command = (
        b"\x05\x01\x00\x03" +
        bytes([len(target)]) +
        target +
        struct.pack("!H", TARGET_PORT)
    )
    sock.settimeout(remaining(deadline))
    sock.sendall(command)
    reply = read_exact(sock, 4, deadline)
    if reply[:3] != b"\x05\x00\x00":
        raise ProxyProbeError(
            "SOCKS5 không tạo được tunnel."
        )
    if reply[3] == 1:
        read_exact(sock, 6, deadline)
    elif reply[3] == 4:
        read_exact(sock, 18, deadline)
    elif reply[3] == 3:
        length = read_exact(sock, 1, deadline)[0]
        read_exact(sock, length + 2, deadline)
    else:
        raise ProxyProbeError(
            "Phản hồi SOCKS5 không hợp lệ."
        )


def fetch_exit_ip(sock, deadline):
    sock.settimeout(remaining(deadline))
    request = (
        "GET /?format=json HTTP/1.1\r\n"
        f"Host: {TARGET_HOST}\r\n"
        "Accept: application/json\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = http.client.HTTPResponse(sock)
    try:
        response.begin()
        if response.status != 200:
            raise ProxyProbeError(
                "Dịch vụ xác minh IP không phản hồi thành công."
            )
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ProxyProbeError(
                "Phản hồi xác minh IP quá dài."
            )
        try:
            data = json.loads(body)
            ip = ipaddress.ip_address(data["ip"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ProxyProbeError(
                "Không xác minh được IP đầu ra."
            ) from exc
        if not ip.is_global:
            raise ProxyProbeError(
                "IP đầu ra không phải IP công khai."
            )
        return str(ip)
    finally:
        response.close()


def perform_probe(protocol, host, port, credentials, deadline):
    if protocol not in {"http", "https", "socks5"}:
        raise ProxyProbeError(
            "Giao thức Proxy không được hỗ trợ."
        )
    credentials = credentials or {}
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    sock = open_pinned_socket(host, port, deadline)
    try:
        if protocol == "https":
            sock.settimeout(remaining(deadline))
            sock = ssl.create_default_context().wrap_socket(
                sock,
                server_hostname=host,
            )
        if protocol in {"http", "https"}:
            http_connect(
                sock, username, password, deadline
            )
        else:
            socks5_connect(
                sock, username, password, deadline
            )
        # TLS to fixed destination through the proxy.
        # This verifies the remote endpoint certificate.
        sock.settimeout(remaining(deadline))
        sock = ssl.create_default_context().wrap_socket(
            sock,
            server_hostname=TARGET_HOST,
        )
        return fetch_exit_ip(sock, deadline)
    finally:
        sock.close()


def check_proxy(protocol, host, port, credentials=None):
    start = time.monotonic()
    deadline = start + TIMEOUT_SECONDS
    try:
        exit_ip = perform_probe(
            protocol,
            host,
            port,
            credentials,
            deadline,
        )
    except ProxyProbeError as exc:
        return ProbeResult(
            healthy=False,
            exit_ip=None,
            latency_ms=round(
                (time.monotonic() - start) * 1000
            ),
            message=str(exc),
        )
    except (
        OSError,
        TimeoutError,
        http.client.HTTPException,
    ):
        return ProbeResult(
            healthy=False,
            exit_ip=None,
            latency_ms=round(
                (time.monotonic() - start) * 1000
            ),
            message=(
                "Không kết nối được hoặc xác minh TLS thất bại."
            ),
        )
    return ProbeResult(
        healthy=True,
        exit_ip=exit_ip,
        latency_ms=round(
            (time.monotonic() - start) * 1000
        ),
        message="Proxy hoạt động. IP đầu ra đã được xác minh.",
    )
