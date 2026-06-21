# Post-Review Integration Fixes

## 背景

上一轮实现了 11 项改进（P0-P3），经过两轮审计修复了 CRITICAL 和 HIGH 问题。但本次全面复查发现：**代码语法正确，但集成不完整**——多个新功能写了代码却没有真正接入，或接入方式有误。

## 问题清单

### 🔴 CRITICAL（3 个）

| # | 文件 | 问题 |
|---|------|------|
| 1 | `memory_manager.py` | SQLite 存储初始化了但从未替代 JSON 存储，`self._sqlite_store` 是空壳 |
| 2 | `memory_integrator.py` | 调用同步 `find_by_predicate`，但 SQLite 版是 async，切换存储后会报错 |
| 3 | `buffer_zone.py` | `_batch_extract` 把整个多轮对话塞进 `user_msg`，`assistant_msg` 是废数据 |

### 🟠 HIGH（7 个）

| # | 文件 | 问题 |
|---|------|------|
| 4 | `pipeline/__init__.py` | 流式输出路径 `_update_memory_from_content` 不更新叙事摘要 |
| 5 | `proactive_service.py` | 关系阶段硬编码为 `"acquaintance"`，ActionSelector 永远拿到固定值 |
| 6 | `action_selector.py` | 未使用的 `import time` |
| 7 | `pipeline/__init__.py` | 工作记忆不追踪 `mentioned_entities`，字段是死的 |
| 8 | `retrieval_router.py` | 图搜索从多个节点收集边时不去重 |
| 9 | `buffer_zone.py` | `_build_batch_prompt` 方法定义了但从未调用（死代码） |
| 10 | `character/__init__.py` | 时间段 22-24 点的逻辑被 else 覆盖，描述与 0-6 重复 |

### 🟡 MEDIUM（5 个）

| # | 文件 | 问题 |
|---|------|------|
| 11 | `drive_system.py` | `snapshot()` 有副作用（调用 `_decay_all`） |
| 12 | `sqlite_store.py` | `search` 和 `list_by_user` 没有并发保护 |
| 13 | `character/__init__.py` | 缺少常见 AI 味词汇 |
| 14 | `memory_manager.py` | `hasattr` 检查私有方法 `_is_quality_gate_enabled` |
| 15 | `pipeline/__init__.py` | 关系阶段阈值硬编码（10/30/80），不可配置 |

## 改动范围

涉及 **7 个现有文件** + **0 个新文件**，无架构变更，无新模块，无新依赖。

## 预期结果

- SQLite 存储真正可选替代 JSON
- Buffer Zone 正确传递对话给 MemoryWriter
- 流式/非流式路径行为一致
- 所有新功能（工作记忆、叙事摘要、关系阶段、行为选择器）正确集成
- 消除死代码和类型不兼容
