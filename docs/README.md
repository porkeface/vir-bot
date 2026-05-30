# vir-bot 文档目录

## 文档导航

| 文档 | 用途 | 状态 |
|------|------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | **核心文档**：8层架构设计 + Phase 1-8 实施计划 + 进度追踪 | ✅ 权威参考 |
| [memory-system-usage.md](./memory-system-usage.md) | 使用指南：配置说明、API文档、知识图谱、质量门控、FAQ | ✅ 使用文档 |
| [proactive/主动消息系统重构计划.md](./proactive/主动消息系统重构计划.md) | 主动消息系统 v4 设计与实现（内驱力+灵感触发） | ✅ 已实现 |
| [proactive/主动消息系统实现框架.md](./proactive/主动消息系统实现框架.md) | 主动消息系统 v1 框架（已废弃，保留参考） | ⚠️ 已废弃 |
| [distillation/DISTILLATION_PLAN.md](./distillation/DISTILLATION_PLAN.md) | 角色蒸馏方案：从聊天记录生成角色人设卡 | ✅ 已实现 |
| [distillation/蒸馏角色卡使用指南.md](./distillation/蒸馏角色卡使用指南.md) | 蒸馏结果使用指南 | ✅ 使用文档 |
| [voice_sticker_plan.md](./voice_sticker_plan.md) | 语音+表情+贴图模块设计方案 | 📋 设计文档 |
| [performance_optimization_plan.md](./performance_optimization_plan.md) | 性能优化方案 | 📋 设计文档 |
| [角色卡微调报告.md](./角色卡微调报告.md) | 角色卡微调实验报告 | 📋 实验报告 |
| [2026-05-10-工作报告.md](./2026-05-10-工作报告.md) | 2026-05-10 工作报告（QQ接入+角色更名） | 📋 工作记录 |

## 归档文档（docs/archive/）

以下文档已被更新的版本替代，保留用于历史参考：

| 原文档 | 被替代 by |
|--------|-----------|
| [AI_Robot_Project.md](./archive/AI_Robot_Project.md) | 项目已转向纯软件架构 |
| [牵挂驱动型AI伴侣主动消息方案.md](./archive/牵挂驱动型AI伴侣主动消息方案.md) | proactive/主动消息系统重构计划.md |
| [IMPROVEMENT_PLAN.md](./archive/IMPROVEMENT_PLAN.md) | ARCHITECTURE.md |
| [MEMORY_ARCHITECTURE.md](./archive/MEMORY_ARCHITECTURE.md) | ARCHITECTURE.md |
| [vir-bot 记忆系统渐进式改造计划.md](./archive/) | ARCHITECTURE.md |
| [vir-bot 记忆系统渐进式改造进度.md](./archive/) | ARCHITECTURE.md |

## 文档关系图

```
docs/
├── README.md                          ← 你在这里
├── ARCHITECTURE.md                    ← 合并文档（架构+计划+进度）
│   ├── 8层架构设计（Mermaid图、数据流、各层详解）
│   ├── Phase 1-8 实施计划（任务清单、验证方法）
│   └── 进度追踪（已完成状态、测试覆盖、评测基线）
├── memory-system-usage.md             ← 使用文档（配置、API、知识图谱、FAQ）
├── proactive/                         ← 主动消息系统
│   ├── 主动消息系统重构计划.md         ← v4 设计（已实现）
│   └── 主动消息系统实现框架.md         ← v1 框架（已废弃）
├── distillation/                      ← 角色蒸馏
│   ├── DISTILLATION_PLAN.md           ← 蒸馏方案
│   ├── DISTILLATION_REFORM_PLAN.md    ← 蒸馏改进方案
│   └── 蒸馏角色卡使用指南.md          ← 使用指南
├── voice_sticker_plan.md              ← 语音+表情设计
├── performance_optimization_plan.md   ← 性能优化
├── 角色卡微调报告.md                  ← 微调实验
├── 2026-05-10-工作报告.md             ← 工作记录
└── archive/                           ← 历史文档
    ├── AI_Robot_Project.md
    ├── 牵挂驱动型AI伴侣主动消息方案.md
    ├── IMPROVEMENT_PLAN.md
    └── MEMORY_ARCHITECTURE.md
```

## 快速查找

- **了解架构** → 读 `ARCHITECTURE.md`（架构总览 + 8层详解）
- **配置使用** → 读 `memory-system-usage.md`（配置、API、知识图谱、FAQ）
- **主动消息** → 读 `proactive/主动消息系统重构计划.md`（v4 内驱力+灵感触发）
- **角色蒸馏** → 读 `distillation/DISTILLATION_PLAN.md`
- **语音/表情** → 读 `voice_sticker_plan.md`
- **查看进度** → 读 `ARCHITECTURE.md`（进度追踪部分）
