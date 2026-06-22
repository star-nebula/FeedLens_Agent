## FeedLens 改进验证与微调完整流程

### 阶段一：单元回归测试（确保改进不破坏现有行为）

按依赖从底层到顶层依次执行，每步确认 PASS：

```powershell
# 1. 记忆系统（P0 依赖）
python scripts/test_memory_manager.py

# 2. 子 Agent 独立测试
python scripts/test_collection_agent.py
python scripts/test_ranking_agent.py
python scripts/test_briefing_agent.py

# 3. 主 Agent 节点逻辑（mock LLM/DB，验证 P0/P1 契约）
python scripts/test_main_agent.py
python scripts/test_main_agent_finishing.py

# 4. 全链路集成（走完整 StateGraph，mock LLM）
python scripts/test_integration.py
```

**通过标准**：每个脚本输出末尾出现 `全部测试通过` 或 `ALL PASSED`，无 Exception 堆栈。

---

### 阶段二：P0-P4 专项验证

#### 2.1 P0 记忆接入 — 验证 planner 上下文含 memory 字段

创建临时验证脚本，运行后删除：

```powershell
python -c "
import sys; sys.path.insert(0,'.')
from agents.main_agent import _build_planner_context
state = {
    'trigger_type':'daily_briefing','goal_text':'test','react_cycle_count':0,
    'collected_items':[{'id':'1'}]*5,'ranking_detail':{'top_score':0.75},
    'brief_quality':0.8,'ranked_items':[],'observation_result':{},
    'search_supplemented':False,
}
ctx = _build_planner_context(state)
print('memory字段存在:', 'memory' in ctx)
print('recent_turns:', ctx['memory']['recent_turns'])
print('relevant_history条数:', len(ctx['memory']['relevant_history']))
print('P0验证通过' if 'memory' in ctx else 'P0验证失败')
"
```

**预期**：`memory字段存在: True`，首次运行 `relevant_history条数: 0`（不报错）。

#### 2.2 P1 Hook 化 — 验证 Hook 可替换

```powershell
python -c "
import sys; sys.path.insert(0,'.')
from utils.hooks import hooks

# 验证默认Hook已注册
print('observe.evaluate注册数:', len(hooks._hooks.get('observe.evaluate',[])))
print('reflect.check注册数:', len(hooks._hooks.get('reflect.check',[])))
print('push.decide注册数:', len(hooks._hooks.get('push.decide',[])))

# 验证自定义Hook可替换
def custom_eval(ctx):
    return {'needs_retry': False, 'issues': ['custom_check'], 'collection_ok': True}
hooks.register('observe.evaluate', custom_eval)
result = hooks.run('observe.evaluate', {'collected':[],'ranked':[],'top_score':0,'brief_quality':0})
print('自定义Hook生效:', result.get('issues') == ['custom_check'])
"
```

**预期**：三行注册数均 ≥1，`自定义Hook生效: True`。

#### 2.3 P2 执行栅栏 — 并发跳过验证

```powershell
python -c "
import threading, time
from utils.pipeline_runner import run_agent_pipeline

results = []
def run():
    results.append(run_agent_pipeline('manual'))

t1 = threading.Thread(target=run)
t2 = threading.Thread(target=run)
t1.start(); t2.start()
t1.join(); t2.join()

statuses = [r['status'] for r in results]
print('结果状态:', statuses)
print('P2验证通过' if 'skipped' in statuses else 'P2验证失败(可能管线太快)')
"
```

**预期**：一个 `completed`/`error`，一个 `skipped`。若两次都 completed（管线太快跑完），锁机制仍正确——可手动加 `time.sleep(2)` 在 `run_agent_pipeline` 入口临时验证。

#### 2.4 P4 模型回退 — 验证 Router 降级

```powershell
python -c "
import sys; sys.path.insert(0,'.')
from utils.llm_provider import DeepSeekProvider, LLMRouter

# 模拟：第一个Provider失败，第二个成功
class FailProvider:
    def chat(self, messages, temperature=0.7, max_tokens=4096, **kwargs):
        raise Exception('模拟故障')
    def chat_with_tools(self, messages, tools, temperature=0.7, max_tokens=4096, **kwargs):
        raise Exception('模拟故障')

class OkProvider:
    def chat(self, messages, temperature=0.7, max_tokens=4096, **kwargs):
        return 'fallback_ok'
    def chat_with_tools(self, messages, tools, temperature=0.7, max_tokens=4096, **kwargs):
        return {'choices':[{'message':{'content':'ok'}}]}

router = LLMRouter([FailProvider(), OkProvider()], names=['fail','ok'])
result = router.chat([{'role':'user','content':'hi'}])
print('回退结果:', result)
print('P4验证通过' if result == 'fallback_ok' else 'P4验证失败')
"
```

**预期**：`回退结果: fallback_ok`。

---

### 阶段三：真机端到端运行（连接真实 LLM/DB）

**前提**：`config/config.yaml` 中 `${DEEPSEEK_API_KEY}` 已设为有效 key。

```powershell
# 单次管线真机运行（走完整采集→排序→简报→推送链路）
python utils/pipeline_runner.py --trigger manual
```

**观察日志关键点**：
| 日志标记 | 应出现的内容 |
|---------|------------|
| `[planner] memory:` | 显示记忆检索条数（P0） |
| `[hooks]` | 无报错（P1） |
| `[pipeline] 已有管线` | 正常单次不应出现（P2 正常） |
| `[llm_router]` | 正常时不应出现（P4 主Provider正常） |
| `[update_memory] planner 决策经验已写入` | 确认记忆写入（P0） |
| `[update_memory] 执行日志写入成功` | 确认日志持久化 |

---

### 阶段四：微调要点（根据运行结果调整）

#### 4.1 记忆检索噪声过大 → 调阈值

`config/config.yaml` 中 `memory.short_term_window` 默认 15，若 planner 上下文过长：
```yaml
memory:
  short_term_window: 10    # 缩小窗口
```
对应代码 `agents/main_agent.py` 第253行 `n_recent=3, n_long_term=3`，可改为 `n_recent=2, n_long_term=2`。

#### 4.2 模型回退频繁触发 → 检查备用 Provider

查看日志中 `[llm_router]` 出现频率。若频繁，检查 `config/config.yaml` 中 `llm.fallback` 配置是否有效。不需要回退时可删掉 fallback 段，Router 只含一个 Provider 时行为等同直接调用。

#### 4.3 Hook 策略需调整 → 注册新实现

无需改 `main_agent.py`，在 `app.py` 启动时注册：

```python
# app.py 顶部添加
from utils.hooks import hooks

def my_observe_evaluate(ctx):
    # 自定义质量评估逻辑
    return {"needs_retry": False, "issues": [], "collection_ok": True}

hooks.register("observe.evaluate", my_observe_evaluate)
```

#### 4.4 管线执行太慢 → 关注 ReAct 循环次数

日志中 `ReAct 第 N 轮`，若频繁到第 3 轮，考虑收紧 `config/config.yaml`：
```yaml
agents:
  max_react_cycles: 2    # 减少循环上限
```

---

### 阶段五：持续观察（运行 1-2 周）

启动 Streamlit UI 日常使用：

```powershell
streamlit run app.py
```

**每周检查**：
1. `data/feedlens.db` → `execution_logs` 表，确认 `brief_quality_score` 趋势是否上升（记忆生效标志）
2. `data/chroma/` 长期记忆向量数量是否增长
3. UI 日志页是否有异常 `skipped` 或 `error` 状态

---

### 快速检查清单

| 步骤 | 命令 | 通过标志 |
|------|------|---------|
| 单元测试 | `python scripts/test_memory_manager.py` 等 6 个 | 全部 PASS |
| P0 验证 | 阶段二 2.1 一行命令 | `memory字段存在: True` |
| P1 验证 | 阶段二 2.2 一行命令 | 注册数≥1, 自定义生效 |
| P2 验证 | 阶段二 2.3 一行命令 | 出现 `skipped` |
| P4 验证 | 阶段二 2.4 一行命令 | `回退结果: fallback_ok` |
| 真机运行 | `python utils/pipeline_runner.py --trigger manual` | 无 Exception，日志完整 |
| UI 启动 | `streamlit run app.py` | 页面正常渲染 |

---

### 附录：其他可用测试脚本（来自 MVP 阶段）

以下命令在 MVP 开发阶段使用，部分已融入阶段一单元测试，保留供参考：

```powershell
# 数据库初始化验证
python scripts/init_db.py

# Embedding 推理速度（< 100ms/条）
python scripts/test_embedding_speed.py

# FC 工具验证
python scripts/test_fc_tools.py

# 去重阈值校准（需标注样本）
python scripts/calibrate_dedup.py --samples data/labeled_dedup_samples.json

# 推送机制
python scripts/test_push_scheduler.py

# 反馈机制
python scripts/test_feedback_agent.py

# 冷启动→偏好自适应切换
python scripts/test_cold_start_switch.py

# 日志和监控
python scripts/test_logging_monitoring.py

# 性能基准测试
python scripts/test_performance.py
```