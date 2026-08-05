"""
图片生成器 — 支持多种后端，可按需切换。

当前支持:
  - openai:  OpenAI DALL-E 3 / DALL-E 2
  - jimeng:  火山引擎即梦 (需安装 volcengine-python-sdk[ark])

配置示例 (config.yaml):
  image:
    provider: openai
    openai:
      model: dall-e-3        # dall-e-3 或 dall-e-2
      size: 1024x1024        # dall-e-3: 1024x1024, 1792x1024, 1024x1792
      quality: standard       # standard 或 hd
      max_retries: 3
      retry_delay: 2
"""

import os
import time
import base64
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from pathlib import Path

from .logger import get_logger

logger = get_logger("image_generator")


# ─── 抽象基类 ────────────────────────────────────────────────────

class BaseImageGenerator(ABC):
    """图片生成器抽象基类。"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay", 2)

    @abstractmethod
    def _generate_one(self, prompt: str) -> Optional[str]:
        """生成一张图片，返回 base64 字符串或 None。"""

    def generate_image(self, prompt: str, save_path: str) -> Optional[str]:
        """生成图片并保存到指定路径。"""
        for attempt in range(self.max_retries):
            try:
                b64 = self._generate_one(prompt)
                if b64:
                    self._save_image(b64, save_path)
                    logger.info("图片已保存: %s", save_path)
                    return save_path
                time.sleep(self.retry_delay)
            except Exception as e:
                logger.warning("第 %d/%d 次生成失败: %s", attempt + 1, self.max_retries, e)
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    raise
        return None

    def generate_batch(
        self, prompts_with_paths: List[Dict[str, str]], delay: float = 1.0
    ) -> List[Optional[str]]:
        """批量生成图片。"""
        results = []
        for i, item in enumerate(prompts_with_paths):
            prompt = item.get("prompt", "")
            save_path = item.get("save_path", "")
            if prompt and save_path:
                try:
                    logger.info("[%d/%d] 生成: %s...", i + 1, len(prompts_with_paths), prompt[:50])
                    r = self.generate_image(prompt, save_path)
                    results.append(r)
                    if i < len(prompts_with_paths) - 1:
                        time.sleep(delay)
                except Exception as e:
                    logger.warning("[%d/%d] 失败: %s", i + 1, len(prompts_with_paths), e)
                    results.append(None)
            else:
                results.append(None)
        ok = sum(1 for r in results if r)
        logger.info("批量生成完成: %d/%d 张", ok, len(results))
        return results

    def _save_image(self, base64_data: str, save_path: str):
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        image_data = base64.b64decode(base64_data)
        with open(save_path, "wb") as f:
            f.write(image_data)


# ─── OpenAI DALL-E ───────────────────────────────────────────────

class OpenAIImageGenerator(BaseImageGenerator):
    """OpenAI DALL-E 图片生成。

    需要 OpenAI API Key (在 .env 中设置 OPENAI_API_KEY)。
    """

    SUPPORTED_MODELS = {
        "dall-e-3": "DALL-E 3 (推荐，质量最高)",
        "dall-e-2": "DALL-E 2 (更快更便宜)",
    }

    DALL_E_3_SIZES = {"1024x1024", "1792x1024", "1024x1792"}
    DALL_E_2_SIZES = {"256x256", "512x512", "1024x1024"}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model = config.get("model", "dall-e-3")
        self.size = config.get("size", "1024x1024")
        self.quality = config.get("quality", "standard")

        api_key = config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI 图片生成需要 API Key。\n"
                "请在 .env 中设置: OPENAI_API_KEY=sk-..."
            )

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("缺少 openai 库，请运行: uv add openai")

        # 验证参数
        if self.model == "dall-e-3":
            if self.size not in self.DALL_E_3_SIZES:
                logger.warning("DALL-E 3 不支持尺寸 %s，回退到 1024x1024", self.size)
                self.size = "1024x1024"
        elif self.model == "dall-e-2":
            if self.size not in self.DALL_E_2_SIZES:
                self.size = "1024x1024"

    def _generate_one(self, prompt: str) -> Optional[str]:
        kwargs = dict(
            model=self.model,
            prompt=prompt,
            size=self.size,
            n=1,
            response_format="b64_json",
        )
        if self.model == "dall-e-3":
            kwargs["quality"] = self.quality

        response = self.client.images.generate(**kwargs)
        b64 = response.data[0].b64_json
        return b64


# ─── 火山引擎即梦 ────────────────────────────────────────────────

class JimengImageGenerator(BaseImageGenerator):
    """火山引擎即梦图片生成。

    需要 AK/SK (在 .env 中设置 VOLCENGINE_AK / VOLCENGINE_SK)。
    需要安装: uv add volcengine-python-sdk[ark]
    """

    SUPPORTED_MODELS = {
        "jimeng_t2i_v30": "即梦文生图3.0",
        "jimeng_seedream46_cvtob": "即梦4.6",
    }

    # 模型名 → SDK API 方法名映射
    _MODEL_MAP = {
        "jimeng_t2i_v30": "high_aes_general_v20_l",
        "jimeng_seedream46_cvtob": "high_aes_general_v20",
        "jimeng_t2i_v20": "high_aes_general_v20",
        "high_aes_general_v20_l": "high_aes_general_v20_l",
        "high_aes_general_v20": "high_aes_general_v20",
        "high_aes_general_v14": "high_aes_general_v14",
        "text2img_xl_sft": "text2_img_xl_sft",
    }

    DEFAULT_SIZES = {
        "1024x1024": (1024, 1024), "1328x1328": (1328, 1328),
        "2048x2048": (2048, 2048), "1280x720": (1280, 720), "1920x1080": (1920, 1080),
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.model = config.get("model", "jimeng_t2i_v30")
        self.size = config.get("size", "1024x1024")
        self.width, self.height = self.DEFAULT_SIZES.get(self.size, (1024, 1024))
        self.timeout = config.get("timeout", 120)

        ak = config.get("access_key")
        sk = config.get("secret_key")
        if not ak or not sk:
            raise ValueError(
                "即梦需要 AK/SK。在 .env 中设置 VOLCENGINE_AK / VOLCENGINE_SK"
            )

        try:
            from volcenginesdkcore import Configuration, ApiClient
            from volcenginesdkcv20240606 import CV20240606Api
        except ImportError:
            raise ImportError(
                "即梦需要 volcengine-python-sdk[ark]\n"
                "运行: uv add volcengine-python-sdk[ark]"
            )

        self._cfg = Configuration()
        self._cfg.ak = ak
        self._cfg.sk = sk
        self._cfg.connection_pool_maxsize = 5
        self._api = CV20240606Api(ApiClient(self._cfg))

        self._api_method_name = self._MODEL_MAP.get(self.model, "high_aes_general_v20_l")
        self._api_method = getattr(self._api, self._api_method_name, None)
        if self._api_method is None:
            raise ValueError(f"不支持的即梦模型: {self.model} (SDK 方法 {self._api_method_name} 不存在)")

        logger.info("即梦图片生成器: model=%s, sdk_method=%s, size=%dx%d",
                     self.model, self._api_method_name, self.width, self.height)

    def _generate_one(self, prompt: str) -> Optional[str]:
        from volcenginesdkcv20240606 import HighAesGeneralV20LRequest
        import httpx

        req = HighAesGeneralV20LRequest()
        req.req_key = self.model
        req.prompt = prompt
        req.width = self.width
        req.height = self.height
        req.return_url = True

        resp = self._api_method(req)

        code = getattr(resp, 'code', 0)
        if code != 10000:
            msg = getattr(resp, 'message', '')
            raise Exception(f"即梦 API 错误: code={code}, message={msg}")

        data = getattr(resp, 'data', None)
        if data is None:
            return None

        urls = getattr(data, 'image_urls', None) or []
        if urls and len(urls) > 0:
            return self._download(urls[0])

        b64_list = getattr(data, 'binary_data_base64', None) or []
        if b64_list and len(b64_list) > 0:
            return b64_list[0]

        return None

    def _download(self, url: str) -> Optional[str]:
        import httpx
        try:
            resp = httpx.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode("utf-8")
        except Exception as e:
            logger.warning("图片下载失败: %s", e)
            return None


# ─── 工厂 ────────────────────────────────────────────────────────

_PROVIDER_REGISTRY = {
    "openai": OpenAIImageGenerator,
    "jimeng": JimengImageGenerator,
}


def register_image_provider(name: str, cls: type):
    """注册自定义图片生成器。"""
    _PROVIDER_REGISTRY[name] = cls


def create_image_generator(config: Dict[str, Any]) -> BaseImageGenerator:
    """根据配置创建图片生成器实例。

    config 来自 ConfigManager.get_image_config()，已经解析过环境变量，
    格式为: {"provider": "jimeng", "access_key": "...", ...}
    """
    provider = config.get("provider", "jimeng")

    # 构建传给构造函数的配置（排除 provider 字段本身）
    resolved = {k: v for k, v in config.items() if k != "provider"}

    # 二次解析环境变量（以防 config_manager 未覆盖的情况）
    for key, value in list(resolved.items()):
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_name = value[2:-1]
            resolved[key] = os.environ.get(env_name, "")

    if provider not in _PROVIDER_REGISTRY:
        raise ValueError(
            f"未知的图片服务商: '{provider}'。\n"
            f"支持: {list(_PROVIDER_REGISTRY.keys())}\n"
            f"在 config.yaml 的 image.provider 中设置。"
        )

    logger.info("图片生成器: %s", provider)
    return _PROVIDER_REGISTRY[provider](resolved)
