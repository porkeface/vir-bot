# vir-bot 文档目录

## 文档导航

| 文档 | 用途 | 状态 |
|------|------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | **核心文档**：8层架构设计 + Phase 1-8 实施计划 + 进度追踪 | ✅ 权威参考 |
| [memory-system-usage.md](./memory-system-usage.md) | 使用指南：配置说明、API文档、测试验证、常见问题 | ✅ 使用文档 |
| [proactive/主动消息系统实现框架.md](./proactive/主动消息系统实现框架.md) | 主动消息系统设计（牵挂驱动型） | ✅ 主动消息 |
| [distillation/DISTILLATION_PLAN.md](./distillation/DISTILLATION_PLAN.md) | 角色蒸馏方案：从聊天记录生成角色人设卡 | 🟡 可选功能 |

## 归档文档（docs/archive/）

以下文档已被更新的版本替代，保留用于历史参考：

| 原文档 | 被替代 by |
|--------|-----------|
| [AI_Robot_Project.md](./archive/AI_Robot_Project.md) | 项目已转向纯软件架构 |
| [牵挂驱动型AI伴侣主动消息方案.md](./archive/牵挂驱动型AI伴侣主动消息方案.md) | proactive/主动消息系统实现框架.md |
| [IMPROVEMENT_PLAN.md](./archive/IMPROVEMENT_PLAN.md) | ARCHITECTURE.md |
| [MEMORY_ARCHITECTURE.md](./archive/MEMORY_ARCHITECTURE.md) | ARCHITECTURE.md |
| [vir-bot 记忆系统渐进式改造计划.md](./archive/) | ARCHITECTURE.md |
| [vir-bot 记忆系统渐进式改造进度.md](./archive/) | ARCHITECTURE.md |

## 文档关系图

```
docs/
├── README.md                          ← 你在这里
├── ARCHITECTURE.md                   ← 合并文档（架构+计划+进度）
│   ├── 8层架构设计（Mermaid图、数据流、各层详解）
│   ├── Phase 1-8 实施计划（任务清单、验证方法）
│   └── 进度追踪（已完成状态、测试覆盖、评测基线）
├── memory-system-usage.md             ← 精简文档（配置、API、FAQ）
├── proactive/                        ← 主动消息系统
│   └── 主动消息系统实现框架.md
├── distillation/                     ← 角色蒸馏（可选）
│   └── DISTILLATION_PLAN.md
└── archive/                          ← 历史文档
    ├── AI_Robot_Project.md
    ├── 牵挂驱动型AI伴侣主动消息方案.md
    ├── IMPROVEMENT_PLAN.md
    ├── MEMORY_ARCHITECTURE.md
    ├── vir-bot 记忆系统渐进式改造计划.md
    └── vir-bot 记忆系统渐进式改造进度.md
```

## 快速查找

- **了解架构** → 读 `ARCHITECTURE.md`（第一部分：架构总览 + 8层详解）
- **开始实施** → 读 `ARCHITECTURE.md`（第二部分：Phase 1-8 实施计划）
- **查看进度** → 读 `ARCHITECTURE.md`（第三部分：进度追踪）
- **配置使用** → 读 `memory-system-usage.md`
- **主动消息** → 读 `proactive/主动消息系统实现框架.md`
- **角色蒸馏** → 读 `distillation/DISTILLATION_PLAN.md`
