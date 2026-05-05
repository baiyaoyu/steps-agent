"""配置读取模块，支持环境变量注入。"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class Config:
    """单例配置类。"""

    _instance = None
    _data: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, path: str | None = None):
        """加载配置文件。先加载 .env 文件到环境变量，再读取 config.yaml。"""
        # 先加载 .env 文件（如果存在）
        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)

        if path is None:
            path = os.environ.get("AGENT_CONFIG", "config.yaml")
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件未找到: {path.absolute()}")

        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()

        # 替换 ${ENV_VAR} 为环境变量值
        raw = self._expand_env_vars(raw)
        self._data = yaml.safe_load(raw) or {}

    def _expand_env_vars(self, text: str) -> str:
        """替换 ${VAR} 和 ${VAR:-default} 语法。"""
        pattern = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")

        def replacer(match):
            var_name = match.group(1)
            default = match.group(2)
            value = os.environ.get(var_name)
            if value is None:
                if default is not None:
                    return default
                return match.group(0)  # 保持原样
            return value

        return pattern.sub(replacer, text)

    def get(self, key: str, default: Any = None) -> Any:
        """支持点号路径，如 'models.default'。"""
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    @property
    def raw(self) -> dict:
        return self._data


# 全局配置实例
config = Config()
