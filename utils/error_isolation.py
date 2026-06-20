"""
任务级错误隔离模块。

提供错误隔离装饰器和上下文管理器，确保：
1. 单次任务失败不阻塞下次执行
2. 错误信息正确记录到日志和数据库
3. 降级策略（失败时返回默认值或空结果）
"""

import functools
from typing import Callable, Any, Optional
from utils.logging_config import get_logger, log_error


logger = get_logger("error_isolation")


def task_error_isolation(
    task_name: str,
    default_return: Any = None,
    max_retries: int = 1,
    retry_delay_ms: int = 1000,
    log_to_db: bool = True,
):
    """任务级错误隔离装饰器。

    Args:
        task_name: 任务名称（用于日志记录）
        default_return: 失败时的默认返回值
        max_retries: 最大重试次数
        retry_delay_ms: 重试延迟（毫秒）
        log_to_db: 是否记录到数据库

    Returns:
        装饰后的函数
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    logger.info(
                        "task_start",
                        task_name=task_name,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                    )

                    result = func(*args, **kwargs)

                    logger.info(
                        "task_success",
                        task_name=task_name,
                        attempt=attempt + 1,
                    )
                    return result

                except Exception as e:
                    last_exception = e
                    logger.error(
                        "task_failed",
                        task_name=task_name,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error=str(e),
                        exc_info=e,
                    )

                    if attempt < max_retries:
                        import time
                        time.sleep(retry_delay_ms / 1000)
                        logger.info(
                            "task_retry",
                            task_name=task_name,
                            attempt=attempt + 2,
                        )

            # 所有重试失败，返回默认值
            logger.warning(
                "task_giving_up",
                task_name=task_name,
                max_retries=max_retries,
                error=str(last_exception),
            )

            return default_return

        return wrapper

    return decorator


class TaskErrorIsolator:
    """任务级错误隔离上下文管理器。"""

    def __init__(
        self,
        task_name: str,
        default_return: Any = None,
        log_to_db: bool = True,
    ):
        self.task_name = task_name
        self.default_return = default_return
        self.log_to_db = log_to_db
        self.success = False

    def __enter__(self):
        logger.info("task_start", task_name=self.task_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            logger.error(
                "task_failed",
                task_name=self.task_name,
                error=str(exc_val),
                exc_info=exc_val,
            )
            self.success = False
            return True  # 吞掉异常，返回默认值
        else:
            logger.info("task_success", task_name=self.task_name)
            self.success = True
            return False


def run_with_isolation(
    task_name: str,
    func: Callable,
    *args,
    default_return: Any = None,
    **kwargs,
) -> Any:
    """在错误隔离环境中运行函数。

    Args:
        task_name: 任务名称
        func: 要执行的函数
        *args: 函数位置参数
        default_return: 失败时的默认返回值
        **kwargs: 函数关键字参数

    Returns:
        函数执行结果或默认值
    """
    try:
        logger.info("task_start", task_name=task_name)
        result = func(*args, **kwargs)
        logger.info("task_success", task_name=task_name)
        return result
    except Exception as e:
        logger.error(
            "task_failed",
            task_name=task_name,
            error=str(e),
            exc_info=e,
        )
        return default_return


def isolate_agent_node(node_func: Callable) -> Callable:
    """Agent 节点错误隔离装饰器。

    专为 LangGraph 节点设计，确保节点失败时不中断整个图的执行。

    Args:
        node_func: LangGraph 节点函数

    Returns:
        装饰后的节点函数
    """

    @functools.wraps(node_func)
    def wrapper(state: dict) -> dict:
        node_name = node_func.__name__

        try:
            logger.info(
                "node_start",
                node_name=node_name,
                state_keys=list(state.keys()),
            )

            result = node_func(state)

            logger.info(
                "node_success",
                node_name=node_name,
                result_keys=list(result.keys()) if isinstance(result, dict) else "N/A",
            )

            return result

        except Exception as e:
            logger.error(
                "node_failed",
                node_name=node_name,
                error=str(e),
                exc_info=e,
                state_keys=list(state.keys()),
            )

            # 返回包含错误信息的状态，而不是中断执行
            error_state = {
                **state,
                "error": {
                    "node": node_name,
                    "message": str(e),
                },
            }

            # 如果节点有特定的返回键，设置为空值
            if node_name == "collection_node":
                error_state["collected_items"] = []
            elif node_name == "ranking_node":
                error_state["ranked_items"] = []
            elif node_name == "briefing_node":
                error_state["briefing"] = None

            return error_state

    return wrapper
