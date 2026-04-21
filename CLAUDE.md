# vir-bot

## 项目概述
个性化AI机器人（数字分身）纯软件版 — 基于聊天记录蒸馏的AI人格 + 多平台接入 + RAG记忆 + MCP工具。

## 技术栈
- Python 3.11+ / FastAPI / asyncio
- ChromaDB 向量数据库
- AI后端可切换：Ollama / OpenAI兼容API / 本地模型

## 目录结构
- `vir_bot/core/` — 核心抽象层（AI Provider、记忆、角色卡、MCP、Pipeline）
- `vir-bot/platforms/` — 平台适配器（QQ/微信/Discord）
- `vir-bot/modules/` — 可插拔模块（Voice/Visual/Hardware）
- `vir-bot/api/` — Web 控制台
- `data/` — 运行时数据（角色卡、记忆、日志）
- `config.yaml` — 全局配置

## 开发
```bash
# 安装依赖
pip install -r requirements.txt

# 启动（纯软件模式，无需硬件）
python -m vir-bot.main

# Web 控制台
open http://localhost:7860
```

## 架构原则
- 核心层（core/）不依赖平台或硬件
- AI Provider 用策略模式，支持切换后端
- 消息统一走 Pipeline 编排
- 硬件模块（modules/）可插拔，后续接入

## 状态
Phase 1: 项目基础结构 & 核心抽象层实现中