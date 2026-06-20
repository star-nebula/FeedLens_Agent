"""
FeedLens LLM Provider 抽象层。

提供统一的 LLM 调用接口，支持：
  - DeepSeek Chat（主力，OpenAI 兼容）
  - 预留 fallback 扩展点

Usage:
    from utils.llm_provider import LLMProvider, DeepSeekProvider
    llm = DeepSeekProvider(api_key="...", model="deepseek-chat")
    reply = llm.chat([{"role": "user", "content": "Hello"}])
"""

from abc import ABC, abstractmethod
from openai import OpenAI


class LLMProvider(ABC):
    """LLM 调用抽象接口。"""

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> str:
        """发送对话消息，返回文本回复。"""
        ...

    @abstractmethod
    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> dict:
        """发送对话消息并支持 Function Calling，返回 OpenAI 格式响应。"""
        ...


class DeepSeekProvider(LLMProvider):
    """DeepSeek Chat 实现（OpenAI 兼容接口）。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
    ):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response.choices[0].message.content

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> dict:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return response.model_dump()
