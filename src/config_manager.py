import yaml
import os
from typing import Any, Dict, Optional
from pathlib import Path

# Load .env at import time — before any env var is read
try:
    from dotenv import load_dotenv
    _env_file = os.path.join(os.getcwd(), ".env")
    if os.path.exists(_env_file):
        load_dotenv(_env_file)
except ImportError:
    pass


class ConfigManager:
    _instance = None
    
    def __new__(cls, config_path: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_path: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True
        
        if config_path is None:
            config_path = os.path.join(os.getcwd(), "config.yaml")
        
        self.config_path = config_path
        self.config = {}
        self._load_config()
    
    def _load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "global": {
                "output_base_dir": "./outputs",
                "log_level": "INFO"
            },
            "models": {
                "default": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "temperature": 0.7
                },
                "nodes": {}
            },
            "api_keys": {}
        }
    
    def get_global(self, key: str, default: Any = None) -> Any:
        return self.config.get("global", {}).get(key, default)
    
    def get_node_config(self, node_name: str) -> Dict[str, Any]:
        nodes_config = self.config.get("models", {}).get("nodes", {})
        if node_name in nodes_config:
            return nodes_config[node_name]
        return self.config.get("models", {}).get("default", {})
    
    def get_api_key(self, provider: str) -> Optional[str]:
        api_keys = self.config.get("api_keys", {})
        key_config = api_keys.get(provider, "")
        
        if key_config.startswith("${") and key_config.endswith("}"):
            env_var_name = key_config[2:-1]
            return os.environ.get(env_var_name)
        
        return key_config or os.environ.get(f"{provider.upper()}_API_KEY")

    def get_image_config(self) -> Optional[Dict[str, Any]]:
        image_config = self.config.get("image", {})
        if not image_config:
            return None

        provider = image_config.get("provider", "jimeng")
        provider_config = image_config.get(provider, {})

        resolved_config = {"provider": provider}
        for key, value in provider_config.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var_name = value[2:-1]
                resolved_config[key] = os.environ.get(env_var_name, "")
            else:
                resolved_config[key] = value

        return resolved_config if resolved_config.get("access_key") else None
    
    def get_prompt_template_path(self, template_name: str) -> str:
        template_config = self.config.get("prompt_templates", {})
        if template_name in template_config:
            return template_config[template_name]
        
        templates_dir = os.path.join(os.getcwd(), "src", "prompts")
        return os.path.join(templates_dir, f"{template_name}.txt")
    
    def get_output_dir(self, episode_id: str) -> str:
        base_dir = self.get_global("output_base_dir", "./outputs")
        output_dir = os.path.join(base_dir, episode_id)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return output_dir
    
    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split(".")
        value = self.config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value
    
    def reload(self):
        self._load_config()
    
    def update_node_model(self, node_name: str, provider: str, model: str, **kwargs):
        if "models" not in self.config:
            self.config["models"] = {}
        if "nodes" not in self.config["models"]:
            self.config["models"]["nodes"] = {}
        
        node_config = {"provider": provider, "model": model}
        node_config.update(kwargs)
        self.config["models"]["nodes"][node_name] = node_config
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
