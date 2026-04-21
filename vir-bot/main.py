"""vir-bot 主入口"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from vir_bot.config import load_config, get_config
from vir_bot.utils.logger import setup_logger, logger


# =============================================================================
# 组件容器（通过 FastAPI 依赖注入访问）
# =============================================================================


class AppState:
    """应用全局状态"""

    def __init__(self):
        self.config: Any = None
        self.ai_provider: Any = None
        self.memory_manager: Any = None
        self.character_card: Any = None
        self.mcp_registry: Any = None
        self.pipeline: Any = None
        self.adapters: dict = {}
        self.hardware: Any = None
        self.visual: Any = None


app_state = AppState()


# =============================================================================
# 核心初始化
# =============================================================================


async def _init_core(config):
    from vir_bot.core.ai_provider import AIProviderFactory
    from vir_bot.core.memory import ShortTermMemory, LongTermMemory, MemoryManager
    from vir_bot.core.character import load_character_card
    from vir_bot.core.mcp import ToolRegistry, register_builtin_tools
    from vir_bot.core.pipeline import MessagePipeline

    logger.info("初始化核心组件...")

    # AI Provider
    ai_provider = AIProviderFactory.create(config.ai)
    healthy = await ai_provider.health_check()
    logger.info(f"AI Provider: {config.ai.provider}/{ai_provider.model_name} (健康: {healthy})")

    # 记忆系统
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
    memory_manager = MemoryManager(
        short_term=short_term,
        long_term=long_term,
        window_size=config.memory.short_term.window_size,
    )
    logger.info("记忆系统就绪")

    # 角色卡
    character_card = load_character_card(config.character.card_path)
    logger.info(f"角色卡: {character_card.name}")

    # MCP 工具
    mcp_registry = ToolRegistry()
    if config.mcp.enabled:
        register_builtin_tools(mcp_registry, memory_manager, character_card)
        logger.info(f"MCP 工具: {mcp_registry.count()} 个已注册")

    # Pipeline
    pipeline = MessagePipeline(
        ai_provider=ai_provider,
        memory_manager=memory_manager,
        character_card=character_card,
        mcp_registry=mcp_registry,
        config=config.pipeline,
    )
    logger.info("消息管道就绪")

    return {
        "ai_provider": ai_provider,
        "memory_manager": memory_manager,
        "character_card": character_card,
        "mcp_registry": mcp_registry,
        "pipeline": pipeline,
    }


async def _init_platforms(config, pipeline):
    from vir_bot.platforms.qq_adapter import QQAdapter
    from vir_bot.platforms.discord_adapter import DiscordAdapter

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

    config = get_config()
    logger.info(f"=== vir-bot {config.app.version} 启动 ===")

    # 核心组件
    core = await _init_core(config)
    app_state.config = config
    app_state.ai_provider = core["ai_provider"]
    app_state.memory_manager = core["memory_manager"]
    app_state.character_card = core["character_card"]
    app_state.mcp_registry = core["mcp_registry"]
    app_state.pipeline = core["pipeline"]

    # 平台适配器
    app_state.adapters = await _init_platforms(config, core["pipeline"])
    for name, adapter in app_state.adapters.items():
        try:
            await adapter.start()
        except Exception as e:
            logger.error(f"平台 {name} 启动失败: {e}")

    # 可选模块
    if config.mcp.hardware.enabled:
        app_state.hardware = await _init_hardware(config)
    if config.visual.enabled:
        app_state.visual = await _init_visual(config)

    logger.info(f"=== vir-bot 启动完成 ===")

    yield

    # 清理
    logger.info("=== vir-bot 关闭中 ===")
    for name, adapter in app_state.adapters.items():
        await adapter.stop()
    if app_state.hardware:
        await app_state.hardware.shutdown()
    if app_state.visual:
        await app_state.visual.stop()
    await app_state.ai_provider.close()


# =============================================================================
# 依赖注入（供路由使用）
# =============================================================================


def get_app_state() -> AppState:
    return app_state


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

    # CORS
    if config.web_console.cors.allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.web_console.cors.allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # 注册路由
    from vir_bot.api.routers import character, memory, config_router, tools, logs, platforms, chat

    app.include_router(character.router, prefix="/api/character", tags=["角色卡"])
    app.include_router(memory.router, prefix="/api/memory", tags=["记忆"])
    app.include_router(config_router.router, prefix="/api/config", tags=["配置"])
    app.include_router(tools.router, prefix="/api/tools", tags=["工具"])
    app.include_router(logs.router, prefix="/api/logs", tags=["日志"])
    app.include_router(platforms.router, prefix="/api/platforms", tags=["平台"])
    app.include_router(chat.router, prefix="/api/chat", tags=["对话"])

    # 健康检查
    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": config.app.version,
            "ai_healthy": await app_state.ai_provider.health_check() if app_state.ai_provider else False,
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

    app = create_app()

    host = config.web_console.host
    port = config.web_console.port
    logger.info(f"Web 控制台: http://{host}:{port}")
    logger.info(f"API 文档:   http://{host}:{port}/docs")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()