from typing import Dict, Any, Optional, Type
from .base_llm import BaseLLM


class LLMFactory:
    _llm_registry: Dict[str, Type[BaseLLM]] = {}
    _instances: Dict[str, BaseLLM] = {}
    
    @classmethod
    def register(cls, provider: str, llm_class: Type[BaseLLM]):
        cls._llm_registry[provider.lower()] = llm_class
    
    @classmethod
    def create(cls, config: Dict[str, Any], config_manager=None) -> BaseLLM:
        provider = config.get("provider", "openai").lower()
        
        if provider not in cls._llm_registry:
            raise ValueError(f"Unknown LLM provider: {provider}. Available: {list(cls._llm_registry.keys())}")
        
        instance_key = f"{provider}:{config.get('model', 'default')}"
        
        if instance_key not in cls._instances:
            llm_class = cls._llm_registry[provider]
            
            if config_manager:
                api_key = config_manager.get_api_key(provider)
                config_with_key = {**config, "api_key": api_key}
                cls._instances[instance_key] = llm_class(config_with_key)
            else:
                cls._instances[instance_key] = llm_class(config)
        
        return cls._instances[instance_key]
    
    @classmethod
    def clear_cache(cls):
        cls._instances.clear()
