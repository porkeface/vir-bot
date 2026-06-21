// =============================================================================
// Section definitions — 每个配置模块的字段元数据
// =============================================================================

const SECTIONS = {
  app: {
    title: '应用设置',
    cards: [
      {
        title: '基本信息',
        desc: '应用名称、版本和运行模式',
        fields: [
          { path: 'app.name', label: '应用名称', type: 'text' },
          { path: 'app.version', label: '版本号', type: 'text' },
          { path: 'app.debug', label: '调试模式', type: 'bool', desc: '启用后输出详细日志，生产环境请关闭' },
        ]
      },
      {
        title: '日志与存储',
        fields: [
          { path: 'app.data_dir', label: '数据目录', type: 'text', desc: '所有数据文件的根目录' },
          { path: 'app.log_dir', label: '日志目录', type: 'text' },
          { path: 'app.log_level', label: '日志级别', type: 'select', options: [
            { value: 'DEBUG', label: 'DEBUG（调试，最详细）' },
            { value: 'INFO', label: 'INFO（信息，推荐）' },
            { value: 'WARNING', label: 'WARNING（警告）' },
            { value: 'ERROR', label: 'ERROR（仅错误）' },
          ]},
        ]
      }
    ]
  },

  ai: {
    title: 'AI 后端配置',
    cards: [
      {
        title: '后端选择',
        desc: '选择当前激活的 AI 推理后端',
        fields: [
          { path: 'ai.provider', label: '当前后端', type: 'select', options: [
            { value: 'openai', label: 'OpenAI 兼容 API（Qwen/DeepSeek/mimo 等）' },
            { value: 'ollama', label: 'Ollama（本地推理）' },
            { value: 'local_model', label: '本地模型（llama.cpp/vLLM）' },
            { value: 'lora', label: 'LoRA 微调模型（本地 GPU）' },
          ]},
        ]
      },
      {
        title: 'Ollama 配置',
        desc: '本地 Ollama 推理服务',
        fields: [
          { path: 'ai.ollama.base_url', label: '服务地址', type: 'text' },
          { path: 'ai.ollama.model', label: '模型名称', type: 'text', desc: '如 qwen2.5:7b、llama3:8b' },
          { path: 'ai.ollama.keep_alive', label: '模型保持时间', type: 'text', desc: '模型在内存中保持的时间，如 5m、1h' },
          { path: 'ai.ollama.timeout', label: '超时（秒）', type: 'number' },
        ]
      },
      {
        title: 'OpenAI 兼容 API',
        desc: '适用于 Qwen、DeepSeek、mimo 等 OpenAI 格式的服务',
        fields: [
          { path: 'ai.openai.base_url', label: 'API 地址', type: 'text' },
          { path: 'ai.openai.api_key', label: 'API Key', type: 'sensitive' },
          { path: 'ai.openai.model', label: '模型名称', type: 'text' },
          { path: 'ai.openai.timeout', label: '超时（秒）', type: 'number' },
          { path: 'ai.openai.max_retries', label: '最大重试次数', type: 'number' },
        ]
      },
      {
        title: '本地模型服务',
        desc: 'llama.cpp server、vLLM 等本地 OpenAI 兼容服务',
        fields: [
          { path: 'ai.local_model.base_url', label: '服务地址', type: 'text' },
          { path: 'ai.local_model.model', label: '模型名称', type: 'text' },
          { path: 'ai.local_model.timeout', label: '超时（秒）', type: 'number' },
        ]
      },
      {
        title: 'LoRA 微调模型',
        desc: '加载 LoRA 适配器进行本地推理（需要 GPU）',
        fields: [
          { path: 'ai.lora.adapter_path', label: '适配器路径', type: 'select', source: 'lora_adapters', desc: '选择已训练的 LoRA 适配器' },
          { path: 'ai.lora.base_model', label: '基座模型', type: 'text', desc: 'HuggingFace 模型 ID 或本地路径' },
          { path: 'ai.lora.load_in_4bit', label: '4-bit 量化加载', type: 'bool', desc: '节省显存，8GB 显卡推荐开启' },
          { path: 'ai.lora.max_new_tokens', label: '最大生成 Token', type: 'number' },
          { path: 'ai.lora.temperature', label: '温度', type: 'range', min: 0, max: 2, step: 0.05 },
          { path: 'ai.lora.top_p', label: 'Top P', type: 'range', min: 0, max: 1, step: 0.05 },
          { path: 'ai.lora.repetition_penalty', label: '重复惩罚', type: 'range', min: 1, max: 2, step: 0.05 },
        ]
      },
    ]
  },

  character: {
    title: '角色卡配置',
    cards: [
      {
        title: '角色卡选择',
        desc: '选择 AI 扮演的角色人格',
        fields: [
          { path: 'character.card_path', label: '角色卡文件', type: 'select', source: 'characters', desc: '从 data/characters/ 中选择' },
        ]
      },
      {
        title: '角色扩展属性',
        desc: '控制角色的表达风格和背景知识',
        fields: [
          { path: 'character.extensions.voice_style', label: '语音风格', type: 'select', options: [
            { value: '撒娇', label: '撒娇' },
            { value: '温柔', label: '温柔' },
            { value: '活泼', label: '活泼' },
            { value: '冷漠', label: '冷漠' },
            { value: '成熟', label: '成熟' },
            { value: '知性', label: '知性' },
          ]},
          { path: 'character.extensions.personality_tags', label: '性格标签', type: 'tags' },
          { path: 'character.extensions.background_knowledge', label: '背景知识目录', type: 'select', source: 'knowledge_dirs' },
        ]
      }
    ]
  },

  expression: {
    title: '表情包系统',
    cards: [
      {
        title: '表情包设置',
        desc: '发送消息时自动匹配表情包',
        fields: [
          { path: 'expression.enabled', label: '启用表情包', type: 'bool' },
        ]
      }
    ]
  },

  memory: {
    title: '记忆系统配置',
    cards: [
      {
        title: '短期记忆',
        desc: 'Ring Buffer 结构，保存最近 N 轮对话',
        fields: [
          { path: 'memory.short_term.max_turns', label: '最大轮次', type: 'number', desc: 'Ring Buffer 容量' },
          { path: 'memory.short_term.window_size', label: '窗口大小', type: 'number', desc: '送给 LLM 的上下文窗口' },
        ]
      },
      {
        title: '长期记忆',
        desc: 'ChromaDB 向量存储，支持语义检索',
        fields: [
          { path: 'memory.long_term.enabled', label: '启用长期记忆', type: 'bool' },
          { path: 'memory.long_term.vector_db', label: '向量数据库', type: 'select', options: [
            { value: 'chroma', label: 'ChromaDB（推荐）' },
          ]},
          { path: 'memory.long_term.persist_dir', label: '持久化目录', type: 'text' },
          { path: 'memory.long_term.collection_name', label: '集合名称', type: 'text' },
          { path: 'memory.long_term.top_k', label: '检索 Top K', type: 'number', desc: '返回最相似的 K 条记忆' },
          { path: 'memory.long_term.embedding_model', label: 'Embedding 模型', type: 'select', source: 'embedding_models' },
          { path: 'memory.long_term.auto_index', label: '自动索引', type: 'bool', desc: '新对话自动写入向量库' },
        ]
      },
      {
        title: 'Re-Ranker（重排序）',
        desc: 'Cross-Encoder 对检索结果重排序，提高精度',
        fields: [
          { path: 'memory.features.reranker.enabled', label: '启用', type: 'bool' },
          { path: 'memory.features.reranker.model', label: '模型', type: 'text' },
          { path: 'memory.features.reranker.top_k', label: 'Top K', type: 'number' },
        ]
      },
      {
        title: 'Composer（去重+冲突消解）',
        desc: '合并重复记忆，解决冲突信息',
        fields: [
          { path: 'memory.features.composer.enabled', label: '启用', type: 'bool' },
          { path: 'memory.features.composer.max_tokens', label: '最大 Token', type: 'number' },
        ]
      },
      {
        title: 'Quality Gate（质量门）',
        desc: 'LLM 判断记忆是否值得保存',
        fields: [
          { path: 'memory.features.quality_gate.enabled', label: '启用', type: 'bool' },
        ]
      },
      {
        title: 'Verifier（重复检测）',
        desc: '写入前检测是否与已有记忆重复',
        fields: [
          { path: 'memory.features.verifier.enabled', label: '启用', type: 'bool' },
        ]
      },
      {
        title: 'Lifecycle（生命周期管理）',
        desc: '自动衰减、合并、归档旧记忆',
        fields: [
          { path: 'memory.features.lifecycle.enabled', label: '启用', type: 'bool' },
          { path: 'memory.features.lifecycle.short_term_ttl', label: '短期记忆 TTL（天）', type: 'number' },
          { path: 'memory.features.lifecycle.long_term_archive_after', label: '长期归档阈值（天）', type: 'number' },
        ]
      },
      {
        title: 'Graph（图记忆）',
        desc: 'NetworkX 实体关系图，支持多跳推理',
        fields: [
          { path: 'memory.features.graph.enabled', label: '启用', type: 'bool' },
          { path: 'memory.features.graph.persist_path', label: '持久化路径', type: 'text' },
        ]
      },
      {
        title: 'Versioning（多版本）',
        desc: '记忆带版本链，支持时间感知检索',
        fields: [
          { path: 'memory.features.versioning.enabled', label: '启用', type: 'bool' },
          { path: 'memory.features.versioning.max_versions', label: '最大版本数', type: 'number' },
        ]
      },
    ]
  },

  platforms: {
    title: '平台接入配置',
    cards: [
      {
        title: 'QQ（OneBot v11/v12）',
        desc: '通过 OneBot 协议接入 QQ',
        fields: [
          { path: 'platforms.qq.enabled', label: '启用', type: 'bool' },
          { path: 'platforms.qq.adapter', label: '协议版本', type: 'select', options: [
            { value: 'onebot_v11', label: 'OneBot v11' },
            { value: 'onebot_v12', label: 'OneBot v12' },
          ]},
          { path: 'platforms.qq.connection.type', label: '连接方式', type: 'select', options: [
            { value: '正向WebSocket', label: '正向 WebSocket' },
            { value: '反向WebSocket', label: '反向 WebSocket' },
            { value: 'HTTP', label: 'HTTP' },
          ]},
          { path: 'platforms.qq.connection.host', label: '主机', type: 'text' },
          { path: 'platforms.qq.connection.port', label: '端口', type: 'number' },
          { path: 'platforms.qq.access_token', label: 'Access Token', type: 'sensitive' },
          { path: 'platforms.qq.rate_limit.per_user', label: '每用户限速（条/分钟）', type: 'number' },
          { path: 'platforms.qq.rate_limit.per_group', label: '每群限速（条/分钟）', type: 'number' },
          { path: 'platforms.qq.connection.suffix', label: '路径后缀', type: 'text', desc: 'WebSocket 路径后缀（如 /ws）' },
          { path: 'platforms.qq.allowed_groups', label: '允许的群号', type: 'tags', desc: '留空表示不限制' },
          { path: 'platforms.qq.allowed_users', label: '允许的用户号', type: 'tags', desc: '留空表示不限制' },
          { path: 'platforms.qq.block_list', label: '黑名单', type: 'tags' },
        ]
      },
      {
        title: 'QQ 官方机器人',
        desc: 'QQ 开放平台官方机器人',
        fields: [
          { path: 'platforms.qq_official.enabled', label: '启用', type: 'bool' },
          { path: 'platforms.qq_official.app_id', label: 'App ID', type: 'text' },
          { path: 'platforms.qq_official.app_secret', label: 'App Secret', type: 'sensitive' },
          { path: 'platforms.qq_official.callback_path', label: '回调地址', type: 'text', desc: '公网可访问的回调 URL' },
        ]
      },
      {
        title: '企业微信',
        fields: [
          { path: 'platforms.wechat.enabled', label: '启用', type: 'bool' },
          { path: 'platforms.wechat.wechat_work.corp_id', label: '企业 ID', type: 'text' },
          { path: 'platforms.wechat.wechat_work.corp_secret', label: 'Secret', type: 'sensitive' },
          { path: 'platforms.wechat.wechat_work.agent_id', label: 'Agent ID', type: 'text' },
          { path: 'platforms.wechat.wechat_work.token', label: 'Token', type: 'sensitive' },
          { path: 'platforms.wechat.wechat_work.encoding_aes_key', label: 'AES Key', type: 'sensitive' },
          { path: 'platforms.wechat.allowed_users', label: '允许的用户', type: 'tags' },
        ]
      },
      {
        title: 'Discord',
        fields: [
          { path: 'platforms.discord.enabled', label: '启用', type: 'bool' },
          { path: 'platforms.discord.bot_token', label: 'Bot Token', type: 'sensitive' },
          { path: 'platforms.discord.guilds', label: '服务器列表', type: 'object-list',
            desc: '配置允许的 Discord 服务器及频道',
            itemFields: [
              { key: 'id', label: '服务器 ID', type: 'text' },
              { key: 'name', label: '名称', type: 'text' },
              { key: 'allowed_channels', label: '允许频道', type: 'tags' },
            ]},
          { path: 'platforms.discord.rate_limit.per_channel', label: '每频道限速（条/分钟）', type: 'number' },
        ]
      },
      {
        title: 'Telegram',
        fields: [
          { path: 'platforms.telegram.enabled', label: '启用', type: 'bool' },
          { path: 'platforms.telegram.bot_token', label: 'Bot Token', type: 'sensitive' },
          { path: 'platforms.telegram.parse_mode', label: '消息格式', type: 'select', options: [
            { value: '', label: '纯文本（默认）' },
            { value: 'HTML', label: 'HTML' },
            { value: 'Markdown', label: 'Markdown' },
          ]},
          { path: 'platforms.telegram.rate_limit.per_user', label: '每用户限速', type: 'number' },
          { path: 'platforms.telegram.rate_limit.per_chat', label: '每聊天限速', type: 'number' },
          { path: 'platforms.telegram.allowed_users', label: '允许的用户', type: 'tags' },
          { path: 'platforms.telegram.allowed_chats', label: '允许的聊天', type: 'tags' },
          { path: 'platforms.telegram.block_list', label: '黑名单', type: 'tags' },
        ]
      },
    ]
  },

  pipeline: {
    title: '消息处理管道',
    cards: [
      {
        title: '上下文与过滤',
        fields: [
          { path: 'pipeline.max_context_turns', label: '最大上下文轮次', type: 'number', desc: '送给 LLM 的历史对话轮数' },
          { path: 'pipeline.filters.block_bots', label: '屏蔽机器人消息', type: 'bool' },
          { path: 'pipeline.filters.block_self', label: '屏蔽自身消息', type: 'bool' },
          { path: 'pipeline.filters.min_content_length', label: '最小内容长度', type: 'number' },
          { path: 'pipeline.filters.max_content_length', label: '最大内容长度', type: 'number' },
        ]
      },
      {
        title: '消息拆分',
        desc: '长回复自动拆成多条短消息逐条发送',
        fields: [
          { path: 'pipeline.split.enabled', label: '启用消息拆分', type: 'bool' },
          { path: 'pipeline.split.max_chunk_chars', label: '单块最大字符', type: 'number' },
          { path: 'pipeline.split.delay_min_ms', label: '最小延迟（ms）', type: 'number' },
          { path: 'pipeline.split.delay_max_ms', label: '最大延迟（ms）', type: 'number' },
        ]
      }
    ]
  },

  mcp: {
    title: 'MCP 工具协议',
    cards: [
      {
        title: '工具系统',
        fields: [
          { path: 'mcp.enabled', label: '启用 MCP 工具', type: 'bool' },
          { path: 'mcp.tool_discovery.enabled', label: '自动发现工具', type: 'bool', desc: '扫描 tools 目录自动注册' },
          { path: 'mcp.tool_discovery.auto_reload', label: '热重载', type: 'bool', desc: '工具文件变更后自动重新加载' },
          { path: 'mcp.builtin_tools', label: '内置工具', type: 'tags', desc: '启动时自动加载的工具列表' },
          { path: 'mcp.tool_discovery.directories', label: '工具目录', type: 'tags', desc: '扫描工具文件的目录列表' },
        ]
      },
      {
        title: '硬件集成（MQTT）',
        desc: '通过 MQTT 与 ESP32 等硬件设备通信',
        fields: [
          { path: 'mcp.hardware.enabled', label: '启用硬件', type: 'bool' },
          { path: 'mcp.hardware.mqtt.broker_url', label: 'MQTT Broker', type: 'text' },
          { path: 'mcp.hardware.mqtt.username', label: '用户名', type: 'text' },
          { path: 'mcp.hardware.mqtt.password', label: '密码', type: 'sensitive' },
          { path: 'mcp.hardware.mqtt.esp32_topics', label: 'ESP32 主题', type: 'tags', desc: 'MQTT 订阅主题列表' },
        ]
      }
    ]
  },

  voice: {
    title: '语音模块',
    cards: [
      {
        title: '语音总开关',
        fields: [
          { path: 'voice.enabled', label: '启用语音', type: 'bool' },
          { path: 'voice.voice_response', label: '语音回复', type: 'bool', desc: '收到语音消息时用语音回复' },
          { path: 'voice.voice_mode', label: '回复模式', type: 'select', options: [
            { value: 'replace', label: '替换（语音替代文字）' },
            { value: 'append', label: '追加（语音附加在文字后）' },
          ]},
          { path: 'voice.voice_decision', label: '语音决策', type: 'select', options: [
            { value: 'ai', label: 'AI 判断（推荐）' },
            { value: 'always', label: '总是语音回复' },
            { value: 'never', label: '从不语音回复' },
          ]},
        ]
      },
      {
        title: 'TTS（文字转语音）',
        fields: [
          { path: 'voice.tts.provider', label: 'TTS 引擎', type: 'select', options: [
            { value: 'edge', label: 'Edge TTS（微软云，免费）' },
            { value: 'cosyvoice2', label: 'CosyVoice 2（本地，支持声音克隆）' },
            { value: 'mimo', label: 'MIMO TTS（mimo 云服务）' },
          ]},
          { path: 'voice.tts.voice_id', label: 'Edge 音色', type: 'select', source: 'tts_voices',
            showWhen: { field: 'voice.tts.provider', equals: 'edge' } },
          { path: 'voice.tts.model_dir', label: 'CosyVoice 模型目录', type: 'text',
            showWhen: { field: 'voice.tts.provider', equals: 'cosyvoice2' } },
          { path: 'voice.tts.voice_sample_path', label: '声音样本路径', type: 'text', desc: '用于声音克隆的参考音频',
            showWhen: { field: 'voice.tts.provider', equals: 'cosyvoice2' } },
          { path: 'voice.tts.voice_sample_text', label: '声音样本文本', type: 'text', desc: '参考音频对应的文本',
            showWhen: { field: 'voice.tts.provider', equals: 'cosyvoice2' } },
          { path: 'voice.tts.instruct_text', label: '音色风格描述', type: 'text', desc: 'CosyVoice instruct2 模式',
            showWhen: { field: 'voice.tts.provider', equals: 'cosyvoice2' } },
          { path: 'voice.tts.mimo_voice', label: 'MIMO 音色', type: 'text', desc: '如：冰糖',
            showWhen: { field: 'voice.tts.provider', equals: 'mimo' } },
          { path: 'voice.tts.mimo_style', label: 'MIMO 风格', type: 'text',
            showWhen: { field: 'voice.tts.provider', equals: 'mimo' } },
          { path: 'voice.tts.mimo_model', label: 'MIMO 模型', type: 'text',
            showWhen: { field: 'voice.tts.provider', equals: 'mimo' } },
          { path: 'voice.tts.ffmpeg_path', label: 'FFmpeg 路径', type: 'text', desc: '音频格式转换工具路径' },
          { path: 'voice.tts.output_format', label: '输出格式', type: 'select', options: [
            { value: 'ogg', label: 'OGG（推荐）' },
            { value: 'mp3', label: 'MP3' },
            { value: 'wav', label: 'WAV' },
          ]},
          { path: 'voice.tts.speed', label: '语速', type: 'range', min: 0.5, max: 2, step: 0.1 },
        ]
      },
      {
        title: 'RVC（声音转换）',
        desc: '对 TTS 输出进行音色后处理（需要 GPU）',
        fields: [
          { path: 'voice.rvc.enabled', label: '启用 RVC', type: 'bool' },
          { path: 'voice.rvc.model_name', label: '模型名称', type: 'text' },
          { path: 'voice.rvc.model_dir', label: '模型目录', type: 'text' },
          { path: 'voice.rvc.f0up_key', label: '变调（半音）', type: 'number', desc: '正值升调，负值降调' },
          { path: 'voice.rvc.f0_method', label: '基频提取算法', type: 'select', options: [
            { value: 'rmvpe', label: 'RMVPE（推荐）' },
            { value: 'pm', label: 'PM（快速）' },
            { value: 'harvest', label: 'Harvest（高质量）' },
            { value: 'crepe', label: 'Crepe（神经网络）' },
          ]},
          { path: 'voice.rvc.index_rate', label: '索引匹配率', type: 'range', min: 0, max: 1, step: 0.05, desc: '音色特征匹配程度' },
          { path: 'voice.rvc.filter_radius', label: '滤波半径', type: 'number' },
          { path: 'voice.rvc.rms_mix_rate', label: '响度混合率', type: 'range', min: 0, max: 1, step: 0.05 },
          { path: 'voice.rvc.protect', label: '保护系数', type: 'range', min: 0, max: 0.5, step: 0.01, desc: '保护清辅音不被移除' },
          { path: 'voice.rvc.device', label: '推理设备', type: 'select', options: [
            { value: 'cuda:0', label: 'GPU (cuda:0)' },
            { value: 'cpu', label: 'CPU' },
          ]},
          { path: 'voice.rvc.half_precision', label: '半精度推理', type: 'bool', desc: '使用 FP16，节省显存' },
          { path: 'voice.rvc.sample_rate', label: '采样率', type: 'select', options: [
            { value: '48000', label: '48000 Hz' },
            { value: '44100', label: '44100 Hz' },
            { value: '24000', label: '24000 Hz' },
          ]},
        ]
      },
      {
        title: 'ASR（语音识别）',
        fields: [
          { path: 'voice.asr.provider', label: 'ASR 引擎', type: 'select', options: [
            { value: 'sensevoice', label: 'SenseVoice（本地，推荐）' },
            { value: 'openai', label: 'OpenAI Whisper API' },
            { value: 'whisper', label: 'Whisper（本地）' },
          ]},
          { path: 'voice.asr.model', label: '模型', type: 'text' },
          { path: 'voice.asr.language', label: '语言', type: 'select', options: [
            { value: 'auto', label: '自动检测' },
            { value: 'zh', label: '中文' },
            { value: 'en', label: '英文' },
            { value: 'ja', label: '日文' },
          ]},
          { path: 'voice.asr.device', label: '推理设备', type: 'select', options: [
            { value: 'cuda:0', label: 'GPU (cuda:0)' },
            { value: 'cpu', label: 'CPU' },
          ]},
          { path: 'voice.asr.base_url', label: 'API 地址', type: 'text', desc: 'Whisper API 或远程 ASR 服务地址' },
          { path: 'voice.asr.api_key', label: 'API Key', type: 'sensitive' },
        ]
      },
      {
        title: 'Wake Word（唤醒词）',
        desc: '语音唤醒功能',
        fields: [
          { path: 'voice.wake_word.provider', label: '唤醒引擎', type: 'select', options: [
            { value: 'porcupine', label: 'Porcupine（推荐）' },
            { value: 'none', label: '不使用唤醒词' },
          ]},
          { path: 'voice.wake_word.keywords', label: '唤醒词列表', type: 'tags' },
        ]
      }
    ]
  },

  visual: {
    title: '视觉感知模块',
    cards: [
      {
        title: '视觉总开关',
        fields: [
          { path: 'visual.enabled', label: '启用视觉', type: 'bool' },
        ]
      },
      {
        title: '摄像头',
        fields: [
          { path: 'visual.camera.provider', label: '摄像头类型', type: 'select', options: [
            { value: 'esp32', label: 'ESP32-CAM（网络摄像头）' },
            { value: 'usb', label: 'USB 摄像头' },
            { value: 'local', label: '本地图像' },
          ]},
          { path: 'visual.camera.esp32_url', label: 'ESP32 地址', type: 'text' },
          { path: 'visual.camera.capture_interval', label: '采集间隔（秒）', type: 'number' },
        ]
      },
      {
        title: '视觉模型',
        fields: [
          { path: 'visual.vision.provider', label: '视觉引擎', type: 'select', options: [
            { value: 'openai', label: 'OpenAI 兼容 API' },
            { value: 'local', label: '本地模型' },
          ]},
          { path: 'visual.vision.model', label: '模型名称', type: 'text' },
          { path: 'visual.vision.base_url', label: 'API 地址', type: 'text' },
          { path: 'visual.vision.max_image_size', label: '最大图片尺寸', type: 'number' },
        ]
      }
    ]
  },

  web_console: {
    title: 'Web 控制台',
    cards: [
      {
        title: '服务设置',
        fields: [
          { path: 'web_console.enabled', label: '启用控制台', type: 'bool' },
          { path: 'web_console.host', label: '监听地址', type: 'select', options: [
            { value: '0.0.0.0', label: '0.0.0.0（允许外部访问）' },
            { value: '127.0.0.1', label: '127.0.0.1（仅本机）' },
          ]},
          { path: 'web_console.port', label: '端口', type: 'number' },
        ]
      },
      {
        title: '认证',
        fields: [
          { path: 'web_console.auth.enabled', label: '启用 Token 认证', type: 'bool' },
          { path: 'web_console.auth.token', label: 'Token', type: 'text', desc: 'Web 控制台访问 Token，修改后需重启服务生效' },
        ]
      },
      {
        title: 'CORS 跨域',
        fields: [
          { path: 'web_console.cors.allow_origins', label: '允许的来源', type: 'tags' },
          { path: 'web_console.cors.allow_credentials', label: '允许凭据', type: 'bool' },
        ]
      }
    ]
  },

  security: {
    title: '安全与隐私',
    cards: [
      {
        title: '安全设置',
        fields: [
          { path: 'security.log_sanitization', label: '日志脱敏', type: 'bool', desc: '自动隐藏日志中的敏感信息' },
          { path: 'security.encrypt_local_data', label: '加密本地数据', type: 'bool' },
          { path: 'security.max_tokens', label: '最大 Token 数', type: 'number', desc: '单次请求的最大 Token 限制' },
          { path: 'security.http_timeout', label: 'HTTP 超时（秒）', type: 'number' },
        ]
      }
    ]
  },

  proactive: {
    title: '主动消息（牵挂驱动）',
    cards: [
      {
        title: '主动消息开关',
        desc: 'AI 主动关心用户，而非被动等待',
        fields: [
          { path: 'proactive.enabled', label: '启用主动消息', type: 'bool' },
          { path: 'proactive.check_interval_seconds', label: '检查间隔（秒）', type: 'number' },
          { path: 'proactive.min_cooldown_seconds', label: '最小冷却（秒）', type: 'number', desc: '两条主动消息之间的最短间隔' },
          { path: 'proactive.max_daily_messages', label: '每日上限', type: 'number' },
        ]
      },
      {
        title: '关怀评估',
        desc: '决定何时发送主动消息',
        fields: [
          { path: 'proactive.concern.threshold', label: '触发阈值', type: 'range', min: 0, max: 1, step: 0.05, desc: '关怀分数超过此值时触发' },
          { path: 'proactive.concern.llm_evaluate', label: 'LLM 评估', type: 'bool', desc: '用 LLM 判断是否需要关心（关闭则纯规则）' },
        ]
      },
      {
        title: '表达配置',
        fields: [
          { path: 'proactive.expression.max_context_memories', label: '上下文记忆数', type: 'number' },
          { path: 'proactive.expression.max_tokens', label: '最大 Token', type: 'number' },
        ]
      },
      {
        title: '发送目标',
        desc: '主动消息发送到哪个平台的哪个用户',
        fields: [
          { path: 'proactive.targets.telegram.chat_id', label: 'Telegram Chat ID', type: 'text' },
          { path: 'proactive.targets.qq.user_id', label: 'QQ 用户号', type: 'text' },
          { path: 'proactive.targets.qq.group_id', label: 'QQ 群号', type: 'text' },
          { path: 'proactive.targets.discord.channel_id', label: 'Discord 频道 ID', type: 'text' },
          { path: 'proactive.targets.wechat.touser', label: '企微用户 ID', type: 'text' },
        ]
      }
    ]
  },
};
