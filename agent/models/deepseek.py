from openai import AsyncOpenAI

from .base import BaseModel


class DeepSeekModel(BaseModel):
    async def chat(self, messages, stream=False):
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=stream,
        )
        if not stream:
            return response.choices[0].message.content or ""

        async def _stream():
            async for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content

        return _stream()
