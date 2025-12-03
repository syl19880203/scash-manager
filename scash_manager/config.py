# scash_manager/config.py
import json
import logging
import os
from copy import deepcopy


# 默认配置（第一次运行或配置文件不存在时使用）
DEFAULT_CONFIG = {
    "wallet": "",
    "miner": {
        "impl": "cpuminer",                 # cpuminer / srbminer
        "url": "",                          # 矿池地址
        "user": "",                         # 钱包地址（用户名）
        "threads": None,                    # 线程数（None = 自动）
        "bin_path": "/usr/local/bin/minerd",
        "algorithm": "randomx",
        "extra_args": "",
    },
    "watchdog": {
        "enabled": True,
        "restart_delay": 5,                 # 秒
    },
    "logging": {
        "file": "/data/scash-manager.log",
        "level": "INFO",
    },
}


def _get_config_path() -> str:
    """
    优先读环境变量 SCASH_MANAGER_CONFIG，
    没有则默认 /data/config.json（Docker 中挂载目录）。
    """
    return os.environ.get("SCASH_MANAGER_CONFIG", "/data/config.json")


def load_config(allow_missing: bool = False) -> dict:
    """
    从 JSON 文件加载配置。
    - 文件不存在且 allow_missing=True：返回默认配置副本；
    - 文件不存在且 allow_missing=False：抛 FileNotFoundError；
    - JSON 解析失败：打印警告，返回默认配置副本。
    """
    path = _get_config_path()
    if not os.path.isfile(path):
        if allow_missing:
            logging.info("配置文件不存在，使用默认配置: %s", path)
            return deepcopy(DEFAULT_CONFIG)
        raise FileNotFoundError(path)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logging.warning("配置文件 JSON 解析失败，使用默认配置: %s (%s)", path, e)
        return deepcopy(DEFAULT_CONFIG)
    except Exception as e:
        logging.error("读取配置文件失败 %s: %s", path, e)
        if allow_missing:
            return deepcopy(DEFAULT_CONFIG)
        raise

    # 和默认配置合并，保证关键字段存在
    cfg = deepcopy(DEFAULT_CONFIG)
    try:
        # 顶层
        cfg.update({k: v for k, v in data.items() if k in cfg})

        # miner 子项
        if "miner" in data and isinstance(data["miner"], dict):
            cfg["miner"].update(data["miner"])

        # watchdog 子项
        if "watchdog" in data and isinstance(data["watchdog"], dict):
            cfg["watchdog"].update(data["watchdog"])

        # logging 子项
        if "logging" in data and isinstance(data["logging"], dict):
            cfg["logging"].update(data["logging"])
    except Exception as e:
        logging.warning("合并配置时出现异常，部分字段可能丢失: %s", e)

    return cfg


def save_config(cfg: dict) -> None:
    """
    把配置写回 JSON 文件。
    """
    path = _get_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        logging.info("配置已保存到: %s", path)
    except Exception as e:
        logging.error("保存配置到 %s 失败: %s", path, e)
        raise


def setup_logging(cfg: dict) -> None:
    """
    根据配置初始化 logging：同时输出到控制台和日志文件。
    只在程序启动时调用一次。
    """
    log_cfg = (cfg or {}).get("logging", {}) or {}
    log_file = log_cfg.get("file", "/data/scash-manager.log")
    level_str = (log_cfg.get("level") or "INFO").upper()

    level = getattr(logging, level_str, logging.INFO)

    # 确保日志目录存在
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
    except Exception:
        pass

    # 避免重复添加 Handler
    root = logging.getLogger()
    if root.handlers:
        return

    fmt = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"

    handlers = [
        logging.StreamHandler(),
    ]
    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        handlers.append(file_handler)
    except Exception as e:
        # 文件打不开时，至少保证控制台有日志
        logging.basicConfig(level=level, format=fmt)
        logging.error("创建日志文件失败 %s: %s", log_file, e)
        return

    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    logging.info("Logging 已初始化，level=%s, file=%s", level_str, log_file)
