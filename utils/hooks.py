"""Hook system ? pluggable strategy extension mechanism (P1).

Extract hard-coded strategy logic from observe/reflect/push/rank nodes
into pluggable Hooks, so new strategies can be added without modifying
core orchestration code.

Each Hook receives dict ctx (state fragment), returns dict (strategy result).
Caller merges results via dict.update(), preserving uncovered fields.

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

# 注意：默认 hook 实现（observe.evaluate / reflect.check / push.decide）
# 由 main_agent.py 在模块级别通过 hooks.register() 注册。
# 使用前需确保已导入 main_agent（或导入 app.py 等上层入口）。