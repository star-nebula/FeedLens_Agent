"""
FeedLens LLM Provider abstraction layer.

Provides a unified LLM call interface, supporting:
  - DeepSeek Chat (primary, OpenAI-compatible)
  - Reserved fallback extension point

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
        tool_choice: str = "required",
        **kwargs,
    ) -> dict:
        """发送对话消息并支持 Function Calling。

        Args:
            tool_choice: 工具选择策略，默认 "required" 强制调用工具。
                         设为 "auto" 可恢复为模型自主决定。
                         设为 None 时不传 tool_choice 参数（完全由模型决定）。
        """
        create_kwargs = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if tool_choice is not None:
            create_kwargs["tool_choice"] = tool_choice

        create_kwargs.update(kwargs)
        response = self.client.chat.completions.create(**create_kwargs)
        return response.model_dump()


# ============================================================
# LLMRouter — 模型回退链（P4）
# ============================================================

class LLMRouter(LLMProvider):
    """按顺序尝试多个 Provider，首个成功即返回；全部失败才抛。

    用于主 LLM 不可用时自动回退到备用 Provider，避免全链路降级。
    """

    def __init__(self, providers: list[LLMProvider], names: list[str] = None):
        self._providers = providers
        self._names = names or [getattr(p, "model", f"provider_{i}") for i, p in enumerate(providers)]

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 4096, **kwargs) -> str:
        last_err = None
        for i, p in enumerate(self._providers):
            try:
                return p.chat(messages, temperature=temperature, max_tokens=max_tokens, **kwargs)
            except Exception as e:
                name = self._names[i] if i < len(self._names) else f"provider_{i}"
                print(f"[llm_router] {name} 调用失败: {e}，尝试下一个", flush=True)
                last_err = e
        raise RuntimeError(f"所有 LLM Provider 均失败，最后错误: {last_err}")

    def chat_with_tools(self, messages: list[dict], tools: list[dict], temperature: float = 0.7, max_tokens: int = 4096, **kwargs) -> dict:
        last_err = None
        for i, p in enumerate(self._providers):
            try:
                return p.chat_with_tools(messages, tools, temperature=temperature, max_tokens=max_tokens, **kwargs)
            except Exception as e:
                name = self._names[i] if i < len(self._names) else f"provider_{i}"
                print(f"[llm_router] {name} (tools) 调用失败: {e}，尝试下一个", flush=True)
                last_err = e
        raise RuntimeError(f"所有 LLM Provider 均失败，最后错误: {last_err}")
