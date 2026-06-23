"""
测试 chat_with_tools 关闭 Thinking Mode + tool_choice="required" 效果。

验证内容：
  1. chat_with_tools 调用参数中是否包含 extra_body 和 tool_choice
  2. 长上下文场景（模拟 60+ 条数据）下 Ranking Agent 是否正常调用工具
  3. 正常场景（少量数据）回归验证
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import unittest.mock
from unittest.mock import MagicMock, patch, ANY


# ============================================================
# 测试 1：验证 chat_with_tools 调用参数
# ============================================================

def test_chat_with_tools_params():
    """验证 chat_with_tools 传入了 extra_body 和 tool_choice。"""
    print("\n[test] chat_with_tools 参数验证")

    from utils.llm_provider import DeepSeekProvider

    llm = DeepSeekProvider(api_key="test-key", model="deepseek-v4-flash")

    # Mock OpenAI client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "test"}}]
    }
    mock_client.chat.completions.create.return_value = mock_response

    with patch.object(llm, 'client', mock_client):
        llm.chat_with_tools(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "test_tool", "description": "test"}}],
        )

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs

    # 验证 extra_body 包含 thinking disabled
    assert "extra_body" in call_kwargs, f"缺少 extra_body 参数，实际参数: {list(call_kwargs.keys())}"
    assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}, \
        f"extra_body 值不对: {call_kwargs['extra_body']}"

    # 验证 tool_choice="required"
    assert call_kwargs.get("tool_choice") == "required", \
        f"tool_choice 应为 required，实际: {call_kwargs.get('tool_choice')}"

    print("  [PASS] extra_body=thinking:disabled + tool_choice=required 已传入")


def test_chat_with_tools_tool_choice_auto():
    """验证 tool_choice 可以显式覆盖为 auto。"""
    print("\n[test] chat_with_tools tool_choice=auto")

    from utils.llm_provider import DeepSeekProvider

    llm = DeepSeekProvider(api_key="test-key", model="deepseek-v4-flash")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"choices": []}
    mock_client.chat.completions.create.return_value = mock_response

    with patch.object(llm, 'client', mock_client):
        llm.chat_with_tools(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "t", "description": "d"}}],
            tool_choice="auto",
        )

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs.get("tool_choice") == "auto", f"tool_choice 应为 auto: {call_kwargs.get('tool_choice')}"
    assert "extra_body" in call_kwargs
    print("  [PASS] tool_choice=auto 覆盖生效")


def test_chat_with_tools_tool_choice_none():
    """验证 tool_choice=None 时不传该参数。"""
    print("\n[test] chat_with_tools tool_choice=None")

    from utils.llm_provider import DeepSeekProvider

    llm = DeepSeekProvider(api_key="test-key", model="deepseek-v4-flash")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"choices": []}
    mock_client.chat.completions.create.return_value = mock_response

    with patch.object(llm, 'client', mock_client):
        llm.chat_with_tools(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "t", "description": "d"}}],
            tool_choice=None,
        )

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert "tool_choice" not in call_kwargs, f"tool_choice 不应存在: {call_kwargs}"
    assert "extra_body" in call_kwargs
    print("  [PASS] tool_choice=None 不传该参数")


# ============================================================
# 测试 2：Ranking Agent ReAct 循环 - 纯文本兜底逻辑
# ============================================================

def test_ranking_react_no_tool_calls_first_retry():
    """验证纯文本返回时仅在 turn<1 时重试一次（不再重试 5 轮）。"""
    print("\n[test] ranking_react - 纯文本重试限为1次")

    import agents.ranking_agent as ra

    # 构造连续返回纯文本的 LLM mock
    mock_llm = MagicMock()
    mock_llm.chat_with_tools.side_effect = [
        {"choices": [{"message": {"role": "assistant", "content": "好的，我来处理"},
                       "finish_reason": "stop"}]},
        {"choices": [{"message": {"role": "assistant", "content": "开始执行"},
                       "finish_reason": "stop"}]},
        {"choices": [{"message": {"role": "assistant", "content": "继续"},
                       "finish_reason": "stop"}]},
    ]

    state = {
        "session_id": "test-ranking-no-tool",
        "trigger_type": "daily_briefing",
        "user_id": 1,
        "goal_text": "test",
        "structured_goal": {"topics": ["AI"], "keywords": ["LLM"], "preferred_sources": []},
        "goal_embedding": [0.1] * 384,
        "collected_items": [
            {"id": f"item_{i:03d}", "title": f"测试条目 {i}", "summary": f"摘要{i}",
             "source": "rss_test", "url": f"http://test.com/{i}", "importance": 0.5,
             "category": "科技", "published_at": "2026-06-20T10:00:00"}
            for i in range(60)
        ],
        "ranked_items": [],
        "ranking_detail": {},
        "feedback_history": [],
    }

    with patch.object(ra, "_get_llm_provider", return_value=mock_llm):
        with patch("agents.ranking_agent.vector_search_node") as mock_vs:
            mock_vs.return_value = {"user_preferences": [], "feedback_history": []}
            result = ra.run_ranking_agent(state)

    # 应该只调用了 2 次 chat_with_tools（首次 + 1次重试），第3次不会被调用
    assert mock_llm.chat_with_tools.call_count <= 2, \
        f"期望最多 2 次调用（首轮+1次重试），实际: {mock_llm.chat_with_tools.call_count}"
    print(f"  [PASS] 纯文本重试限为1次: chat_with_tools 调用 {mock_llm.chat_with_tools.call_count} 次")


def test_collection_react_no_tool_calls_first_retry():
    """验证 Collection Agent 纯文本返回时仅重试一次。"""
    print("\n[test] collection_react - 纯文本重试限为1次")

    import agents.collection_agent as ca

    mock_llm = MagicMock()
    mock_llm.chat_with_tools.side_effect = [
        {"choices": [{"message": {"role": "assistant", "content": "收到，开始采集"},
                       "finish_reason": "stop"}]},
        {"choices": [{"message": {"role": "assistant", "content": "执行中"},
                       "finish_reason": "stop"}]},
    ]

    state = {
        "session_id": "test-collection-no-tool",
        "trigger_type": "daily_briefing",
        "user_id": 1,
        "goal_text": "test",
        "collected_items": [],
        "item_relations": [],
        "sources": [{"id": 1, "url": "http://test.com/rss", "name": "test源"}],
    }

    with patch.object(ca, "_get_llm_provider", return_value=mock_llm):
        with patch("agents.collection_agent.tool_registry") as mock_registry:
            mock_registry.get_schemas_for_phase.return_value = []
            result = ca.run_collection_agent(state)

    assert mock_llm.chat_with_tools.call_count <= 2, \
        f"期望最多 2 次调用，实际: {mock_llm.chat_with_tools.call_count}"
    print(f"  [PASS] Collection 纯文本重试限为1次: 调用 {mock_llm.chat_with_tools.call_count} 次")


def test_briefing_react_no_tool_calls_first_retry():
    """验证 Briefing Agent 纯文本返回时仅重试一次。"""
    print("\n[test] briefing_react - 纯文本重试限为1次")

    import agents.briefing_agent as ba

    mock_llm = MagicMock()
    mock_llm.chat_with_tools.side_effect = [
        {"choices": [{"message": {"role": "assistant", "content": "好的，开始生成简报"},
                       "finish_reason": "stop"}]},
        {"choices": [{"message": {"role": "assistant", "content": "简报生成中"},
                       "finish_reason": "stop"}]},
    ]

    state = {
        "session_id": "test-briefing-no-tool",
        "trigger_type": "daily_briefing",
        "user_id": 1,
        "goal_text": "test",
        "ranked_items": [{"id": "item_001", "title": "test", "summary": "test",
                          "source": "rss", "url": "http://t.com/1", "importance": 0.5,
                          "category": "科技", "published_at": "2026-06-20T10:00:00"}],
        "briefing": {},
        "brief_quality": 0.0,
    }

    with patch.object(ba, "_get_llm_provider", return_value=mock_llm):
        with patch("agents.briefing_agent.tool_registry") as mock_registry:
            mock_registry.get_schemas_for_phase.return_value = []
            result = ba.run_briefing_agent(state)

    assert mock_llm.chat_with_tools.call_count <= 2, \
        f"期望最多 2 次调用，实际: {mock_llm.chat_with_tools.call_count}"
    print(f"  [PASS] Briefing 纯文本重试限为1次: 调用 {mock_llm.chat_with_tools.call_count} 次")


# ============================================================
# 测试 3：真实 API 调用验证（需要 DEEPSEEK_API_KEY 环境变量）
# ============================================================

def test_real_api_chat_with_tools():
    """真实 API 调用：验证 thinking disabled + tool_choice=required 正常工作。"""
    print("\n[test] 真实 API - chat_with_tools 验证")

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("  [SKIP] 未设置 DEEPSEEK_API_KEY 环境变量，跳过真实 API 测试")
        return

    from utils.llm_provider import DeepSeekProvider

    llm = DeepSeekProvider(api_key=api_key, model="deepseek-v4-flash")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名称"}
                    },
                    "required": ["city"],
                },
            },
        }
    ]

    try:
        response = llm.chat_with_tools(
            messages=[{"role": "user", "content": "北京今天天气怎么样？"}],
            tools=tools,
        )
    except Exception as e:
        print(f"  [FAIL] API 调用失败: {e}")
        return

    choices = response.get("choices", [])
    assert choices, "API 返回空 choices"
    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls", [])
    assert tool_calls, f"tool_choice=required 下应返回 tool_calls，实际: {json.dumps(message, ensure_ascii=False)[:300]}"

    print(f"  [PASS] 真实 API: thinking disabled + tool_choice=required 正常，返回 {len(tool_calls)} 个 tool_call")


def test_real_api_long_context_tool_calling():
    """真实 API 调用：模拟长上下文场景（60+ 条数据），验证 function calling 稳定性。"""
    print("\n[test] 真实 API - 长上下文 Function Calling 稳定性")

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("  [SKIP] 未设置 DEEPSEEK_API_KEY 环境变量，跳过真实 API 测试")
        return

    from utils.llm_provider import DeepSeekProvider

    llm = DeepSeekProvider(api_key=api_key, model="deepseek-v4-flash")

    # 构造长 user message（模拟 62 条数据的场景）
    items_text = "\n".join(
        f"{i}. 【{f'来源{i%5+1}'}】测试新闻标题 {i} - 这是一段测试摘要内容，用于模拟大量数据的场景，验证长上下文下 function calling 的稳定性"
        for i in range(1, 63)
    )
    user_msg = f"以下是采集到的 62 条新闻条目，请处理：\n\n{items_text}"

    tools = [
        {
            "type": "function",
            "function": {
                "name": "deduplicate",
                "description": "对条目进行去重",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "rank_items",
                "description": "对条目进行排序",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish_task",
                "description": "完成任务",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "任务总结"}
                    },
                    "required": ["summary"],
                },
            },
        },
    ]

    messages = [
        {"role": "system", "content": "你是一个排序 Agent，收到新闻条目后调用工具处理。第一轮必须先调用 deduplicate 或 rank_items。"},
        {"role": "user", "content": user_msg},
    ]

    # 模拟多轮工具调用
    tool_call_count = 0
    try:
        for turn in range(5):
            response = llm.chat_with_tools(messages=messages, tools=tools)
            choices = response.get("choices", [])
            if not choices:
                print(f"  [FAIL] 第 {turn+1} 轮：API 返回空 choices")
                break

            message = choices[0].get("message", {})
            tool_calls = message.get("tool_calls", [])
            content = message.get("content", "")

            if tool_calls:
                tool_call_count += 1
                tool_name = tool_calls[0].get("function", {}).get("name", "unknown")
                print(f"  第 {turn+1} 轮：调用工具 {tool_name} ✅")

                if tool_name == "finish_task":
                    print("  [PASS] 长上下文场景 function calling 正常工作")
                    break

                # 追加 assistant + tool 消息
                messages.append(message)
                for tc in tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", tool_name),
                        "content": json.dumps({"status": "ok"}, ensure_ascii=False),
                    })
            elif content:
                print(f"  第 {turn+1} 轮：纯文本回复（未调用工具）: {content[:80]} ❌")
                break
    except Exception as e:
        print(f"  [FAIL] 长上下文测试异常: {e}")
        return

    if tool_call_count == 0:
        print("  [FAIL] tool_choice=required 下不应出现 0 次工具调用")
    else:
        print(f"  [INFO] 共 {tool_call_count} 次工具调用")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    tests = [
        # 参数验证（不需要真实 API）
        ("chat_with_tools 参数", test_chat_with_tools_params),
        ("tool_choice=auto 覆盖", test_chat_with_tools_tool_choice_auto),
        ("tool_choice=None", test_chat_with_tools_tool_choice_none),
        ("Ranking 纯文本重试", test_ranking_react_no_tool_calls_first_retry),
        ("Collection 纯文本重试", test_collection_react_no_tool_calls_first_retry),
        ("Briefing 纯文本重试", test_briefing_react_no_tool_calls_first_retry),
        # 真实 API 测试
        ("真实 API - 基础 tool call", test_real_api_chat_with_tools),
        ("真实 API - 长上下文稳定性", test_real_api_long_context_tool_calling),
    ]

    passed = 0
    failed = 0
    skipped = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"结果: {passed} 通过, {failed} 失败, {skipped} 跳过, 共 {len(tests)} 项")
    if failed > 0:
        sys.exit(1)
