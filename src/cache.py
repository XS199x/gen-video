import hashlib
import json
import pickle
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger("cache")


class LLMCache:
    """基于文件系统的 LLM 响应缓存（LRU 淘汰策略）。

    缓存键由 (provider, model, messages, temperature) 拼接后 SHA256 生成。
    每个缓存条目存储为一个 pickle 文件。
    """

    def __init__(self, cache_dir: str = ".cache/llm", max_size: int = 500):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size = max_size

    def _make_key(
        self,
        provider: str,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
    ) -> str:
        payload = {
            "provider": provider,
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.pkl"

    def get(
        self,
        provider: str,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
    ) -> Optional[str]:
        if not self.cache_dir.exists():
            return None
        key = self._make_key(provider, model, messages, temperature)
        path = self._cache_path(key)
        if path.exists():
            try:
                with open(path, "rb") as f:
                    entry = pickle.load(f)
                path.touch()
                logger.debug("缓存命中: %s...", key[:8])
                return entry["response"]
            except Exception:
                logger.warning("缓存条目损坏: %s", key[:8])
                path.unlink(missing_ok=True)
        return None

    def set(
        self,
        provider: str,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        response: str,
    ):
        key = self._make_key(provider, model, messages, temperature)
        path = self._cache_path(key)
        entry = {
            "key": key,
            "provider": provider,
            "model": model,
            "temperature": temperature,
            "response": response,
            "created_at": time.time(),
        }
        with open(path, "wb") as f:
            pickle.dump(entry, f)
        logger.debug("缓存写入: %s...", key[:8])
        self._evict_if_needed()

    def _evict_if_needed(self):
        files = sorted(
            self.cache_dir.glob("*.pkl"), key=lambda p: p.stat().st_atime
        )
        while len(files) > self.max_size:
            victim = files.pop(0)
            victim.unlink()
            logger.debug("缓存淘汰: %s", victim.stem[:8])

    def clear(self):
        for f in self.cache_dir.glob("*.pkl"):
            f.unlink()
        logger.info("缓存已清空: %s", self.cache_dir)

    def stats(self) -> Dict[str, Any]:
        files = list(self.cache_dir.glob("*.pkl"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "条目数": len(files),
            "总大小_bytes": total_size,
            "总大小_mb": round(total_size / (1024 * 1024), 2),
            "缓存目录": str(self.cache_dir),
        }


_cache_instance: Optional[LLMCache] = None


def get_cache(cache_dir: str = ".cache/llm", max_size: int = 500) -> LLMCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = LLMCache(cache_dir=cache_dir, max_size=max_size)
    return _cache_instance
