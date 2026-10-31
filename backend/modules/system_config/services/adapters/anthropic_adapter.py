from .base import BaseAIAdapter
from .protocol import Protocol, ProviderError, secure_urlopen as urlopen


class AnthropicAdapter(BaseAIAdapter):
    def complete(self, **kwargs):
        return Protocol("anthropic", urlopen).complete(**kwargs)

    def discover(self, **kwargs):
        return Protocol("anthropic", urlopen).discover(**kwargs)

    def generate_completion(self, *, base_url, api_key, model, prompt, system_instruction=None, timeout=60, **kwargs):
        result = self.complete(base_url=base_url, api_key=api_key, model=model, prompt=prompt, system_instruction=system_instruction, timeout=timeout, **kwargs)
        return result["text"], result["model"]

    def test_connection(self, *, base_url, api_key, model, timeout=25, **kwargs):
        try:
            result = self.complete(base_url=base_url, api_key=api_key, model=model, prompt="Reply OK.", timeout=timeout, **kwargs)
            result.pop("text", None)
            return result
        except ProviderError as exc:
            return exc.public()
