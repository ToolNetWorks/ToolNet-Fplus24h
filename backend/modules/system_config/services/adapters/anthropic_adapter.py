import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Dict, Any, Tuple, Optional

from .base import BaseAIAdapter
from ...crypto import sanitize_text


class AnthropicAdapter(BaseAIAdapter):
    """Adapter for Anthropic Claude Messages API."""

    def _normalize_url(self, base_url: str) -> str:
        url = (base_url or "https://api.anthropic.com").strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"
        if not url.endswith("/v1/messages"):
            url = f"{url.rstrip('/').removesuffix('/v1')}/v1/messages"
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Endpoint URL không có host hợp lệ.")
        return url

    def _build_headers(self, api_key: str) -> Dict[str, str]:
        return {
            "x-api-key": api_key.strip(),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def test_connection(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 25,
    ) -> Dict[str, Any]:
        start = time.monotonic()
        try:
            url = self._normalize_url(base_url)
            headers = self._build_headers(api_key)
            payload = {
                "model": model.strip(),
                "max_tokens": 20,
                "messages": [
                    {"role": "user", "content": "Ping test connection. Reply: OK"}
                ],
            }
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = Request(url, data=data, headers=headers, method="POST")

            with urlopen(req, timeout=timeout) as resp:
                status_code = resp.status
                raw = resp.read(60_000).decode("utf-8", "ignore")
                latency_ms = int((time.monotonic() - start) * 1000)

                if status_code != 200:
                    return {
                        "success": False,
                        "latency_ms": latency_ms,
                        "error": f"HTTP status {status_code}",
                        "model": model,
                    }

                parsed = json.loads(raw)
                content = parsed.get("content", [])
                reply_text = ""
                for part in content:
                    if part.get("type") == "text":
                        reply_text += part.get("text", "")

                return {
                    "success": bool(reply_text.strip()),
                    "latency_ms": latency_ms,
                    "error": "",
                    "model": model,
                    "response_received": bool(reply_text.strip()),
                }

        except HTTPError as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            try:
                err_body = e.read().decode("utf-8", "ignore")
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message") or err_body
            except Exception:
                msg = f"HTTP {e.code}: {e.reason}"
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": "Provider không phản hồi hợp lệ. Kiểm tra endpoint, model và credentials.",
                "model": model,
            }
        except (URLError, TimeoutError, OSError) as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": "Provider không phản hồi hợp lệ. Kiểm tra endpoint, model và credentials.",
                "model": model,
            }
        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": "Provider không phản hồi hợp lệ. Kiểm tra endpoint, model và credentials.",
                "model": model,
            }

    def generate_completion(
        self,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        system_instruction: Optional[str] = None,
        timeout: int = 60,
    ) -> Tuple[str, str]:
        url = self._normalize_url(base_url)
        headers = self._build_headers(api_key)

        payload = {
            "model": model.strip(),
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_instruction:
            payload["system"] = system_instruction

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        for attempt in range(3):
            req = Request(url, data=data, headers=headers, method="POST")
            try:
                with urlopen(req, timeout=timeout) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    raw = resp.read(120_000).decode("utf-8", "ignore").strip()
                    parsed = json.loads(raw)
                content = parsed.get("content", [])
                reply = "".join(part.get("text", "") for part in content if part.get("type") == "text")
                if not reply.strip():
                    raise ValueError("Không nhận được nội dung từ Anthropic.")
                return reply.strip(), model
            except HTTPError as e:
                if attempt < 2 and e.code in (429, 502, 503, 504):
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError(sanitize_text(f"Anthropic HTTP {e.code}")) from None
            except (TimeoutError, OSError):
                if attempt < 2:
                    time.sleep(3)
                    continue
                raise RuntimeError("Anthropic Timeout / Network error") from None
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                raise RuntimeError(sanitize_text(f"Anthropic error: {str(e)}")) from None

        raise RuntimeError("Không thể tạo caption qua Anthropic sau 3 lần thử.")
