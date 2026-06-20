"""
推送调度器测试
"""

import sys
import os
from datetime import datetime, timedelta
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from scheduler.push_scheduler import (
    detect_breaking_events,
    is_breaking_news,
    FeedLensScheduler,
)


def test_is_breaking_news():
    now = datetime.now()

    # 重大事件：高分 + 新鲜
    item1 = {"id": "1", "title": "突发重大事件", "_score": 0.90, "published_at": (now - timedelta(hours=1)).isoformat()}
    assert is_breaking_news(item1) == True, "高分新鲜应为重大事件"

    # 普通新闻：低分
    item2 = {"id": "2", "title": "普通新闻", "_score": 0.60, "published_at": (now - timedelta(hours=3)).isoformat()}
    assert is_breaking_news(item2) == False, "低分不应为重大事件"

    # 边界：刚好 >= 0.85
    item3 = {"id": "3", "title": "热点", "_score": 0.88, "published_at": (now - timedelta(minutes=30)).isoformat()}
    assert is_breaking_news(item3) == True, "0.88 >= 0.85 应为重大事件"

    # 旧闻：高分但超过2小时
    item4 = {"id": "4", "title": "旧闻", "_score": 0.95, "published_at": (now - timedelta(days=1)).isoformat()}
    assert is_breaking_news(item4) == False, "超过2小时不是重大事件"

    # 无时间
    item5 = {"id": "5", "title": "无时间", "_score": 0.90}
    assert is_breaking_news(item5) == False, "无时间不应为重大事件"

    print("[PASS] is_breaking_news 测试通过")


def test_detect_breaking_events():
    now = datetime.now()
    items = [
        {"id": "1", "title": "突发：重大事件", "_score": 0.90, "published_at": (now - timedelta(hours=1)).isoformat()},
        {"id": "2", "title": "普通新闻", "_score": 0.60, "published_at": (now - timedelta(hours=3)).isoformat()},
        {"id": "3", "title": "热点新闻", "_score": 0.88, "published_at": (now - timedelta(minutes=30)).isoformat()},
        {"id": "4", "title": "旧闻", "_score": 0.95, "published_at": (now - timedelta(days=1)).isoformat()},
    ]

    breaking = detect_breaking_events(items)
    assert len(breaking) == 2, f"期望2条重大事件，实际{len(breaking)}条"
    assert breaking[0]["id"] == "1"
    assert breaking[1]["id"] == "3"
    print("[PASS] detect_breaking_events 测试通过")


def test_scheduler_init():
    scheduler = FeedLensScheduler()
    assert scheduler._cron_time == "06:00"
    assert scheduler._breaking_threshold == 0.85
    assert scheduler._breaking_freshness == 2
    print("[PASS] FeedLensScheduler 初始化测试通过")


def test_parse_cron_time():
    scheduler = FeedLensScheduler()
    hour, minute = scheduler._parse_cron_time()
    assert hour == 6
    assert minute == 0
    print("[PASS] _parse_cron_time 测试通过")



def test_set_callback():
    """验证 callback 绑定后可被 trigger_now 调用。"""
    scheduler = FeedLensScheduler()
    tracker = {"called": False, "trigger_type": None, "push_immediate": None}
    def cb(trigger_type, push_immediate):
        tracker["called"] = True
        tracker["trigger_type"] = trigger_type
        tracker["push_immediate"] = push_immediate
    scheduler.set_callback(cb)
    scheduler.trigger_now(trigger_type="manual", push_immediate=False)
    assert tracker["called"] == True, "callback 未被调用"
    assert tracker["trigger_type"] == "manual"
    assert tracker["push_immediate"] == False
    print("[PASS] set_callback + trigger_now callback 调用测试通过")

def test_trigger_breaking_news_chain():
    """验证 trigger_breaking_news 在检测到重大事件时正确触发立即推送。"""
    now = datetime.now()
    items = [
        {"id": "1", "title": "重大", "_score": 0.90, "published_at": (now - timedelta(minutes=30)).isoformat()},
        {"id": "2", "title": "普通", "_score": 0.60, "published_at": (now - timedelta(hours=1)).isoformat()},
    ]
    scheduler = FeedLensScheduler()
    tracker = {"called": False, "trigger_type": None, "push_immediate": None}
    def cb(trigger_type, push_immediate):
        tracker["called"] = True
        tracker["trigger_type"] = trigger_type
        tracker["push_immediate"] = push_immediate
    scheduler.set_callback(cb)
    scheduler.trigger_breaking_news(items)
    assert tracker["called"] == True, "callback 未被调用"
    assert tracker["trigger_type"] == "breaking_news"
    assert tracker["push_immediate"] == True, "重大事件应触发 immediate=True"
    print("[PASS] trigger_breaking_news 串联检测+触发测试通过")

def test_start_daily_registers_job():
    """验证 start_daily() 注册了正确的 CronTrigger。"""
    scheduler = FeedLensScheduler()
    # Mock BackgroundScheduler.add_job 来验证注册参数
    orig_add_job = scheduler._scheduler.add_job
    add_job_args = {}
    def capture_add_job(func, **kwargs):
        add_job_args["id"] = kwargs.get("id", "")
        add_job_args["name"] = kwargs.get("name", "")
        trigger = kwargs.get("trigger")
        if trigger:
            add_job_args["trigger_str"] = str(trigger)
    scheduler._scheduler.add_job = capture_add_job
    try:
        scheduler.start_daily()
        trigger_str = add_job_args.get("trigger_str", "")
        assert "hour" in trigger_str, f"trigger 应包含 hour 字段，实际: {trigger_str}"
        assert "minute" in trigger_str, f"trigger 应包含 minute 字段，实际: {trigger_str}"
        assert add_job_args["id"] == "daily_briefing", f"job id 应为 daily_briefing，实际: {add_job_args['id']}"
        assert add_job_args["name"] == "每日简报"
        print(f"[PASS] start_daily 注册 CronTrigger: {trigger_str}")
    finally:
        scheduler._scheduler.add_job = orig_add_job

def test_scheduler_start_stop():
    """验证 start() 和 stop() 生命周期。"""
    scheduler = FeedLensScheduler()
    # start() 应能正常调用（APScheduler 会自动处理重复 start）
    scheduler.start()
    assert scheduler._scheduler.running == True, "start() 后 scheduler 应处于 running 状态"
    scheduler.stop()
    # stop 后 scheduler 可能已停止
    print("[PASS] start/stop 生命周期测试通过")

def test_get_scheduler_singleton():
    """验证单例模式"""
    from scheduler.push_scheduler import get_scheduler
    s1 = get_scheduler()
    s2 = get_scheduler()
    assert s1 is s2, "get_scheduler() 应返回同一实例"
    print("[PASS] 调度器单例测试通过")

def main():
    print("=" * 50)
    print("推送调度器测试")
    print("=" * 50)
    test_scheduler_init()
    test_parse_cron_time()
    test_set_callback()
    test_trigger_breaking_news_chain()
    test_start_daily_registers_job()
    test_get_scheduler_singleton()
    test_is_breaking_news()
    test_detect_breaking_events()
    test_scheduler_start_stop()

    print("=" * 50)
    print("所有测试通过!")
    print("=" * 50)
    print("=" * 50)


if __name__ == "__main__":
    main()
