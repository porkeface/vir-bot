"""Web Console Bearer Token 认证中间件。"""

from __future__ import annotations

import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


# 豁免路径（无需认证）
_EXEMPT_PATHS: set[str] = {
    "/health",
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# 豁免路径前缀（静态文件等）
_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/distillation",
    "/config",
    "/docs/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """全局 Bearer Token 认证中间件。

    - 从 Authorization: Bearer <token> 头提取 token
    - 与 config.web_console.auth.token 做时序安全比较
    - 豁免健康检查、Swagger UI、静态文件等路径
    """

    async def dispatch(self, request: Request, call_next):
        from vir_bot.config import get_config

        config = get_config()

        # 未启用认证时直接放行
        if not config.web_console.auth.enabled:
            return await call_next(request)

        path = request.url.path

        # 豁免路径
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        for prefix in _EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # QQ 回调豁免（有独立签名验证）
        if path == "/api/platforms/qq/callback" and request.method == "POST":
            return await call_next(request)

        # 提取 Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Bearer token"},
            )

        token = auth_header[7:]  # 去掉 "Bearer " 前缀

        # 时序安全比较
        expected = config.web_console.auth.token
        if not hmac.compare_digest(token, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token"},
            )

        return await call_next(request)
