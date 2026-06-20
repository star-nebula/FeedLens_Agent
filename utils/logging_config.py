"""
结构化日志配置模块。

使用 structlog 实现统一的结构化日志，支持：
- 控制台输出（开发环境）
- 文件输出（JSON格式，生产环境）
- 日志级别控制
- 自定义处理器
"""

import structlog
from structlog.processors import JSONRenderer, ExceptionPrettyPrinter
from datetime import datetime
import os


def _get_log_dir() -> str:
    """获取日志目录。"""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _add_timestamp(_, __, event_dict):
    """添加时间戳。"""
    event_dict["timestamp"] = datetime.now().isoformat()
    return event_dict


def _add_level(_, __, event_dict):
    """添加日志级别。"""
    level = event_dict.get("level")
    if level:
        event_dict["level"] = level.upper()
    return event_dict


def configure_logging(log_level: str = "INFO", log_format: str = "console"):
    """配置结构化日志。

    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        log_format: 输出格式 (console, json)
    """
    # 基础处理器链
    processors = [
        structlog.stdlib.add_log_level,
        _add_timestamp,
        _add_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        # JSON 格式（文件输出）
        log_file = os.path.join(_get_log_dir(), f"feedlens_{datetime.now().strftime('%Y%m%d')}.log")
        processors.append(
            structlog.processors.JSONRenderer(indent=2)
        )
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )
    else:
        # 控制台格式
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=ExceptionPrettyPrinter(),
            )
        )
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.BoundLogger,
        )

    # 设置日志级别
    import logging
    logging.basicConfig(level=getattr(logging, log_level.upper()))


def get_logger(name: str = "feedlens") -> structlog.BoundLogger:
    """获取结构化日志实例。

    Args:
        name: 日志器名称

    Returns:
        structlog.BoundLogger 实例
    """
    return structlog.get_logger(name)


def log_event(
    logger: structlog.BoundLogger,
    level: str,
    event: str,
    **kwargs,
):
    """记录事件日志。

    Args:
        logger: 日志器实例
        level: 日志级别 (debug, info, warning, error)
        event: 事件描述
        **kwargs: 附加字段
    """
    method = getattr(logger, level, logger.info)
    method(event, **kwargs)


def log_error(
    logger: structlog.BoundLogger,
    event: str,
    exc_info: Exception = None,
    **kwargs,
):
    """记录错误日志。

    Args:
        logger: 日志器实例
        event: 事件描述
        exc_info: 异常信息
        **kwargs: 附加字段
    """
    logger.error(
        event,
        exc_info=exc_info,
        **kwargs,
    )


def log_metric(
    logger: structlog.BoundLogger,
    metric_name: str,
    value: float,
    **kwargs,
):
    """记录指标日志。

    Args:
        logger: 日志器实例
        metric_name: 指标名称
        value: 指标值
        **kwargs: 附加字段
    """
    logger.info(
        "metric",
        metric_name=metric_name,
        value=value,
        **kwargs,
    )


# 初始化默认日志配置
configure_logging()
