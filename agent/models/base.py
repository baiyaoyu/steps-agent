"""模型基类与统一调用接口。"""

from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseModel(ABC):
    """LLM 模型基类。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    @abstractmethod
    async def chat(self, messages: list[dict], stream: bool = False) -> str | AsyncIterator[str]:
        """对话调用。stream=False 返回完整字符串，stream=True 返回文本片段迭代器。"""
        ...
