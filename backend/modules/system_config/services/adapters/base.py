from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional


class BaseAIAdapter(ABC):
    """Abstract interface for AI Provider adapters."""

    @abstractmethod
    def test_connection(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Test provider connectivity and response.

        Returns:
            dict with keys: success (bool), latency_ms (int), error (str), model (str)
        """
        pass

    @abstractmethod
    def generate_completion(
        self,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        system_instruction: Optional[str] = None,
        timeout: int = 60,
    ) -> Tuple[str, str]:
        """Generate text completion from prompt.

        Returns:
            (generated_text, model_name)
        """
        pass
