# FeedLens 项目工作记忆

## 项目定位
- 主动式信息聚合 Agent 系统，核心差异化：自主规划 + 多Agent协调 + 定时执行 + 个性化筛选
- MVP 文档：docs/FeedLens_MVP_Design_Document.md (v3.0)

## 关键决策
- 主Agent planner节点是P0核心，采用ReAct循环自主编排子Agent（附录决策P1已修正为"P0 planner自主编排"）
- 反馈回路是「个性化筛选」的实现路径，异步执行不阻塞主流程（threading.Thread独立线程）
- 六层架构：感知→大脑→规划→工具→记忆→展示（展示层=交付层：推送承载）
- 展示层(Streamlit)实际承载推送交付功能，非纯UI
- APScheduler：BackgroundScheduler独立后台线程（非Streamlit主线程），config.yaml读取cron触发时间（MVP不从数据库读取）
- 排序公式：w₃·(preference + feedback_bias)，feedback_bias叠加到preference内部而非独立因子
- **similarity vs preference 因子区分**：similarity用goal_embedding（structured_goal.topics拼接后实时生成），preference用user_preference_vector（v_like/v_dislike合成+EMA更新）。冷启动时两者接近，有反馈后分化。goal_embedding不存ChromaDB，运行时计算。
- importance归一化：(score-1)/4线性归一化（1→0, 5→1）
- 反馈权重表中数值为feedback_bias（临时补偿，EMA更新后归零），非preference永久调整
- reflect命名：两个层级——简报Agent reflect(FC)=质量评分，主Agent reflect(StateGraph节点)=综合审查。实现时应分别命名briefing_reflect/coordinator_reflect
- observe_results节点输出observation_result:dict（条件路由摘要），条件边路由到planner或reflect
- planner短期记忆：State存15轮，planner仅取最近3轮摘要
- reflect回退条件：quality<0.7 AND retry<2才回退planner，否则继续推送
- MVP单用户但数据模型预留user_id FK，user_id固定为1
- reflect质量不达标时回退planner（重新规划），而非回退invoke_sub_agent
- 反馈子Agent统一命名为FeedbackAgent，中文描述用"反馈子Agent"
- brief_quality：JSON Schema quality = State brief_quality，同一数据两种形态
- briefs表：score存独立列quality_score，quality_detail仅存3个子维度
- §3.1=设计原则与范围界定（含不做清单+planner场景映射表），§3.2=P0核心(3.2.1-3.2.6)，§3.3=P1增强(3.3.1-3.3.2)，§3.4=P2，§6.3=Streamlit页面路由
- §3.2.5=推送模块，§3.2.6=反馈模块（FeedbackAgent属P0，完整实现feedback_bias+EMA+ChromaDB）
- feedback_bias唯一权威定义在§3.2.3排序公式说明，其他位置均引用该处
- reflect命名统一：简报Agent内=brief_quality_check(FC)，主Agent=coordinator_reflect(StateGraph节点)
- goal_embedding在understand_intent阶段生成，缓存于SQLite users表，排序Agent通过State读取
- P1简化为可裁剪增强（无"P1核心"分类）；§3.3.2偏好深化用P0已有/P1新增对比表
- 附录决策编号(P/T/I)与§3优先级(P0/P1/P2)是两套独立编号系统
- sub Agent参数命名统一：structured_goal（非goal/user_profile）
- 附录决策索引I1引用更新为§3.2.6(P0实现)+§3.3.2(P1深化)
- planner安全约束"同一子Agent≤2次"理由含Collection补充搜索+Ranking调参重排两个场景
- deduped_items数据生命周期：30天，随briefs引用期保留；raw_items清理级联仅删原始文本

## 文档规范
- MVP文档风格：决策可追溯（标注来源），实现细节写到配置参数级
- 不在MVP文档中写具体Python类/方法，只写节点接口和约束
- 决策规则引用已有章节，不重复写
- §4新增调度集成小节（§4.3），原§4.3→§4.4，原§4.4→§4.5，原§4.5→§4.6
- "cron job"术语统一为"CronTrigger"
- authority_score=预留扩展因子，P0不参与排序；relation_type=P2扩展，MVP仅用duplicate_of和merged_into
- source_diversity_bonus：P1阶段直接加到final_score（final_score += bonus），P0值为0
- goal_embedding生成方式：topics关键词空格分隔拼接为单句文本后embedding（MVP），P1可改为加权平均
- config.yaml结构：§8.6.2标注"可调"的参数均通过config.yaml读取（7段：scheduler/agents/ranking/feedback/weights/breaking_news/data）
- push_immediate触发逻辑：LLM自主判断，breaking_news_score/freshness参数提供阈值引导
- planner最大子Agent调用：理论上限9次（3×3），实际约6次（同一子Agent≤2次约束）
- briefing_result=完整结构(含briefing+brief_quality)，briefing=提取的简报JSON内容（供push/渲染）
