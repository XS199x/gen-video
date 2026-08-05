from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Type
from pydantic import BaseModel


class BaseLLM(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model_name = config.get("model", "default")
        self.temperature = config.get("temperature", 0.7)
        self.provider_name = config.get("provider", "unknown")
        self._cache_enabled = config.get("cache_enabled", True)
        self._cache_dir = config.get("cache_dir", ".cache/llm")

    @abstractmethod
    async def agenerate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        pass

    @abstractmethod
    def generate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        pass

    def generate_structured(
        self, messages: List[Dict[str, str]], output_schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        """Generate a structured response conforming to the given Pydantic schema.

        Default implementation: generate text, then parse with schema.
        Override in provider for native structured output support.
        """
        text = self.generate(messages, **kwargs)
        return output_schema.model_validate_json(text)

    async def agenerate_structured(
        self, messages: List[Dict[str, str]], output_schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        """Async version of generate_structured."""
        text = await self.agenerate(messages, **kwargs)
        return output_schema.model_validate_json(text)

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model_name,
            "temperature": self.temperature,
            "provider": self.provider_name,
        }
