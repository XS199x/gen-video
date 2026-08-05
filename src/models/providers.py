import json
import os
import re
from typing import List, Dict, Any, Type, Optional

from pydantic import BaseModel

from .base_llm import BaseLLM
from .llm_factory import LLMFactory
from ..logger import get_logger

logger = get_logger("models")


class OpenAILLM(BaseLLM):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        try:
            from langchain_openai import ChatOpenAI

            api_key = config.get("api_key") or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OpenAI API Key 未找到，请设置 OPENAI_API_KEY 环境变量或 .env 文件")

            base_url = config.get("base_url")
            kw = dict(model=self.model_name, temperature=self.temperature, api_key=api_key)
            if base_url:
                kw["base_url"] = base_url

            self.llm = ChatOpenAI(**kw)
        except ImportError:
            raise ImportError("缺少 langchain-openai，请运行: uv add langchain-openai")

        self._cache = None
        if self._cache_enabled:
            try:
                from ..cache import LLMCache
                self._cache = LLMCache(cache_dir=self._cache_dir)
                logger.info("LLM 缓存已启用: %s", self._cache_dir)
            except Exception as e:
                logger.warning("LLM 缓存未启用: %s", e)

    def generate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        if self._cache and not kwargs.get("skip_cache"):
            cached = self._cache.get(
                self.provider_name, self.model_name, messages, self.temperature
            )
            if cached is not None:
                return cached

        langchain_messages = [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        logger.info(
            "LLM 调用: %s/%s, %d 条消息, 温度=%.2f",
            self.provider_name,
            self.model_name,
            len(messages),
            self.temperature,
        )
        response = self.llm.invoke(langchain_messages)
        result = response.content

        if self._cache and not kwargs.get("skip_cache") and result:
            self._cache.set(
                self.provider_name, self.model_name, messages, self.temperature, result
            )

        return result

    async def agenerate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        if self._cache and not kwargs.get("skip_cache"):
            cached = self._cache.get(
                self.provider_name, self.model_name, messages, self.temperature
            )
            if cached is not None:
                return cached

        langchain_messages = [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        logger.info(
            "异步 LLM 调用: %s/%s, %d 条消息",
            self.provider_name,
            self.model_name,
            len(messages),
        )
        response = await self.llm.agenerate(langchain_messages)
        result = response.generations[0][0].text

        if self._cache and not kwargs.get("skip_cache") and result:
            self._cache.set(
                self.provider_name, self.model_name, messages, self.temperature, result
            )

        return result

    def generate_structured(
        self, messages: List[Dict[str, str]], output_schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        """生成结构化输出。

        尝试顺序:
        1. with_structured_output (仅 OpenAI/Claude 原生支持)
        2. response_format json_object (DeepSeek 等兼容)
        3. 纯文本 + JSON 提示词 + 正则提取 (任何 LLM 通用回退)
        """
        langchain_messages = [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]

        # --- 方案一: with_structured_output ---
        try:
            structured_llm = self.llm.with_structured_output(output_schema)

            if self._cache and not kwargs.get("skip_cache"):
                cached = self._cache.get(
                    self.provider_name, self.model_name, messages, self.temperature,
                )
                if cached is not None:
                    try:
                        return output_schema.model_validate_json(cached)
                    except Exception:
                        pass

            logger.info(
                "结构化 LLM 调用 (with_structured_output): %s/%s, schema=%s",
                self.provider_name, self.model_name, output_schema.__name__,
            )
            result = structured_llm.invoke(langchain_messages)

            if self._cache and not kwargs.get("skip_cache"):
                self._cache.set(
                    self.provider_name, self.model_name, messages,
                    self.temperature, result.model_dump_json(),
                )
            return result

        except Exception:
            pass  # 回退到方案二

        # --- 方案二: response_format json_object ---
        try:
            logger.info(
                "结构化 LLM 调用 (json_object): %s/%s, schema=%s",
                self.provider_name, self.model_name, output_schema.__name__,
            )

            schema_json = json.dumps(
                output_schema.model_json_schema(), ensure_ascii=False, indent=2
            )
            json_messages = [
                {"role": m["role"], "content": m["content"]} for m in messages
            ]
            json_messages.append({
                "role": "system",
                "content": (
                    "你必须返回一个纯 JSON 对象，不要包含 markdown 代码块标记，不要有任何解释性文字。"
                    "严格按照以下 JSON Schema:\n" + schema_json
                ),
            })

            if self._cache and not kwargs.get("skip_cache"):
                cached = self._cache.get(
                    self.provider_name, self.model_name, json_messages, self.temperature,
                )
                if cached is not None:
                    try:
                        return output_schema.model_validate_json(cached)
                    except Exception:
                        pass

            response = self.llm.invoke(
                json_messages,
                response_format={"type": "json_object"},
            )
            text = response.content
            text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
            text = re.sub(r"\n?```\s*$", "", text.strip())

            result = output_schema.model_validate_json(text)

            if self._cache and not kwargs.get("skip_cache"):
                self._cache.set(
                    self.provider_name, self.model_name, json_messages,
                    self.temperature, result.model_dump_json(),
                )
            return result

        except Exception:
            pass  # 回退到方案三

        # --- 方案三: 纯文本 + JSON 提取 ---
        logger.info(
            "结构化 LLM 调用 (纯文本提取): %s/%s, schema=%s",
            self.provider_name, self.model_name, output_schema.__name__,
        )

        text = self.generate(messages, **kwargs)

        # 尝试从文本中提取 JSON
        text_clean = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        text_clean = re.sub(r"\n?```\s*$", "", text_clean.strip())

        json_match = re.search(r"\{[\s\S]*\}", text_clean)
        if json_match:
            try:
                return output_schema.model_validate_json(json_match.group())
            except Exception:
                pass

        raise ValueError(
            f"无法从 LLM 响应中提取有效的 JSON。响应前 500 字符:\n{text[:500]}"
        )


class DeepSeekLLM(OpenAILLM):
    """DeepSeek LLM — OpenAI 兼容 API (api.deepseek.com)。

    支持模型: deepseek-chat (V3), deepseek-reasoner (R1)。
    在 .env 中设置 DEEPSEEK_API_KEY。
    """

    def __init__(self, config: Dict[str, Any]):
        config = dict(config)
        if "base_url" not in config:
            config["base_url"] = "https://api.deepseek.com"
        if not config.get("api_key"):
            config["api_key"] = os.environ.get("DEEPSEEK_API_KEY")
        if not config.get("model") or config.get("model") == "default":
            config["model"] = "deepseek-chat"
        super().__init__(config)


class MockLLM(BaseLLM):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    def generate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return self._get_mock_response(messages)

    async def agenerate(self, messages: List[Dict[str, str]], **kwargs) -> str:
        return self._get_mock_response(messages)

    def generate_structured(
        self, messages: List[Dict[str, str]], output_schema: Type[BaseModel], **kwargs
    ) -> BaseModel:
        schema = output_schema.model_json_schema()
        props = schema.get("properties", {})
        mock_data = {}

        for field_name, field_info in props.items():
            field_type = field_info.get("type", "string")
            if field_type == "string":
                mock_data[field_name] = f"[Mock] {field_name}"
            elif field_type == "array":
                mock_data[field_name] = []
            elif field_type == "object":
                mock_data[field_name] = {}
            elif field_type == "boolean":
                mock_data[field_name] = False
            elif field_type in ("integer", "number"):
                mock_data[field_name] = 0
            else:
                mock_data[field_name] = None

        return output_schema.model_validate(mock_data)

    def _get_mock_response(self, messages: List[Dict[str, str]]) -> str:
        user_content = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_content = msg.get("content", "")[:200]

        return f"""# Mock 响应

当前使用 Mock LLM 模式，返回占位内容。

## 输入摘要
{user_content}

## 说明
如需使用真实 AI 生成，请在 .env 中配置 API Key。
"""


def register_all_providers():
    LLMFactory.register("openai", OpenAILLM)
    LLMFactory.register("deepseek", DeepSeekLLM)
    LLMFactory.register("mock", MockLLM)


register_all_providers()
