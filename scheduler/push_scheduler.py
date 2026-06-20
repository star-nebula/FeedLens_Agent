"""
推送调度器 — APScheduler CronTrigger 定时触发 + 重大事件破例推送。

功能：
  - 每日定时触发简报生成（配置 cron_time）
  - 重大事件检测（score > threshold 且时效 < freshness_hours）立即推送
  - 与主 Agent StateGraph 集成
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Optional, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.config import load_config

# ============================================================
# 调度器
# ============================================================

def is_breaking_news(
    item: dict,
    score_threshold: float = 0.85,
    freshness_hours: int = 2,
) -> bool:
    """判断是否为重大事件。

    条件：
      - 条目得分 > score_threshold（配置: breaking_news.score_threshold）
      - 发布时间距今 < freshness_hours（配置: breaking_news.freshness_hours）

    Returns:
        True if 重大事件，否则 False
    """
    score = item.get("_score", 0.0)
    if score < score_threshold:
        return False

    published_at = item.get("published_at")
    if not published_at:
        return False

    try:
        pub_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        hours_diff = (datetime.now() - pub_time).total_seconds() / 3600
        if hours_diff > freshness_hours:
            return False
    except Exception:
        return False

    return True


def detect_breaking_events(
    ranked_items: list,
    score_threshold: float = 0.85,
    freshness_hours: int = 2,
) -> list:
    """从 ranked_items 中检测所有重大事件。

    Returns:
        重大事件条目列表
    """
    breaking = []
    for item in ranked_items:
        if is_breaking_news(item, score_threshold, freshness_hours):
            breaking.append(item)

    if breaking:
        print(f"[scheduler] 检测到 {len(breaking)} 条重大事件", flush=True)
        for item in breaking:
            print(f"  重大事件: {item.get('title', 'untitled')} (score={item.get('_score', 0):.3f})", flush=True)

    return breaking


# ============================================================
# 调度器
# ============================================================

class FeedLensScheduler:
    """FeedLens 推送调度器。

    支持：
      - 每日定时触发（APScheduler CronTrigger）
      - 立即触发（用于重大事件）
    """

    def __init__(self):
        self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._config = load_config()
        self._cron_time = self._config.get("scheduler", {}).get("cron_time", "06:00")
        self._timezone = self._config.get("scheduler", {}).get("timezone", "Asia/Shanghai")
        self._breaking_threshold = self._config.get("breaking_news", {}).get("score_threshold", 0.85)
        self._breaking_freshness = self._config.get("breaking_news", {}).get("freshness_hours", 2)
        self._callback: Optional[Callable] = None

    def set_callback(self, callback: Callable):
        """设置触发回调函数。"""
        self._callback = callback

    def _parse_cron_time(self) -> tuple:
        """解析 cron_time 配置，返回 hour 和 minute。"""
        parts = self._cron_time.split(":")
        hour = int(parts[0]) if len(parts) > 0 else 6
        minute = int(parts[1]) if len(parts) > 1 else 0
        return hour, minute

    def start_daily(self):
        """启动每日定时调度。"""
        hour, minute = self._parse_cron_time()

        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=self._timezone,
        )

        self._scheduler.add_job(
            self._on_scheduled_trigger,
            trigger=trigger,
            id="daily_briefing",
            name="每日简报",
            replace_existing=True,
        )

        print(f"[scheduler] 每日定时调度已启动: {hour:02d}:{minute:02d} ({self._timezone})", flush=True)

    def _on_scheduled_trigger(self):
        """定时触发回调。"""
        print(f"[scheduler] 定时触发: {datetime.now().isoformat()}", flush=True)
        if self._callback:
            self._callback(trigger_type="daily_briefing", push_immediate=False)

    def trigger_now(self, trigger_type: str = "manual", push_immediate: bool = False):
        """手动立即触发。

        Args:
            trigger_type: 触发类型（manual / breaking_news）
            push_immediate: 是否立即推送（用于重大事件）
        """
        print(f"[scheduler] 立即触发: trigger_type={trigger_type}, push_immediate={push_immediate}", flush=True)
        if self._callback:
            self._callback(trigger_type=trigger_type, push_immediate=push_immediate)

    def trigger_breaking_news(self, items: list):
        """检测重大事件并触发立即推送。

        Args:
            items: ranked_items 列表
        """
        breaking = detect_breaking_events(
            items,
            score_threshold=self._breaking_threshold,
            freshness_hours=self._breaking_freshness,
        )
        if breaking:
            self.trigger_now(trigger_type="breaking_news", push_immediate=True)

    def stop(self):
        """停止调度器。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            print("[scheduler] 调度器已停止", flush=True)

    def start(self):
        """启动调度器（后台运行）。"""
        if not self._scheduler.running:
            self._scheduler.start()
            print("[scheduler] 调度器已启动", flush=True)


# ============================================================
# 单例实例
# ============================================================

_scheduler_instance: Optional[FeedLensScheduler] = None


def get_scheduler() -> FeedLensScheduler:
    """获取调度器单例。"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = FeedLensScheduler()
    return _scheduler_instance


def start_daily_scheduler(callback: Callable):
    """启动每日调度器（便捷函数）。"""
    scheduler = get_scheduler()
    scheduler.set_callback(callback)
    scheduler.start_daily()
    scheduler.start()
    return scheduler


# ============================================================
# CLI 测试入口
# ============================================================

def _demo_callback(trigger_type: str, push_immediate: bool):
    print(f"[DEMO] 收到触发: trigger_type={trigger_type}, push_immediate={push_immediate}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="FeedLens 调度器")
    parser.add_argument("--once", action="store_true", help="单次触发（测试用）")
    parser.add_argument("--detect", action="store_true", help="测试重大事件检测")
    args = parser.parse_args()

    if args.detect:
        print("=" * 50)
        print("重大事件检测测试")
        print("=" * 50)

        now = datetime.now()
        test_items = [
            {"id": "1", "title": "突发：某重大事件发生", "_score": 0.90, "published_at": (now - timedelta(hours=1)).isoformat()},
            {"id": "2", "title": "普通新闻", "_score": 0.60, "published_at": (now - timedelta(hours=3)).isoformat()},
            {"id": "3", "title": "热点新闻", "_score": 0.88, "published_at": (now - timedelta(minutes=30)).isoformat()},
            {"id": "4", "title": "旧闻", "_score": 0.95, "published_at": (now - timedelta(days=1)).isoformat()},
        ]

        breaking = detect_breaking_events(test_items)
        print(f"\n检测结果: {len(breaking)} 条重大事件")
        for item in breaking:
            print(f"  - {item['title']} (score={item['_score']:.3f})")

    elif args.once:
        print("单次触发测试")
        scheduler = FeedLensScheduler()
        scheduler.trigger_now(trigger_type="manual", push_immediate=False)

    else:
        print("启动每日调度器...")
        scheduler = start_daily_scheduler(_demo_callback)
        print("调度器运行中，按 Ctrl+C 退出")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.stop()


if __name__ == "__main__":
    main()
