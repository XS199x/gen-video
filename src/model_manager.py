from typing import Dict, Any, List, Optional
from .config_manager import ConfigManager
from .models.base_llm import BaseLLM
from .models.llm_factory import LLMFactory


class ModelManager:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self._llm_cache: Dict[str, BaseLLM] = {}

    def get_llm_for_node(self, node_name: str) -> BaseLLM:
        if node_name not in self._llm_cache:
            node_config = self.config_manager.get_node_config(node_name)
            self._llm_cache[node_name] = LLMFactory.create(node_config, self.config_manager)

        return self._llm_cache[node_name]

    def switch_model_for_node(self, node_name: str, provider: str, model: str, **kwargs):
        self.config_manager.update_node_model(node_name, provider, model, **kwargs)

        if node_name in self._llm_cache:
            del self._llm_cache[node_name]

    def get_available_providers(self) -> List[str]:
        from .models.llm_factory import LLMFactory
        return list(LLMFactory._llm_registry.keys())

    def clear_cache(self):
        self._llm_cache.clear()
        LLMFactory.clear_cache()
