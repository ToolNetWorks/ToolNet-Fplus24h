import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Dict, Any, Tuple, Optional

from .base import BaseAIAdapter
from ...crypto import sanitize_text


class OpenAICompatibleAdapter(BaseAIAdapter):
    """Adapter for OpenAI, OpenRouter, Groq, ToolNet, and generic OpenAI-compatible APIs."""

    def _normalize_url(self, base_url: str) -> str:
        url = base_url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"
        if not url.endswith("/chat/completions"):
            url = f"{url.rstrip('/')}/chat/completions"
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Endpoint URL không có host hợp lệ.")
        return url

    def _build_headers(self, api_key: str, provider_type: str = "openai") -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if provider_type == "openrouter":
            headers["HTTP-Referer"] = "https://toolnet.tech"
            headers["X-Title"] = "ToolNet Fplus24h"
        return headers

    def test_connection(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 25,
        provider_type: str = "openai_compatible",
    ) -> Dict[str, Any]:
        start = time.monotonic()
        try:
            url = self._normalize_url(base_url)
            headers = self._build_headers(api_key, provider_type)
            payload = {
                "model": model.strip(),
                "messages": [
                    {"role": "user", "content": "Ping test connection. Reply with: OK"}
                ],
                "max_tokens": 15,
                "temperature": 0.1,
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
                choices = parsed.get("choices", [])
                if not choices:
                    return {
                        "success": False,
                        "latency_ms": latency_ms,
                        "error": "Phản hồi API rỗng (không có choices).",
                        "model": model,
                    }

                reply_text = choices[0].get("message", {}).get("content", "").strip()
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
                msg = err_json.get("error", {}).get("message") or str(err_json.get("error")) or err_body
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
        provider_type: str = "openai_compatible",
    ) -> Tuple[str, str]:
        url = self._normalize_url(base_url)
        headers = self._build_headers(api_key, provider_type)

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model.strip(),
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 800,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        for attempt in range(3):
            req = Request(url, data=data, headers=headers, method="POST")
            try:
                with urlopen(req, timeout=timeout) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    raw = resp.read(120_000).decode("utf-8", "ignore").strip()
                    if "data: [DONE]" in raw:
                        raw = raw.split("data: [DONE]")[0].strip()
                    parsed = json.loads(raw)
                value = parsed["choices"][0]["message"]["content"]
                if not isinstance(value, str):
                    raise ValueError("Nội dung phản hồi không phải chuỗi.")
                return value.strip(), model
            except HTTPError as e:
                if attempt < 2 and e.code in (429, 502, 503, 504):
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError(sanitize_text(f"API Error HTTP {e.code}")) from None
            except (TimeoutError, OSError):
                if attempt < 2:
                    time.sleep(3)
                    continue
                raise RuntimeError("API Timeout / Network error") from None
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                raise RuntimeError(sanitize_text(f"API error: {str(e)}")) from None

        raise RuntimeError("Không thể tạo caption qua API sau 3 lần thử.")
