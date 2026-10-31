import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Dict, Any, Tuple, Optional

from .base import BaseAIAdapter
from ...crypto import sanitize_text


class GeminiAdapter(BaseAIAdapter):
    """Adapter for Google Gemini REST API (v1beta generateContent)."""

    def _build_url(self, base_url: str, model: str, api_key: str) -> str:
        clean_base = (base_url or "https://generativelanguage.googleapis.com").strip().rstrip("/")
        parsed = urlparse(clean_base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Endpoint phải là HTTPS hợp lệ.")
        clean_base = clean_base.removesuffix("/v1beta")
        clean_model = model.strip()
        # If user passed full path or models already in model name
        if not clean_model.startswith("models/"):
            model_path = f"models/{clean_model}"
        else:
            model_path = clean_model
        return f"{clean_base}/v1beta/{model_path}:generateContent?key={api_key.strip()}"

    def test_connection(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 25,
    ) -> Dict[str, Any]:
        start = time.monotonic()
        try:
            url = self._build_url(base_url, model, api_key)
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [
                    {"parts": [{"text": "Ping test connection. Reply: OK"}]}
                ],
                "generationConfig": {
                    "maxOutputTokens": 20,
                    "temperature": 0.1,
                },
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
                candidates = parsed.get("candidates", [])
                if not candidates:
                    return {
                        "success": False,
                        "latency_ms": latency_ms,
                        "error": "Gemini không trả về candidate.",
                        "model": model,
                    }

                parts = candidates[0].get("content", {}).get("parts", [])
                reply_text = "".join(p.get("text", "") for p in parts)

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
        url = self._build_url(base_url, model, api_key)
        headers = {"Content-Type": "application/json"}

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "maxOutputTokens": 800,
                "temperature": 0.8,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        for attempt in range(3):
            req = Request(url, data=data, headers=headers, method="POST")
            try:
                with urlopen(req, timeout=timeout) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Gemini HTTP {resp.status}")
                    raw = resp.read(120_000).decode("utf-8", "ignore").strip()
                    parsed = json.loads(raw)

                candidates = parsed.get("candidates", [])
                if not candidates:
                    raise ValueError("Gemini không trả về kết quả.")
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                return text.strip(), model
            except HTTPError as e:
                if attempt < 2 and e.code in (429, 502, 503, 504):
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError(sanitize_text(f"Gemini HTTP {e.code}")) from None
            except (TimeoutError, OSError):
                if attempt < 2:
                    time.sleep(3)
                    continue
                raise RuntimeError("Gemini Timeout / Network error") from None
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                raise RuntimeError(sanitize_text(f"Gemini error: {str(e)}")) from None

        raise RuntimeError("Không thể tạo caption qua Gemini sau 3 lần thử.")
