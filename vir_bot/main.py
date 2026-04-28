"""vir-bot 主入口"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vir_bot.config import get_config, load_config
from vir_bot.utils.logger import logger, setup_logger

# =============================================================================
# 全局状态（放在 sys.modules 里确保跨模块实例一致）
# =============================================================================


class _AppState:
    def __init__(self):
        self.config: Any = None
        self.ai_provider: Any = None
        self.memory_manager: Any = None
        self.character_card: Any = None
        self.mcp_registry: Any = None
        self.pipeline: Any = None
        self.adapters: dict = {}
        self.proactive_service: Any = None
        self.hardware: Any = None
        self.visual: Any = None


def _get_app_state() -> _AppState:
    """从 __main__ 模块获取 app_state（-m 模式兼容性）"""
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "app_state"):
        return main_mod.app_state
    # 兜底：直接返回模块级实例
    return app_state


# 模块级实例（chat.py 等导入 vir_bot.main 时会拿到这个）
app_state = _AppState()


# =============================================================================
# 核心初始化
# =============================================================================


async def _init_core(config):
    from vir_bot.core.ai_provider import AIProviderFactory
    from vir_bot.core.character import load_character_card
    from vir_bot.core.mcp import ToolRegistry, register_builtin_tools
    from vir_bot.core.memory import (
        LongTermMemory,
        MemoryManager,
        MemoryUpdater,
        MemoryWriter,
        SemanticMemoryStore,
        ShortTermMemory,
    )
    from vir_bot.core.pipeline import MessagePipeline

    logger.info("=" * 60)
    logger.info("初始化核心组件...")
    logger.info("=" * 60)

    ai_provider = AIProviderFactory.create(config.ai)
    try:
        healthy = await ai_provider.health_check()
        logger.info(f"AI Provider: {config.ai.provider}/{ai_provider.model_name} (健康: {healthy})")

        character_card = load_character_card(config.character.card_path)
        logger.info(f"角色卡已加载: {character_card.name}")

        short_term = ShortTermMemory(max_turns=config.memory.short_term.max_turns)
        long_term = (
            LongTermMemory(
                persist_dir=config.memory.long_term.persist_dir,
                collection_name=config.memory.long_term.collection_name,
                embedding_model=config.memory.long_term.embedding_model,
                top_k=config.memory.long_term.top_k,
            )
            if config.memory.long_term.enabled
            else None
        )
        semantic_store = SemanticMemoryStore(
            persist_path=str(config.app.data_dir) + "/memory/semantic_memory.json"
        )
        memory_writer = MemoryWriter(ai_provider)
        memory_updater = MemoryUpdater(semantic_store)
        memory_manager = MemoryManager(
            short_term=short_term,
            long_term=long_term,
            semantic_store=semantic_store,
            memory_writer=memory_writer,
            memory_updater=memory_updater,
            window_size=config.memory.short_term.window_size,
            wiki_dir=str(config.app.data_dir) + "/wiki",
            ai_provider=ai_provider,
            features=getattr(config.memory, 'features', {}),
        )

        await memory_manager.set_character(character_card.name)

        logger.info("记忆系统就绪")
        logger.info(f"Wiki 系统已初始化，当前角色: {character_card.name}")

        mcp_registry = ToolRegistry()
        if config.mcp.enabled:
            register_builtin_tools(mcp_registry, memory_manager, character_card)
            logger.info(f"MCP 工具: {mcp_registry.count()} 个已注册")

        pipeline = MessagePipeline(
            ai_provider=ai_provider,
            memory_manager=memory_manager,
            character_card=character_card,
            mcp_registry=mcp_registry,
            config=config.pipeline,
        )
        logger.info("消息管道就绪")
    except Exception:
        await ai_provider.close()
        raise

    return {
        "ai_provider": ai_provider,
        "memory_manager": memory_manager,
        "character_card": character_card,
        "mcp_registry": mcp_registry,
        "pipeline": pipeline,
    }


async def _init_platforms(config, pipeline):
    from vir_bot.platforms.discord_adapter import DiscordAdapter
    from vir_bot.platforms.qq_adapter import QQAdapter

    adapters = {}
    if config.platforms.qq.enabled:
        try:
            adapters["qq"] = QQAdapter(pipeline, config.platforms.qq)
            logger.info("QQ 适配器已创建")
        except Exception as e:
            logger.error(f"QQ 适配器失败: {e}")

    if config.platforms.discord.enabled:
        if not config.platforms.discord.bot_token:
            logger.warning("Discord bot_token 未配置")
        else:
            try:
                adapters["discord"] = DiscordAdapter(pipeline, config.platforms.discord)
                logger.info("Discord 适配器已创建")
            except Exception as e:
                logger.error(f"Discord 适配器失败: {e}")

    return adapters


async def _init_hardware(config):
    from vir_bot.modules.hardware import create_hardware_module

    hw = create_hardware_module(config.mcp)
    if hw:
        await hw.initialize()
        logger.info("硬件控制模块已启动")
    return hw


async def _init_visual(config):
    from vir_bot.modules.visual import create_visual_module

    vis = create_visual_module(config.visual)
    if vis:
        await vis.start_auto_capture(config.visual.camera.capture_interval)
        logger.info("视觉感知模块已启动")
    return vis


# =============================================================================
# FastAPI 生命周期
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_state

    # 从 sys.modules["__main__"] 取 app_state（-m 模式兼容）
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "app_state"):
        app_state = main_mod.app_state

    config = get_config()
    logger.info(f"=== vir-bot {config.app.version} 启动 ===")

    core = await _init_core(config)
    app_state.config = config
    app_state.ai_provider = core["ai_provider"]
    app_state.memory_manager = core["memory_manager"]
    await app_state.memory_manager.start_background_tasks()
    app_state.character_card = core["character_card"]
    app_state.mcp_registry = core["mcp_registry"]
    app_state.pipeline = core["pipeline"]

    app_state.adapters = await _init_platforms(config, core["pipeline"])
    for name, adapter in app_state.adapters.items():
        try:
            await adapter.start()
        except Exception as e:
            logger.error(f"平台 {name} 启动失败: {e}")

    if config.mcp.hardware.enabled:
        app_state.hardware = await _init_hardware(config)
    if config.visual.enabled:
        app_state.visual = await _init_visual(config)

    # 初始化主动消息服务
    print("DEBUG: 开始初始化主动消息服务...", flush=True)
    logger.info("初始化主动消息服务...")
    try:
        from vir_bot.core.proactive.proactive_service import ProactiveService
        logger.info(f"ProactiveService 导入成功, app_state.config 存在: {hasattr(app_state, 'config')}")
        print(f"DEBUG: ProactiveService 类导入成功", flush=True)
    except Exception as e:
        print(f"DEBUG: ProactiveService 导入失败: {e}", flush=True)
        logger.error(f"ProactiveService 导入失败: {e}")
        raise
    app_state.proactive_service = ProactiveService(
        ai_provider=app_state.ai_provider,
        memory_manager=app_state.memory_manager,
        character_card=app_state.character_card,
        config=app_state.config,
        platform_adapters=app_state.adapters,
    )
    logger.info(f"app_state.proactive_service 已设置: {hasattr(app_state, 'proactive_service')}")
    if app_state.proactive_service._enabled:
        await app_state.proactive_service.start()
        logger.info("主动消息服务已启动")
    else:
        logger.info("主动消息服务未启用")

    logger.info(f"=== vir-bot 启动完成 ===")

    yield

    # 关闭主动消息服务
    if hasattr(app_state, 'proactive_service') and app_state.proactive_service and app_state.proactive_service._enabled:
        try:
            await app_state.proactive_service.stop()
            logger.info("主动消息服务已停止")
        except Exception as e:
            logger.error(f"停止主动消息服务失败: {e}")

    logger.info("=== vir-bot 关闭中 ===")
    for name, adapter in app_state.adapters.items():
        await adapter.stop()
    if app_state.hardware:
        await app_state.hardware.shutdown()
    if app_state.visual:
        await app_state.visual.stop()
    await app_state.ai_provider.close()


# =============================================================================
# 创建 FastAPI 应用
# =============================================================================


def create_app() -> FastAPI:
    config = get_config()

    app = FastAPI(
        title="vir-bot 控制台",
        version=config.app.version,
        debug=config.app.debug,
        lifespan=lifespan,
    )

    if config.web_console.cors.allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.web_console.cors.allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    from vir_bot.api.routers import (
        character,
        chat,
        config_router,
        distillation,
        logs,
        memory,
        platforms,
        proactive,
        tools,
    )

    app.include_router(character.router, prefix="/api/character", tags=["角色卡"])
    app.include_router(memory.router, prefix="/api/memory", tags=["记忆"])
    app.include_router(config_router.router, prefix="/api/config", tags=["配置"])
    app.include_router(tools.router, prefix="/api/tools", tags=["工具"])
    app.include_router(logs.router, prefix="/api/logs", tags=["日志"])
    app.include_router(platforms.router, prefix="/api/platforms", tags=["平台"])
    app.include_router(distillation.router, prefix="/api/distillation", tags=["蒸馏"])
    app.include_router(proactive.router, prefix="/api/proactive", tags=["主动消息"])
    # Serve the distillation static UI (if present)
    # StaticFiles is imported here to avoid changing top-level imports; this will
    # mount the directory vir_bot/api/static/distillation at the route /distillation.
    try:
        from pathlib import Path

        from fastapi.staticfiles import StaticFiles

        static_dir = Path(__file__).parent / "api" / "static" / "distillation"
        if static_dir.exists():
            app.mount(
                "/distillation",
                StaticFiles(directory=str(static_dir), html=True),
                name="distillation",
            )
    except Exception:
        # If StaticFiles or the directory is not available, continue without mounting.
        pass
    app.include_router(chat.router, prefix="/api/chat", tags=["对话"])

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": config.app.version,
            "ai_healthy": await app_state.ai_provider.health_check()
            if app_state.ai_provider
            else False,
        }

    @app.get("/")
    async def root():
        return {
            "name": config.app.name,
            "version": config.app.version,
            "docs": "/docs",
            "platforms": list(app_state.adapters.keys()),
        }

    return app


# =============================================================================
# 入口
# =============================================================================


def run():
    config = load_config()
    setup_logger(level=config.app.log_level, log_dir=config.app.log_dir)

    import os

    os.makedirs(f"{config.app.data_dir}/cache", exist_ok=True)

    # 在 __main__ 模块注册 app_state（关键！）
    sys.modules["__main__"].app_state = app_state

    app = create_app()

    host = config.web_console.host
    port = config.web_console.port
    logger.info(f"Web 控制台: http://{host}:{port}")
    logger.info(f"API 文档: http://{host}:{port}/docs")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
