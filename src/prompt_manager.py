import os
from typing import Dict, Any, Optional, List
from jinja2 import Environment, FileSystemLoader, Template
from .config_manager import ConfigManager


class PromptManager:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self._template_cache: Dict[str, Template] = {}
        
        templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
        self.jinja_env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=False
        )
    
    def load_template(self, template_name: str) -> Template:
        if template_name not in self._template_cache:
            template_path = self.config_manager.get_prompt_template_path(template_name)
            
            if not os.path.exists(template_path):
                template_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "prompts",
                    f"{template_name}.txt"
                )
            
            if os.path.exists(template_path):
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_content = f.read()
                self._template_cache[template_name] = Template(template_content)
            else:
                self._template_cache[template_name] = Template("")
        
        return self._template_cache[template_name]
    
    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        template = self.load_template(template_name)
        return template.render(**context)
    
    def create_messages(self, template_name: str, context: Dict[str, Any], 
                         system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        user_content = self.render(template_name, context)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        
        return messages
    
    def add_template(self, template_name: str, content: str):
        self._template_cache[template_name] = Template(content)
    
    def clear_cache(self):
        self._template_cache.clear()
