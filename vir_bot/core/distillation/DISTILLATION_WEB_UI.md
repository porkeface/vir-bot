概述
- 目标：为 `Persona Distillation` 提供一个可视化、交互友好的 Web 界面，方便用户上传聊天记录、配置蒸馏参数、监控蒸馏进度、查看/下载生成的角色卡（Markdown/JSON）、并可复核/编辑生成结果。
- 益处：降低使用门槛、便于非开发者操作、支持并发任务管理与可视化评估、显著加速迭代与人工复核流程。

可行性（简短结论）
- 可行。项目已包含 FastAPI 的 Web API 框架和若干路由（例如 `character` 路由），因此把蒸馏功能作为新的 API 路由并接入前端界面是自然且低成本的扩展。
- 实现方式可从最小可行产品（MVP）逐步演进到完整 SPA + 异步任务队列 + 实时 WebSocket 推送的成熟产品线。

参考已有 API 实现（示例）
- 项目已有的角色卡管理路由可作为实现新路由的参考：
```vir-bot/vir_bot/api/routers/character.py#L1-400
"""角色卡管理 API"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from vir_bot.core.character import CharacterCard, load_character_card
from vir_bot.config import get_config

router = APIRouter()
...
```

可选实现方案对比

1) 方案 A — 最小可行 UI（MVP）
- 技术：FastAPI 后端 + 简单服务器端渲染或纯静态 HTML+Vanilla JS。
- 功能：文件上传、参数表单、启动任务（后台）、轮询查询/下载结果、展示 Markdown 预览。
- 优点：实现最快（1-2 天）；易于调试；可直接集成到现有 FastAPI 服务。
- 缺点：用户体验一般；并发/长任务的进度反馈较弱（可用轮询实现）。

2) 方案 B — 实时交互式界面（推荐 MVP 升级）
- 技术：FastAPI 后端 + WebSocket（或 Server-Sent Events），前端使用轻量框架（Vue/React）或使用现成的 UI（例如 Gradio/Streamlit）。
- 功能：上传、参数配置、启动任务、实时日志/分段进度、完成后展示 Markdown、直接编辑并保存角色卡、评估分数可视化。
- 优点：用户体验好，实时反馈，适合生产使用。
- 缺点：实现复杂度中等（2-4 天）。

3) 方案 C — 后台任务队列 + SPA（企业级）
- 技术：FastAPI + Celery / RQ / Dramatiq（任务队列） + Redis + React/Vue + WebSocket/Redis PubSub。
- 功能：任务管理（重试、并发限制、队列优先级）、历史任务/多用户支持、长时间任务可靠执行、审计日志。
- 优点：可靠、扩展性强，适合大量并发或多用户场景。
- 缺点：运维成本增加（Redis/任务队列）；实现周期更长（3-7 天）。

推荐方案
- 若要尽快落地：先做 A 的 MVP，然后用 B 的方式升级（增加 WebSocket 实时日志）。
- 若期望多用户并发且生产就绪：直接做 C，但需要部署 Redis/Worker。

后端设计（API 设计样例）
- 新增路由：`/api/distillation`
- 功能及接口（示例）：
  - `POST /api/distillation/upload` — 上传聊天记录文件（返回 `file_id`）
  - `POST /api/distillation/start` — 启动蒸馏任务（body: { file_id, name, parser, options... }） → 返回 `job_id`
  - `GET  /api/distillation/status/{job_id}` — 查询任务状态（queued/running/done/failed）与基础进度
  - `GET  /api/distillation/result/{job_id}` — 获取生成的 metadata（summary、metrics、markdown_preview、markdown_url）
  - `GET  /api/distillation/download/{job_id}` — 下载 Markdown / JSON 文件
  - `WS   /api/distillation/ws/{job_id}` — 实时推送日志与进度（可选）

示例服务端接口实现（伪代码示例）
- 示例代码块（示例新路由文件，不会实际写入项目；若需要我可把这个实现成真实路由）：
```/dev/null/distillation_api_example.py#L1-120
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, WebSocket
from pydantic import BaseModel

router = APIRouter(prefix="/api/distillation")

class StartRequest(BaseModel):
    file_id: str
    name: str
    parser: str | None = None
    evaluate: bool = False

@router.post("/upload")
async def upload_chat(file: UploadFile = File(...)):
    # 保存到 data/chat_records/{generated_id}.json
    return {"file_id": generated_id}

@router.post("/start")
async def start_distillation(req: StartRequest, background_tasks: BackgroundTasks):
    # 创建 job entry（job_id）并在 background_tasks 启动 pipeline.run(...)
    return {"job_id": job_id}

@router.get("/status/{job_id}")
async def status(job_id: str):
    return {"job_id": job_id, "state": "running", "progress": 0.42}

@router.get("/result/{job_id}")
async def result(job_id: str):
    # 返回 markdown preview, metrics, download urls
    return {"job_id": job_id, "markdown_preview": "...", "metrics": {...}}
```

后台任务与进度报告（实现选项）
- Option 1 — FastAPI `BackgroundTasks` / `asyncio.create_task`（适合 MVP）
  - 优点：零运维，直接在主进程内运行，容易实现。
  - 缺点：长期/重任务会阻塞或在进程重启时丢失进度；不适合水平扩展。
- Option 2 — 使用 Redis + Celery / RQ（推荐用于生产）
  - 优点：任务可靠、可重试、可观察；可扩展。
  - 缺点：需要运维 Redis + worker。
- 进度反馈实现：
  - 最简单：轮询 `GET /status/{job_id}` 返回 progress int。
  - 更佳：在后端通过 WebSocket 推送日志与进度（例如：每轮 LLM 完成时推送一条消息）。前端订阅 `WS /api/distillation/ws/{job_id}`。

前端交互与 UX（草案）
- 页面/区域
  1. 上传区：拖拽或选择文件（支持 JSON/NDJSON/TXT），显示文件大小 / 检测格式。
  2. 参数区：`name`、`parser`（auto/generic/wechat/qq/discord）、`evaluate`、`max_chars`、`timeout` 等。
  3. 启动按钮：`Start Distillation`
  4. 任务列表：显示当前用户的任务（job_id、name、status、created_at、actions）
  5. 任务详情（点击某一任务）：顶部显示进度条 + 状态，下方是实时日志（stream）、最终 Markdown 预览（可编辑）和下载按钮（Markdown/JSON）
  6. 结果复核：按钮 `Edit & Save` -> 把修改后的角色卡保存到 `data/wiki/characters/{name}.md`（由 `WikiGenerator.save` 实现）
- 交互细节
  - 当任务 running 时，前端通过 WebSocket 实时追加日志；状态切换时显示对应操作（如下载可用）。
  - 支持把生成的 Machine-readable JSON 供高级用户下载或导入进角色管理（`/api/character/upload`）。

安全、隐私与权限
- 身份与权限控制：
  - 若是单机/个人使用，内网访问或 token 认证即可（`WebConsoleAuthConfig` 已在 `config.py` 中）。
  - 多用户场景：必须集成用户认证（JWT / OAuth / Session）并对 API 加权限检测，隔离用户的 `data/chat_records/` 与 `jobs`。
- 敏感数据处理：
  - 在上传前提供“脱敏/模糊化”选项（可在客户端或后端实现），去除手机号/身份证/邮箱等 PII。
  - 在 UI 上明确告知用户：上传的数据会发送到配置的 LLM 后端（若使用云服务则会离开本地）。
- 速率限制与资源控制：
  - 对单个用户并发任务数进行限制（默认 1-2），避免滥用 LLM 调用配额。
  - 提供队列优先策略及管理员接口取消任务。

存储与路径约定（建议）
- 上传文件保存： `data/chat_records/{file_id}.json`
- 任务元数据： `data/distillation/jobs/{job_id}.json`（记录 status、progress、timestamps、metrics、artifact paths）
- 输出 Markdown： `data/wiki/characters/{safe_name}.md`
- 日志/临时文件： `data/logs/distillation/{job_id}.log`

评估与可视化（UI）
- 显示 `overlap_similarity`（词汇相似度）以及可选的向量相似度（如果你接入 embedding）。
- 可视化：雷达图展示 Big Five、条形图展示 similarity、示例对话卡片列出 5-10 个代表片段。

实现步骤与时间估算（建议迭代）
- MVP（API + 简单 HTML 前端 + BackgroundTasks + 轮询）：
  - 任务：新增 `api/routers/distillation.py` 路由、保存上传文件、调用 `DistillationPipeline.run`（background task）、实现 `status/result` endpoint、简单 HTML 页面（上传 + 参数 + 轮询展示）。
  - 估时：1-2 天（单人）。
- 升级（MVP -> 实时）：
  - 任务：为后端添加 WebSocket 推送（或 SSE），前端订阅并展示实时日志、进度，Markdown 预览页面改为可编辑并保存。
  - 估时：1-2 天。
- 生产化（任务队列 + SPA + 权限）：
  - 任务：引入 Celery/Redis、实现任务持久化、实现用户认证、实现任务管理界面、实现历史任务检索与审计、增强评估（embeddings）。
  - 估时：3-7 天（取决于现有 infra）。

示例 UI 文案 / 交互流程
1. 用户上传文件或选择已有记录文件
2. 用户填写 `Persona Name` 与可选参数，点击 `Start Distillation`
3. 后端返回 `job_id`，前端打开任务详情页并建立 WebSocket 连接
4. 后端在每轮 LLM 完成后推送状态更新（e.g. "Round 1 done", progress=0.25）
5. 任务完成后，前端显示最终 Markdown，用户可直接编辑并保存，或下载 Markdown/JSON，同时可以触发重新蒸馏（调整参数）

部署注意
- 若使用外部 LLM（OpenAI），请配置好 API Key 的安全存储（环境变量或 Secret Manager），并在 UI 上提示用户数据离开本地的风险。
- 若部署在公网，必须启用 HTTPS、认证并对上传文件大小做限制（例如 10MB）。

示例演示（MVP 命令）
- 启动后端（已有项目入口）：
```vir-bot/vir_bot/main.py#L1-400
# 启动项目（依据 README）
python -m vir_bot.main
```
- 打开 Web 控制台（如项目 README 中所示）：
  - http://localhost:7860 （若你的 Web 控制台已集成路由，可把新页面挂载到同一服务）

我可以帮你做什么（下一步）
- 帮你在项目中实现 MVP：我会新增 `vir_bot/api/routers/distillation.py`、前端静态页面（`vir_bot/api/static/distillation.html`）并把路由注册到现有 FastAPI 应用中；或使用现有 Web 控制台（如果你有前端框架偏好也可以用 React/Vue）。
- 如果你愿意让我实现，请确认：
  1. 希望的方案：MVP（轮询） / 实时（WebSocket） / 生产（Celery）
  2. 是否允许新增后台依赖（Redis/Celery）？
  3. 是否提供一份示例聊天记录（项目内相对路径），我可以用它做一次 demo 并把生成的 Markdown 返回给你。
  4. 是否希望在 UI 中集成身份验证（简单 token 或已有控制台的 auth）？

补充链接（参考）
- 已有 API 示例：`vir-bot/vir_bot/api/routers/character.py`（可借鉴上传/保存逻辑）
- Distillation CLI / pipeline：`vir-bot/vir_bot/core/distillation/cli.py`（用于参考任务调用流程）
