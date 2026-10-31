"""Provider wire protocols. No secret-bearing URLs, redirects, logging, or implicit retries."""
import json
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ProviderError(Exception):
    def __init__(self, code, http_status=None, fallback_allowed=False, retry_after=None):
        self.code, self.http_status, self.fallback_allowed = code, http_status, fallback_allowed
        self.retry_after = retry_after
        super().__init__(code)

    def public(self):
        return {'success': False, 'error': self.code, 'http_status': self.http_status, 'fallback_allowed': self.fallback_allowed, 'retry_after': self.retry_after}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('redirect_rejected')


def secure_urlopen(req, timeout):
    return build_opener(NoRedirect()).open(req, timeout=timeout)


def validate_base(base):
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderError('invalid_endpoint')
    return base.rstrip('/')


def request_json(open_url, url, key, protocol, *, payload=None, headers=None, timeout=60):
    merged = {'Accept': 'application/json', 'Content-Type': 'application/json', **(headers or {})}
    if protocol == 'anthropic':
        merged.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
    elif protocol == 'gemini':
        merged['x-goog-api-key'] = key
    else:
        merged['Authorization'] = f'Bearer {key}'
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=merged, method='POST' if payload is not None else 'GET')
    try:
        with open_url(request, timeout=timeout) as response:
            status = response.status
            if status < 200 or status >= 300:
                raise ProviderError('service_error' if status in (500, 502, 503, 504) else 'request_rejected', status, status in (500, 502, 503, 504))
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ProviderError('response_too_large')
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ProviderError('invalid_response')
            return data, status
    except HTTPError as exc:
        code = exc.code
        raw_retry = (exc.headers or {}).get('Retry-After', '')
        retry_after = min(3600, max(1, int(raw_retry))) if str(raw_retry).isdigit() else 60
        exc.close()
        reason = {400: 'invalid_input', 401: 'authentication_failed', 403: 'access_denied', 404: 'model_or_endpoint_unavailable', 408: 'timeout', 422: 'invalid_input', 429: 'rate_or_quota_limited'}.get(code, 'service_error' if code in (500, 502, 503, 504) else 'request_rejected')
        raise ProviderError(reason, code, code in (408, 500, 502, 503, 504), retry_after if code == 429 else None) from None
    except (ssl.SSLError, ssl.CertificateError):
        raise ProviderError('tls_security_error') from None
    except (TimeoutError, socket.timeout):
        raise ProviderError('timeout', fallback_allowed=True) from None
    except URLError as exc:
        if isinstance(exc.reason, (ssl.SSLError, ssl.CertificateError)):
            raise ProviderError('tls_security_error') from None
        raise ProviderError('network_error', fallback_allowed=True) from None
    except (OSError, ConnectionError):
        raise ProviderError('network_error', fallback_allowed=True) from None
    except (ValueError, KeyError, TypeError):
        raise ProviderError('invalid_response') from None


class Protocol:
    def __init__(self, kind, open_url):
        self.kind, self.open_url = kind, open_url

    def root(self, base):
        base = validate_base(base)
        if self.kind == 'anthropic':
            return base.removesuffix('/messages').removesuffix('/v1') + '/v1'
        if self.kind == 'gemini':
            return base if base.endswith(('/v1', '/v1beta')) else base + '/v1beta'
        return base.removesuffix('/chat/completions')

    def complete(self, *, base_url, api_key, model, prompt, system_instruction=None, timeout=60, settings=None, custom_headers=None):
        start = time.monotonic()
        options = settings or {}
        root = self.root(base_url)
        optional = {}
        if options.get('supports_temperature') is True and options.get('temperature') is not None:
            optional['temperature'] = options['temperature']
        if options.get('supports_top_p') is True and options.get('top_p') is not None:
            optional['top_p'] = options['top_p']
        maximum = options.get('max_output_tokens')
        if self.kind == 'anthropic':
            if maximum is None:
                raise ProviderError('anthropic_max_output_tokens_required')
            payload = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': maximum, **optional}
            if system_instruction:
                payload['system'] = system_instruction
            url = root + '/messages'
        elif self.kind == 'gemini':
            config = {('topP' if k == 'top_p' else k): v for k, v in optional.items()}
            if maximum is not None:
                config['maxOutputTokens'] = maximum
            payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}]}
            if config:
                payload['generationConfig'] = config
            if system_instruction:
                payload['systemInstruction'] = {'parts': [{'text': system_instruction}]}
            url = root + '/models/' + quote(model.removeprefix('models/'), safe='') + ':generateContent'
        else:
            messages = ([{'role': 'system', 'content': system_instruction}] if system_instruction else []) + [{'role': 'user', 'content': prompt}]
            payload = {'model': model, 'messages': messages, **optional}
            if maximum is not None:
                payload[options.get('token_parameter', 'max_tokens')] = maximum
            url = root + '/chat/completions'
        data, status = request_json(self.open_url, url, api_key, self.kind, payload=payload, headers=custom_headers, timeout=timeout)
        try:
            if self.kind == 'anthropic':
                text = ''.join(p.get('text', '') for p in data.get('content', []) if p.get('type') == 'text')
                usage = data.get('usage', {})
            elif self.kind == 'gemini':
                text = ''.join(p.get('text', '') for p in data['candidates'][0]['content']['parts'] if not p.get('thought'))
                usage = data.get('usageMetadata', {})
            else:
                text = data['choices'][0]['message']['content']
                usage = data.get('usage', {})
            if not isinstance(text, str) or not text.strip():
                raise ValueError()
            # The provider can reflect headers/credentials in its response. Remove exact secret values.
            for secret in [api_key, *(custom_headers or {}).values()]:
                if secret:
                    text = text.replace(secret, '[REDACTED]')
            allowed_usage = {'prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'promptTokenCount', 'candidatesTokenCount', 'totalTokenCount', 'thoughtsTokenCount', 'cachedContentTokenCount'}
            usage = {k: v for k, v in (usage if isinstance(usage, dict) else {}).items() if k in allowed_usage and isinstance(v, int) and not isinstance(v, bool)}
            actual = data.get('model') or data.get('modelVersion') or model
            actual = actual if isinstance(actual, str) and len(actual) <= 200 and not any(secret and secret in actual for secret in [api_key, *(custom_headers or {}).values()]) else model
            return {'success': True, 'text': text.strip(), 'model': actual, 'requested_model': model, 'usage': usage, 'http_status': status, 'latency_ms': int((time.monotonic() - start) * 1000)}
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            raise ProviderError('empty_or_invalid_completion') from None

    def discover(self, *, base_url, api_key, timeout=30, custom_headers=None):
        root, models, cursor, seen = self.root(base_url), [], '', set()
        start = time.monotonic()
        for _ in range(50):
            if time.monotonic() - start > 45:
                raise ProviderError('discovery_budget_exceeded')
            params = {}
            if self.kind == 'gemini':
                params = {'pageSize': 100, **({'pageToken': cursor} if cursor else {})}
            elif self.kind == 'anthropic':
                params = {'limit': 100, **({'after_id': cursor} if cursor else {})}
            elif cursor:
                params = {'after': cursor}
            url = root + '/models' + ('?' + urlencode(params) if params else '')
            try:
                data, _ = request_json(self.open_url, url, api_key, self.kind, headers=custom_headers, timeout=max(1, min(timeout, int(45 - (time.monotonic() - start)))))
            except ProviderError as exc:
                if exc.http_status in (404, 405, 501):
                    raise ProviderError('models_api_not_supported_use_manual', exc.http_status) from None
                raise
            rows = data.get('models' if self.kind == 'gemini' else 'data')
            if not isinstance(rows, list):
                raise ProviderError('invalid_models_response')
            for item in rows:
                if not isinstance(item, dict):
                    raise ProviderError('invalid_models_response')
                model_id = item.get('name', '').removeprefix('models/') if self.kind == 'gemini' else item.get('id')
                if not isinstance(model_id, str) or not model_id or len(model_id) > 120:
                    continue
                models.append({'model_id': model_id, 'display_name': str(item.get('displayName') or item.get('display_name') or item.get('name') or model_id)[:200], 'output_token_limit': item.get('outputTokenLimit'), 'supports_temperature': True if 'temperature' in item else None, 'supports_top_p': True if 'topP' in item else None})
            cursor = data.get('nextPageToken', '') if self.kind == 'gemini' else (data.get('last_id') or (rows[-1].get('id') if rows else '')) if data.get('has_more') else ''
            if not cursor:
                return models
            if not isinstance(cursor, str) or cursor in seen or (api_key and api_key in cursor):
                raise ProviderError('invalid_pagination')
            seen.add(cursor)
        raise ProviderError('discovery_page_limit')
