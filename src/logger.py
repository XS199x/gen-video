import logging
import sys
from pathlib import Path


_logger_initialized = False


def setup_logging(log_level: str = "INFO", log_dir: str = None):
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True

    root_logger = logging.getLogger("gen_video")
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(level)

    if not root_logger.handlers:
        # 控制台输出
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        console_handler.setFormatter(console_fmt)
        root_logger.addHandler(console_handler)

        # 文件输出
        if log_dir:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                log_path / "运行日志.log", encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_fmt = logging.Formatter(
                "%(asctime)s [%(levelname)-5s] %(name)s:%(lineno)d: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(file_fmt)
            root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"gen_video.{name}")
