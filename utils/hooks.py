"""Hook 系统 — 策略点的可注册扩展机制（P1）。

将 observe/reflect/push/rank 等节点的硬编码策略逻辑提取为
可注册的 Hook，后续新增策略无需改核心编排代码。

每个 Hook 接收 dict ctx（状态片段），返回 dict（策略结果字段）。
调用方通过 dict.update() 合并结果，保留未覆盖字段。

Usage:
    from utils.hooks import hooks
    hooks.register("observe.evaluate", my_custom_eval)
    ctx = hooks.run("observe.evaluate", ctx)
"""

from typing import Callable


class HookRegistry:
    """轻量 Hook 注册表。

    同一个 hook 点可注册多个函数，按注册顺序依次执行。
    每个函数接收并返回（或修改）dict；异常不传播到其他 Hook。
    """

    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {}

    def register(self, name: str, fn: Callable) -> None:
        """注册一个 hook 函数。"""
        self._hooks.setdefault(name, []).append(fn)

    def run(self, name: str, ctx: dict) -> dict:
        """依次执行该 hook 点下所有函数，合并结果到 ctx。"""
        result = dict(ctx)
        for fn in self._hooks.get(name, []):
            try:
                out = fn(ctx)
                if isinstance(out, dict):
                    result.update(out)
            except Exception as e:
                print(f"[hooks] {name} 执行失败: {e}", flush=True)
        return result


# 全局单例
hooks = HookRegistry()