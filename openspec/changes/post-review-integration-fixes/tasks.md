# Tasks: Post-Review Integration Fixes

## Group A: 记忆系统集成修复（CRITICAL）

- [x] **A1** `memory_manager.py` — SQLite 启用时替换 `self.semantic_store` 引用，重新初始化依赖组件
- [x] **A2** `memory_integrator.py` — `find_by_predicate` 统一为 async（`inspect.isawaitable` 兼容）
- [x] **A3** `buffer_zone.py` — 修复 `_batch_extract` 参数：`assistant_msg` 用最后一条实际回复，其余作为上下文

## Group B: Pipeline 行为修复（HIGH）

- [x] **B1** `pipeline/__init__.py` — `_update_memory_from_content` 加上 `_maybe_update_narrative` 调用
- [x] **B2** `pipeline/__init__.py` — `_update_working_memory` 填充 `mentioned_entities`（正则提取 + 停用词过滤）
- [x] **B3** `pipeline/__init__.py` — 关系阶段阈值改为从 `character.extensions` 可配置读取

## Group C: 主动消息系统修复（HIGH）

- [x] **C1** `proactive_service.py` — 维护 `_turn_counts`，`_get_relationship_stage` 方法替换硬编码
- [x] **C2** `action_selector.py` — 删除未使用的 `import time` 和 `field`

## Group D: 检索与图存储修复（HIGH）

- [x] **D1** `retrieval_router.py` — `_search_graph_activated` 返回前对边去重（`(subject, predicate, object)` 元组去重）

## Group E: 死代码与逻辑清理（HIGH）

- [x] **E1** `buffer_zone.py` — 删除未调用的 `_build_batch_prompt` 方法（30行）
- [x] **E2** `character/__init__.py` — 重写 `_get_time_context` 分支，22-24 独立描述

## Group F: 中等问题修复（MEDIUM）

- [x] **F1** `drive_system.py` — `_tick()` 改为公开 `tick()`，从 `snapshot()` 移出，proactive loop 调用
- [x] **F2** `sqlite_store.py` — 添加 `search_async` / `list_by_user_async` 方法（async + Lock）
- [x] **F3** `character/__init__.py` — 补充 10 个常见 AI 味词汇（总计 75 个）
- [x] **F4** `memory_manager.py` — `hasattr` 检查改为 `getattr(..., None) is not None`
- [x] **F5** `pipeline/__init__.py` — 关系阶段阈值可配置（与 B3 合并执行）

## 验证

- [x] **V1** 全部 10 个文件 `python -m py_compile` 语法检查通过
- [x] **V2** 功能冒烟测试：character/ANTI_AI_PHRASES(75)、WorkingMemory、NarrativeSummary、ActionSelector、Buffer Zone 结构、MemoryIntegrator 兼容性
- [x] **V3** 回归测试：86 个现有测试通过，3 个预存在失败（numpy DLL 环境问题，非本次引入）

## 修改文件清单

| 文件 | 改动类型 |
|------|---------|
| `vir_bot/core/memory/memory_manager.py` | 修改（A1, F4） |
| `vir_bot/core/memory/memory_integrator.py` | 修改（A2） |
| `vir_bot/core/memory/buffer_zone.py` | 修改（A3, E1） |
| `vir_bot/core/pipeline/__init__.py` | 修改（B1, B2, B3, F5） |
| `vir_bot/core/proactive/proactive_service.py` | 修改（C1, F1） |
| `vir_bot/core/proactive/action_selector.py` | 修改（C2） |
| `vir_bot/core/memory/retrieval_router.py` | 修改（D1） |
| `vir_bot/core/character/__init__.py` | 修改（E2, F3） |
| `vir_bot/core/proactive/drive_system.py` | 修改（F1） |
| `vir_bot/core/memory/sqlite_store.py` | 修改（F2） |
