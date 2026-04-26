# vir-bot Phase 2 基线分数

## 评测时间
2026-04-26

## 环境
- AI Provider: Mock 模式（验证流程）
- 数据集大小: 各 8 条 (MVP)
- 评测系统: Phase 2 已实现

## Mock 模式结果（预期行为）

| 指标 | 分数 | 正确/总数 | 说明 |
|------|------|-----------|------|
| preference_recall | 0% | 0/8 | Mock AI 不返回关键词 |
| episodic_recall | 0% | 0/8 | Mock AI 不返回关键词 |
| knowledge_update | 0% | 0/8 | Mock AI 不返回关键词 |
| temporal_reasoning | 0% | 0/8 | Mock AI 不返回关键词 |
| abstention_accuracy | 0% | 0/8 | Mock AI 不返回拒答关键词 |
| **overall** | **0%** | - | Mock 模式预期结果 |

## 真实 AI 模式（待运行）

运行命令：
```bash
cd "D:/code Project/vir-bot"
python -m tests.eval.benchmark --report tests/eval/baseline_real.json
```

## 备注
- Mock 模式用于验证评测流程是否跑通
- 真实 AI 模式才能反映实际系统能力
- 后续 Phase 3+ 的改进应该使分数提升
- 数据集后续扩充到 20+ 条后重新评测
