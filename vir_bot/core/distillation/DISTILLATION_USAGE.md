蒸馏使用说明（Persona Distillation Usage）

## 1. 简介
本指南介绍如何使用项目内置的人格蒸馏子系统将聊天记录导出为结构化的角色卡（Markdown / machine-readable JSON）。蒸馏流程由以下模块组成：

- 解析器：将平台聊天导出转为 `DialogueTurn` 列表（见 `vir_bot.core.distillation.parser`）
- 分析器：基于多轮 LLM 提示抽取 `PersonaProfile`（见 `PersonaExtractor`）
- 生成器：将画像生成为 Wiki 风格 Markdown（见 `WikiGenerator`）
- 管道与 CLI：串联上述步骤并提供命令行入口（见 `DistillationPipeline` 与 `cli.py`）

关键文件/类：
- `vir-bot/vir_bot/core/distillation/pipeline.py` 中的 `DistillationPipeline`
- `vir-bot/vir_bot/core/distillation/analyzer/extractor.py` 中的 `PersonaExtractor` 与 `PersonaProfile`
- `vir-bot/vir_bot/core/distillation/generator/wiki_generator.py` 中的 `WikiGenerator`
- 命令行入口：`vir-bot/vir_bot/core/distillation/cli.py`

## 2. 先决条件
- Python 3.11+（项目使用的运行环境）
- 已安装项目依赖：`pip install -r requirements.txt`
- 配置可用的 AI 后端（OpenAI、Ollama 或本地模型），在 `config.yaml` 或通过环境变量配置：
  - OpenAI: 设置 `VIRBOT_OPENAI_KEY`（或在 `config.yaml` 中设置 `ai.openai.api_key`）
  - Ollama: 配置 `ai.ollama.base_url` 与 `ai.provider: ollama`
  - 本地模型：配置 `ai.local_model.base_url` 与 `ai.provider: local_model`

可选：如果处理特定平台导出（微信/QQ/Discord），建议先准备该平台的导出文件；目前系统内置 `GenericParser` 支持 JSON/NDJSON/TXT 等通用格式。

## 3. 输入数据格式
支持的输入格式（通过 `GenericParser`）：
- JSON array：`[{"sender":"A","content":"...","timestamp":"..."} , ...]`
- NDJSON（每行一个 JSON 对象）
- 文本文件（每行一条消息，尝试解析 `时间 发送者: 内容` 的常见模式）

如果需要，我可以为微信/QQ/Discord 实现专用解析器（需平台导出样本）。

## 4. 快速开始（命令行示例）
示例命令（在项目根目录下运行）：

- 标准蒸馏并写出 Markdown：
```vir-bot/vir_bot/core/distillation/cli.py#L1-255
python -m vir_bot.core.distillation.cli \
  --input ./data/chat_records/myfriend.json \
  --name "小雅" \
  --output ./data/wiki/characters/ \
  --evaluate
```

- 仅预览（不写文件）：
```vir-bot/vir_bot/core/distillation/cli.py#L1-255
python -m vir_bot.core.distillation.cli \
  --input ./data/chat_records/myfriend.json \
  --name "小雅" \
  --dry-run
```

- 强制使用特定解析器（例如 `wechat`，如果实现了该解析器）：
```vir-bot/vir_bot/core/distillation/cli.py#L1-255
python -m vir_bot.core.distillation.cli \
  --input ./data/chat_records/wechat_export.html \
  --name "小明" \
  --parser wechat \
  --output ./data/wiki/characters/
```

注意：
- 如果使用 OpenAI，请先在环境中设置 API Key：
```vir-bot/vir_bot/core/distillation/cli.py#L1-255
# Linux / macOS
export VIRBOT_OPENAI_KEY="sk-xxxx"

# Windows (PowerShell)
$env:VIRBOT_OPENAI_KEY = "sk-xxxx"
```

## 5. 可选参数说明（CLI）
- `--input`：输入聊天记录文件路径（必需）
- `--name`：生成的人格名称（必需），用于 Markdown 标题与文件名
- `--output`：输出目录（默认 `./data/wiki/characters/`）
- `--evaluate`：是否运行轻量评估（基于词汇重合的 heuristics）
- `--dry-run`：不写文件，仅在终端显示摘要/预览
- `--parser`：强制使用某个解析器（如 `generic` / `wechat` / `qq` / `discord`）；默认自动选择 `generic`
- `--timeout`：单次 LLM 调用超时时间（秒）

更多参数和帮助可以运行：
```vir-bot/vir_bot/core/distillation/cli.py#L1-255
python -m vir_bot.core.distillation.cli --help
```

## 6. 输出说明
蒸馏后会产出（取决于 `--dry-run`）：
- Markdown 文件：`{output_dir}/{safe_name}.md`，包含：
  - 概要（Summary）、Big Five 估计、说话风格、情绪模式、价值观、禁忌、代表对话示例、Machine-readable JSON 等（由 `WikiGenerator` 生成）
- `PersonaProfile` 的 machine-readable JSON（以 Markdown 内嵌的 JSON 或可在 pipeline 中保存）
- 评估指标（如果使用 `--evaluate`），例如 `overlap_similarity`（0.0-1.0）

路径示例：
- 输出 Markdown：`./data/wiki/characters/小雅.md`

## 7. 结果解读与合格标准
- 角色卡为 LLM 基于对话推断的结构化画像，存在不确定性与可能的幻觉（hallucination）。
- 我们的轻量评估（词汇/摘要重合）仅用于快速筛查：
  - similarity > 0.85：高度还原
  - 0.70-0.85：基本还原
  - < 0.70：建议人工复核或重蒸
- 最终通过度量仍需人工审核（尤其是涉及价值观或敏感话题部分）。

## 8. 调试与常见问题
- 无法连接 AI 后端：
  - 检查 `config.yaml` 中 `ai.provider` 与对应 `api_key` / `base_url` 是否正确。
  - 使用 `VIRBOT_OPENAI_KEY` 等环境变量来覆盖。
- 解析失败（输入文件无法被解析）：
  - 检查输入是否为有效 JSON / NDJSON / 普通文本格式；可先用 `jq` 或文本编辑器确认。
  - 提供样本给我，我可以为该平台实现专用解析器（例如微信 HTML）。
- LLM 输出无法解析为 JSON：
  - 提取器会尝试 fallback（抽取首个 JSON 块或保存原文到 `raw_notes`），但建议检查模型输出日志并依据需要调整提示词（prompt）。
- 输出看起来“不像”原人物：
  - 可在 `PersonaExtractor` 中增加更多对话上下文（提高 `max_chunk_chars`）或提供更具代表性的对话子集给 `--input`。

## 9. 进阶用法（建议）
- 向量相似度评估：将 `evaluator/similarity.py` 接入 embedding（如 `text-embedding-3-small` 或本地嵌入），对蒸馏回复与原始对话做 cosine 比较，得到更可靠的还原度量。
- LoRA / 微调：当数据量非常大（5k+ 轮）且需要最高还原度，可考虑 QLoRA 微调小模型（会涉及 GPU、训练脚本与成本估计）。
- 增量更新：如果已有 `persona.md`，可实现“增量蒸馏”，只用新会话更新画像而非重蒸。

## 10. 安全与隐私
- 蒸馏过程会把对话上下文发送到你选择的 LLM 后端，注意不要在未脱敏的情况下发送敏感/个人识别信息（PII）。
- 如需脱敏，建议在预处理阶段（或在 `ChatParser` 中）移除或替换姓名、手机号、身份证号等字段。
