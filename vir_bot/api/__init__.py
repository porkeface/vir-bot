"""FastAPI Web 控制台"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vir_bot.config import get_config
from vir_bot.utils.logger import logger


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(
        title="vir-bot 控制台",
        version=config.app.version,
        debug=config.app.debug,
    )

    # CORS
    if config.web_console.cors.allow_credentials:
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
        return {"status": "ok", "version": config.app.version}

    @app.get("/")
    async def root():
        return {"name": config.app.name, "version": config.app.version, "docs": "/docs"}

    logger.info("Web 控制台已初始化")
    return app