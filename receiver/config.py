import json
import logging
import os
from datetime import datetime
from typing import Any, Dict

import yaml

_CONFIG_CACHE: Dict[str, Any] | None = None
_LOGGER: logging.Logger | None = None


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    global _CONFIG_CACHE
    with open(config_path, "r", encoding="utf-8") as f:
        _CONFIG_CACHE = yaml.safe_load(f)
    return _CONFIG_CACHE


def get_config() -> Dict[str, Any]:
    if _CONFIG_CACHE is None:
        return load_config()
    return _CONFIG_CACHE


def ensure_directories(config: Dict[str, Any]) -> None:
    data_root = config["edge"]["data_root"]
    for sub in ["incoming", "queued", "sent", "failed"]:
        os.makedirs(os.path.join(data_root, sub), exist_ok=True)
    log_path = config["edge"]["log_path"]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    sqlite_path = config["edge"]["sqlite_path"]
    os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("edge")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False

    config = get_config()
    log_path = config["edge"]["log_path"]

    file_handler = logging.FileHandler(log_path)
    stream_handler = logging.StreamHandler()

    formatter = logging.Formatter("%(message)s")
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    _LOGGER = logger
    return logger


def log_event(level: str, stage: str, **fields: Any) -> None:
    logger = get_logger()
    payload = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "level": level,
        "stage": stage,
        **fields,
    }
    message = json.dumps(payload, separators=(",", ":"))
    if level.lower() == "error":
        logger.error(message)
    elif level.lower() == "warning":
        logger.warning(message)
    else:
        logger.info(message)
