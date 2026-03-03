"""Simple centralized Loguru setup helpers.

Use `setup_logging(level, enable, log_file)` early in your entrypoints
to configure Loguru sinks and optionally intercept stdlib logging.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from loguru import logger


class InterceptHandler(logging.Handler):
    """Redirect stdlib logging to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except Exception:
            level = record.levelno

        logger.opt(exception=record.exc_info, depth=6).log(level, record.getMessage())


def setup_logging(
    level: str = "INFO",
    enable: bool = True,
    log_file: Optional[str] = None,
    rotation: str = "10 MB",
    retention: str = "7 days",
    intercept_stdlib: bool = False,
    enable_httpx: bool = False,
):
    """Configure loguru global logger.

    - level: one of TRACE/DEBUG/INFO/SUCCESS/WARNING/ERROR/CRITICAL
    - enable: if False, removes sinks and no logging will be emitted
    - log_file: optional path to also write logs
    - intercept_stdlib: when True, route logging.getLogger() output to loguru
    """
    # Remove existing sinks
    try:
        for sink in list(logger._core.handlers):
            # logger.remove accepts handler id; using remove all via catch-all
            try:
                logger.remove(sink)
            except Exception:
                pass
    except Exception:
        # fallback: remove all by calling remove with indices until fails
        try:
            i = 0
            while True:
                logger.remove(i)
                i += 1
        except Exception:
            pass

    if not enable:
        # add a sink that only accepts CRITICAL+ to effectively silence
        logger.add(sys.stderr, level="CRITICAL+1")
        return

    # Colored format for terminal output
    fmt_color = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.add(sys.stderr, level=level, format=fmt_color, enqueue=True, colorize=True)
    logger.debug(f"Logging initialized with level {level} and intercept_stdlib={intercept_stdlib}")

    if log_file:
        try:
            # File sink should not contain color tags
            fmt_file = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
            logger.add(log_file, level=level, rotation=rotation, retention=retention, encoding="utf-8", format=fmt_file, colorize=False)
        except Exception:
            logger.exception(f"Failed to add file sink {log_file}")

    if intercept_stdlib:
        logging.root.handlers = [InterceptHandler()]
        try:
            lvl = getattr(logging, level.upper())
        except Exception:
            lvl = logging.INFO
        logging.root.setLevel(lvl)
        logging.captureWarnings(True)

    logger.disable("httpx") if not enable_httpx else logger.debug("HTTPX logging enabled")


def get_logger(name: Optional[str] = None):
    if name:
        return logger.bind(module=name)
    return logger
