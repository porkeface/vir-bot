"""配置加载：config.yaml → 类型安全的 dataclass"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# =============================================================================
# 小模型（对应 config.yaml 各 section）
# =============================================================================


class AppConfig(BaseModel):
    name: str = "vir-bot"
    version: str = "0.1.0"
    debug: bool = False
    data_dir: str = "./data"
    log_dir: str = "./data/logs"
    log_level: str = "INFO"


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:7b"
    keep_alive: str = "5m"
    timeout: int = 120


class OpenAIConfig(BaseModel):
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = ""
    model: str = "qwen-plus"
    timeout: int = 60
    max_retries: int = 3


class LocalModelConfig(BaseModel):
    base_url: str = "http://localhost:8080"
    model: str = "local-model"
    timeout: int = 180


class AIConfig(BaseModel):
    provider: str = "openai"
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    local_model: LocalModelConfig = Field(default_factory=LocalModelConfig)


class CharacterExtensions(BaseModel):
    voice_style: str = "撒娇"
    personality_tags: list[str] = Field(default_factory=list)
    background_knowledge: str = "./data/knowledge/"


class CharacterConfig(BaseModel):
    card_path: str = "./data/characters/default.json"
    extensions: CharacterExtensions = Field(default_factory=CharacterExtensions)


class ShortTermMemoryConfig(BaseModel):
    max_turns: int = 20
    window_size: int = 10


class LongTermMemoryConfig(BaseModel):
    enabled: bool = True
    vector_db: str = "chroma"
    persist_dir: str = "./data/memory/chroma_db"
    collection_name: str = "persona_memory"
    top_k: int = 5
    embedding_model: str = "all-MiniLM-L6-v2"
    auto_index: bool = True


class MemoryConfig(BaseModel):
    short_term: ShortTermMemoryConfig = Field(default_factory=ShortTermMemoryConfig)
    long_term: LongTermMemoryConfig = Field(default_factory=LongTermMemoryConfig)


class QQConnectionConfig(BaseModel):
    type: str = "正向WebSocket"
    host: str = "0.0.0.0"
    port: int = 8080


class QQRateLimitConfig(BaseModel):
    per_user: int = 20
    per_group: int = 60


class QQConfig(BaseModel):
    enabled: bool = False
    adapter: str = "onebot_v11"
    connection: QQConnectionConfig = Field(default_factory=QQConnectionConfig)
    access_token: str = ""
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)
    block_list: list[str] = Field(default_factory=list)
    rate_limit: QQRateLimitConfig = Field(default_factory=QQRateLimitConfig)


class WeChatWorkConfig(BaseModel):
    corp_id: str = ""
    corp_secret: str = ""
    agent_id: str = ""
    token: str = ""
    encoding_aes_key: str = ""


class WeChatConfig(BaseModel):
    enabled: bool = False
    adapter: str = "wechat_work"
    wechat_work: WeChatWorkConfig = Field(default_factory=WeChatWorkConfig)
    allowed_users: list[str] = Field(default_factory=list)


class DiscordRateLimitConfig(BaseModel):
    per_channel: int = 10


class DiscordGuildConfig(BaseModel):
    id: str = ""
    name: str = ""
    allowed_channels: list[str] = Field(default_factory=list)


class DiscordConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    guilds: list[DiscordGuildConfig] = Field(default_factory=list)
    rate_limit: DiscordRateLimitConfig = Field(default_factory=DiscordRateLimitConfig)


class PlatformsConfig(BaseModel):
    qq: QQConfig = Field(default_factory=QQConfig)
    wechat: WeChatConfig = Field(default_factory=WeChatConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)


class PipelineFiltersConfig(BaseModel):
    block_bots: bool = True
    block_self: bool = True
    min_content_length: int = 1
    max_content_length: int = 4096


class PipelineConfig(BaseModel):
    max_context_turns: int = 20
    handlers: list[str] = Field(default_factory=lambda: ["text"])
    filters: PipelineFiltersConfig = Field(default_factory=PipelineFiltersConfig)


class MCPToolDiscoveryConfig(BaseModel):
    enabled: bool = True
    directories: list[str] = Field(default_factory=lambda: ["./vir-bot/core/mcp/tools/"])
    auto_reload: bool = True


class MCPHardwareMQTTConfig(BaseModel):
    broker_url: str = "mqtt://localhost:1883"
    username: str = ""
    password: str = ""
    esp32_topics: list[str] = Field(default_factory=lambda: ["vir-bot/esp32/#"])


class MCPHardwareConfig(BaseModel):
    enabled: bool = False
    mqtt: MCPHardwareMQTTConfig = Field(default_factory=MCPHardwareMQTTConfig)


class MCPConfig(BaseModel):
    enabled: bool = True
    builtin_tools: list[str] = Field(
        default_factory=lambda: ["memory_query", "memory_forget", "character_update", "calculator"]
    )
    tool_discovery: MCPToolDiscoveryConfig = Field(default_factory=MCPToolDiscoveryConfig)
    hardware: MCPHardwareConfig = Field(default_factory=MCPHardwareConfig)


class VoiceTTSConfig(BaseModel):
    provider: str = "edge"
    voice_id: str = "zh-CN-XiaoxiaoNeural"
    speed: float = 1.0


class VoiceASRConfig(BaseModel):
    provider: str = "whisper"
    model: str = "base"
    language: str = "zh"


class VoiceWakeWordConfig(BaseModel):
    provider: str = "porcupine"
    keywords: list[str] = Field(default_factory=lambda: ["hey-vir"])


class VoiceConfig(BaseModel):
    enabled: bool = False
    tts: VoiceTTSConfig = Field(default_factory=VoiceTTSConfig)
    asr: VoiceASRConfig = Field(default_factory=VoiceASRConfig)
    wake_word: VoiceWakeWordConfig = Field(default_factory=VoiceWakeWordConfig)


class VisualCameraConfig(BaseModel):
    provider: str = "esp32"
    esp32_url: str = "http://esp32-cam.local/capture"
    capture_interval: int = 10


class VisualVisionConfig(BaseModel):
    provider: str = "openai"
    model: str = "qwen-vl-plus"
    base_url: str = "http://localhost:8080"
    max_image_size: int = 1024


class VisualConfig(BaseModel):
    enabled: bool = False
    camera: VisualCameraConfig = Field(default_factory=VisualCameraConfig)
    vision: VisualVisionConfig = Field(default_factory=VisualVisionConfig)


class WebConsoleAuthConfig(BaseModel):
    enabled: bool = True
    token: str = "vir-bot-console-token"


class WebConsoleCORSConfig(BaseModel):
    allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:7860"])
    allow_credentials: bool = True


class WebConsoleConfig(BaseModel):
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 7860
    auth: WebConsoleAuthConfig = Field(default_factory=WebConsoleAuthConfig)
    cors: WebConsoleCORSConfig = Field(default_factory=WebConsoleCORSConfig)


class ProactiveConcernConfig(BaseModel):
    threshold: float = 0.7
    llm_evaluate: bool = True


class ProactiveExpressionConfig(BaseModel):
    max_context_memories: int = 5
    max_tokens: int = 200


class ProactiveTargetsQQConfig(BaseModel):
    user_id: str = ""
    group_id: str = ""


class ProactiveTargetsDiscordConfig(BaseModel):
    channel_id: str = ""


class ProactiveTargetsWeChatConfig(BaseModel):
    touser: str = ""


class ProactiveConfig(BaseModel):
    enabled: bool = False
    check_interval_seconds: int = 60
    min_cooldown_seconds: int = 60
    max_daily_messages: int = 20
    concern: ProactiveConcernConfig = Field(default_factory=ProactiveConcernConfig)
    expression: ProactiveExpressionConfig = Field(default_factory=ProactiveExpressionConfig)
    targets: dict = Field(default_factory=dict)


class SecurityConfig(BaseModel):
    log_sanitization: bool = True
    encrypt_local_data: bool = False
    max_tokens: int = 4096
    http_timeout: int = 30


# =============================================================================
# 完整配置（根对象）
# =============================================================================


class Config(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    character: CharacterConfig = Field(default_factory=CharacterConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    platforms: PlatformsConfig = Field(default_factory=PlatformsConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    visual: VisualConfig = Field(default_factory=VisualConfig)
    web_console: WebConsoleConfig = Field(default_factory=WebConsoleConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)


# =============================================================================
# 配置加载器（单例）
# =============================================================================

_CONFIG: Config | None = None
_CONFIG_PATH: Path | None = None


def load_config(path: str | Path | None = None) -> Config:
    """从 YAML 文件加载配置（支持环境变量覆盖）"""
    global _CONFIG, _CONFIG_PATH

    if path is None:
        path = os.environ.get("VIRBOT_CONFIG", "config.yaml")

    config_path = Path(path).resolve()
    _CONFIG_PATH = config_path

    # 读取 YAML
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    # 环境变量覆盖（VIRBOT_AI_API_KEY, VIRBOT_DISCORD_TOKEN 等）
    raw = _apply_env_overrides(raw)

    _CONFIG = Config.model_validate(raw)
    return _CONFIG


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """将环境变量覆盖到配置字典"""
    if api_key := os.environ.get("VIRBOT_OPENAI_KEY"):
        raw.setdefault("ai", {})
        raw["ai"].setdefault("openai", {})
        raw["ai"]["openai"]["api_key"] = api_key

    if token := os.environ.get("VIRBOT_DISCORD_TOKEN"):
        raw.setdefault("platforms", {})
        raw["platforms"].setdefault("discord", {})
        raw["platforms"]["discord"]["bot_token"] = token

    if access_token := os.environ.get("VIRBOT_QQ_TOKEN"):
        raw.setdefault("platforms", {})
        raw["platforms"].setdefault("qq", {})
        raw["platforms"]["qq"]["access_token"] = access_token

    if console_token := os.environ.get("VIRBOT_CONSOLE_TOKEN"):
        raw.setdefault("web_console", {})
        raw["web_console"].setdefault("auth", {})
        raw["web_console"]["auth"]["token"] = console_token

    return raw


def get_config() -> Config:
    """获取已加载的配置（必须先调用 load_config）"""
    if _CONFIG is None:
        return load_config()
    return _CONFIG
