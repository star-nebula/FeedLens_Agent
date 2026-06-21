"""执行栅栏 — 同一用户的管线串行化，防止并发写偏好向量。

场景：APScheduler 定时触发、UI 手动触发、重大事件破例推送可能
同时发生，导致两个管线并发执行，偏好向量的"读-改-写"会丢更新。

单进程内有效（Streamlit + APScheduler 同进程场景）。
跨进程部署需替换为分布式锁。
"""

import threading


class ExecutionFence:
    """per-user 锁管理器。

    同一 user_id 的管线串行执行；不同 user_id 可并行。
    """

    def __init__(self):
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    def acquire(self, user_id: int) -> threading.Lock:
        with self._guard:
            if user_id not in self._locks:
                self._locks[user_id] = threading.Lock()
            return self._locks[user_id]


# 全局单例
_fence = ExecutionFence()


def try_acquire_pipeline(user_id: int):
    """尝试获取管线锁。

    Returns:
        锁对象则获取成功（调用方负责在 finally 中 release）；
        None 表示该 user 已有管线在执行，应跳过本次触发。
    """
    lock = _fence.acquire(user_id)
    if lock.acquire(blocking=False):
        return lock
    return None
