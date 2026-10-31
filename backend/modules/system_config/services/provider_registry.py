"""UI metadata and adapter registry. Adding a protocol never requires a UI rewrite."""
from .adapters.openai_adapter import OpenAICompatibleAdapter
from .adapters.anthropic_adapter import AnthropicAdapter
from .adapters.gemini_adapter import GeminiAdapter

PROVIDERS = {
    'openai': ('OpenAI', 'https://api.openai.com/v1', 'openai'),
    'anthropic': ('Anthropic', 'https://api.anthropic.com/v1', 'anthropic'),
    'gemini': ('Google Gemini', 'https://generativelanguage.googleapis.com/v1beta', 'gemini'),
    'openrouter': ('OpenRouter', 'https://openrouter.ai/api/v1', 'openai'),
    'groq': ('Groq', 'https://api.groq.com/openai/v1', 'openai'),
    'toolnet': ('ToolNetAPI', 'https://api.toolnet.tech/v1', 'openai'),
    'openai_compatible': ('Custom OpenAI-compatible', '', 'openai'),
}


def adapter(provider_type):
    protocol = PROVIDERS[provider_type][2]
    return {'openai': OpenAICompatibleAdapter, 'anthropic': AnthropicAdapter, 'gemini': GeminiAdapter}[protocol]()


def catalog():
    return [{'id': key, 'name': value[0], 'base_url': value[1], 'protocol': value[2]} for key, value in PROVIDERS.items()]
