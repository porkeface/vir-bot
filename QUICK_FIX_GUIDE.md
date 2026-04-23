# vir-bot 记忆系统快速修复指南

## 🚨 问题症状

你遇到以下问题？

- ❌ 记忆在每次启动时丢失
- ❌ AI 说"我什么都记不得"
- ❌ 即使有记忆，AI 也不从记忆回答，反而乱说话
- ❌ 用户说"我喜欢吃火锅"后，问"你还记得我喜欢吃什么吗"，AI 仍然编造

**这就是记忆系统失效了！** 按以下步骤快速修复。

---

## ⚡ 5分钟快速修复

### 第一步：确认已应用代码修补

检查以下三个文件是否包含修复内容：

#### ✅ 检查 1：`vir_bot/core/memory/semantic_store.py`

查找第 45-48 行，应该**不存在**这几行：
```python
# ❌ 错误（旧代码）
removed = self.cleanup_invalid_records()
if removed:
    logger.info(f"SemanticMemoryStore cleaned invalid records...")
```

应该改为：
```python
# ✅ 正确（新代码）
logger.info(f"SemanticMemoryStore initialized: path={self.persist_path}")
```

**如果还是旧代码？**
→ 文件未更新，需要手动删除那几行。

#### ✅ 检查 2：`vir_bot/core/memory/memory_manager.py`

搜索 `_infer_semantic_namespaces` 方法，应该存在。

```bash
grep -n "_infer_semantic_namespaces" vir_bot/core/memory/memory_manager.py
```

应该有输出。如果没有，说明文件未更新。

#### ✅ 检查 3：`vir_bot/core/memory/memory_writer.py`

搜索 "例1 - 清晰偏好"，应该在提示词中。

```bash
grep -n "例1" vir_bot/core/memory/memory_writer.py
```

应该有输出。

### 第二步：重启应用

```bash
# 如果正在运行，先停止
# Ctrl+C

# 重新启动
python -m vir_bot.main
```

### 第三步：验证修复

在 Web 控制台测试：

```
用户输入: 我最喜欢吃火锅
（AI 回复，记忆已记录）

然后输入: 你还记得我喜欢吃什么吗？
期望输出: 应该说"火锅"，而不是"我不确定"或随意编造
```

**成功！** ✅ 如果 AI 正确回答，说明修复有效。

---

## 🔍 诊断脚本

如果不确定修复是否生效，运行诊断：

```bash
python debug_memory.py
```

输出示例：
```
📊 记忆统计
  - 总记录数: 3
  - 活跃记录: 3  ← 数字应该增长，不应该减少
  - 失效记录: 0

✓ 未发现明显问题
```

**解读**：
- 如果 `活跃记录` 在增长 → ✅ 记忆系统正常
- 如果 `活跃记录` 在减少或停留 → ❌ 可能还有问题

---

## 🧪 完整测试

要全面验证修复效果，运行：

```bash
python test_memory_fix.py
```

这会：
1. 添加多条测试记忆
2. 测试精确和宽泛检索
3. 验证系统提示词生成
4. 输出最终统计

预期输出中应该包含：
```
✓ 查询'我喜欢吃什么'找到 1 条记录
✓ 查询'我叫什么名字'找到 1 条记录
✓ 查询'我每天做什么'找到 1 条记录
```

---

## ❓ 常见问题

### Q1：修复后记忆仍然在丢失

**可能原因1**：代码未完全更新
```bash
# 查看 semantic_store.py 的 __init__ 方法
grep -A 5 "def __init__" vir_bot/core/memory/semantic_store.py | head -20
```

应该看到 `self._load()` 之后直接是 `logger.info`，没有 `cleanup_invalid_records()` 调用。

**可能原因2**：其他地方调用了清理
```bash
grep -r "cleanup_invalid_records" vir_bot/
```

只应该在 `semantic_store.py` 中定义，不应该在其他地方被调用。

### Q2：AI 仍然不从记忆回答

**检查项1**：系统提示词是否包含记忆内容

运行 `test_prompt_output.py` 查看实际生成的提示词：
```bash
python test_prompt_output.py 2>&1 | tail -50
```

应该看到类似：
```
【用户偏好】
- 喜欢：火锅

【记忆使用规则】
- 当用户提及这些记忆相关的话题时...必须优先从【用户偏好】等记忆中回答
```

如果这部分缺失 → 说明 `build_enhanced_system_prompt()` 方法未正确更新。

**检查项2**：user_id 是否正确传递

在 Web 聊天时，查看后端日志是否看到：
```
user_id: web_user
```

如果 user_id 为空或错误 → 记忆检索会失败。

### Q3："什么"等疑问词仍被写入记忆

**检查**：运行诊断看是否还有活跃的纯疑问词记忆

```bash
python debug_memory.py
```

如果看到：
```
✓ [profile.preference] likes: 什么
```

说明旧数据还在。需要手动清理或重置记忆库。

**手动清理方法**：
```bash
# 删除旧的记忆文件
rm data/memory/semantic_memory.json

# 重启应用，会生成新的空记忆库
python -m vir_bot.main
```

### Q4：修复后其他功能出问题

**最常见**：导入错误或语法错误

```bash
python -c "from vir_bot.core.memory import MemoryManager; print('OK')"
```

如果有错误，会显示哪个文件有问题。

---

## 📋 修复完成清单

- [ ] 代码已更新（三个文件都检查过）
- [ ] 应用已重启
- [ ] `python debug_memory.py` 运行正常
- [ ] 可以在 Web 控制台成功对话
- [ ] 测试"记忆检索"功能：问过的问题 AI 能回答
- [ ] 测试"记忆新增"功能：新的用户陈述被正确保存

所有项都打钩？✅ **恭喜，记忆系统已修复！**

---

## 🆘 还是不行？

如果按照上面的步骤还是不行，收集诊断信息：

```bash
# 运行这三个命令的输出
python debug_memory.py > diag1.log 2>&1
python test_memory_fix.py > diag2.log 2>&1
python test_prompt_output.py > diag3.log 2>&1

# 查看日志
tail -50 diag1.log
tail -50 diag2.log
tail -50 diag3.log
```

然后检查：
1. 是否有 Python 错误信息
2. 记忆统计数字是否合理
3. 检索结果是否为空

---

## 📚 更多信息

- **详细文档**：见 `MEMORY_SYSTEM_FIX.md`
- **架构设计**：见 `MEMORY_ARCHITECTURE.md`
- **改进路线**：见 `MEMORY_IMPROVEMENT_PLAN.md`

---

**记忆系统恢复快速指南完成！** 💡

如果成功了，可以继续正常使用。记忆会持久化在 `data/memory/semantic_memory.json`。

下次 AI 会记得你的偏好、习惯和身份信息！🎉