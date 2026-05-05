from .base import BaseModel
from .deepseek import DeepSeekModel
from .gemini import GeminiModel
from .qwen import QwenModel

__all__ = ["BaseModel", "DeepSeekModel", "GeminiModel", "QwenModel"]


_MODEL_MAP = {
    "deepseek": DeepSeekModel,
    "gemini": GeminiModel,
    "qwen": QwenModel,
}


def create_model(provider: str, api_key: str, base_url: str, model: str) -> BaseModel:
    """根据 provider 名称创建对应模型实例。"""
    cls = _MODEL_MAP.get(provider)
    if cls is None:
        raise ValueError(f"不支持的模型提供商: {provider}")
    return cls(api_key=api_key, base_url=base_url, model=model)
