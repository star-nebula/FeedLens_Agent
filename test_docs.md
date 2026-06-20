- 验证 SQLite 表已创建：python scripts/init\_db.py

  输出：
  ```
  [init_db] Creating schema at data/feedlens.db ...
  [init_db] Schema created (11 tables + indexes).
  [init_db] Default user seeded (id=1, goal_text empty).
  [init_db] Verified: 12 tables — briefing_items, briefs, deduped_items, execution_logs, feedback, item_relations, raw_items, run_logs, sources, sqlite_sequence, user_preferences, users
  [init_db] Done.
  ```
- 验证 Embedding模式推理速度（< 100ms/条）：python scripts/test\_embedding\_speed.py
- FeedLens FC 工具验证测试：python scripts/test\_fc\_tools.py
- 测试 collection\_agent：python scripts/test\_collection\_agent.py
- 测试 ranking\_agent：python scripts/test\_ranking\_agent.py
- 测试 main\_agent：python scripts/test\_main\_agent.py
- 去重阈值校准：python scripts/calibrate\_dedup.py --samples data/labeled\_dedup\_samples.json
- 测试 briefing\_agent：python scripts/test\_briefing\_agent.py
- main\_agent 的完整测试：python scripts/test\_main\_agent\_finishing.py
- 测试推送机制：python scripts/test\_push\_scheduler.py
- 测试 feedback\_agent：python scripts/test\_feedback\_agent.py
- 测试 记忆管理：python scripts/test\_memory\_manager.py
- 测试 冷启动→偏好自适应切换：python scripts/test\_cold\_start\_switch.py
- 运行前端：streamlit run app.py
- 集成测试：python scripts/test\_integration.py
- 测试日志和监控：python scripts/test\_logging\_monitoring.py
- 性能基准测试：python scripts/test\_performance.py

