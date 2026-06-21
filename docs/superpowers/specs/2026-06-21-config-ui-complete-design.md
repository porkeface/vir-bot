---
comet_change: config-ui-complete
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-21-config-ui-complete
status: final
---

# Design Doc: 配置管理 UI 补齐

## 1. 概述

补齐 `vir_bot/api/static/config/index.html` 中缺失的 38 个配置字段，新增 object-list 编辑器和条件显隐机制。仅修改 1 个文件。

## 2. 新增组件设计

### 2.1 object-list 编辑器

**用途**：编辑 `discord.guilds` 等 object[] 类型。

**数据结构**：
```javascript
{
  path: 'platforms.discord.guilds',
  label: '服务器列表',
  type: 'object-list',
  desc: 'Discord 服务器配置',
  itemFields: [
    { key: 'id', label: '服务器 ID', type: 'text' },
    { key: 'name', label: '名称', type: 'text' },
    { key: 'allowed_channels', label: '允许频道', type: 'tags' },
  ]
}
```

**DOM 结构**：
```
div.object-list[data-path="..."]
  div.object-list-item.collapsed
    div.object-item-header  (摘要 + 展开/删除按钮)
    div.object-item-body    (表单字段，默认隐藏)
  div.object-list-item.expanded
    ...
  button.object-list-add (+ 添加)
```

**交互**：
- 折叠状态显示摘要：第一个 text 字段值或 "项目 #N"
- 点击 header 展开/折叠
- 删除按钮（需确认）
- 添加按钮在列表末尾
- 内部字段复用 mkText、mkTags 等已有 builder

**collectData 处理**：
```javascript
case 'object-list':
  const items = document.querySelectorAll(`.object-list-item[data-path="${field.path}"]`);
  const arr = [];
  items.forEach(item => {
    const obj = {};
    field.itemFields.forEach(f => {
      // 从每个 item 内收集子字段
      obj[f.key] = collectSubField(item, f);
    });
    arr.push(obj);
  });
  setVal(data, field.path, arr);
  break;
```

### 2.2 条件显隐机制

**用途**：TTS provider 切换时显隐不同字段组。

**字段定义扩展**：
```javascript
{
  path: 'voice.tts.voice_id',
  label: '音色',
  type: 'select',
  source: 'tts_voices',
  showWhen: { field: 'voice.tts.provider', equals: 'edge' }
}
```

**实现**：
```javascript
function shouldShow(field) {
  if (!field.showWhen) return true;
  const triggerField = document.querySelector(
    `[data-path="${field.showWhen.field}"]`
  );
  if (!triggerField) return true;
  const currentVal = triggerField.tagName === 'SELECT'
    ? triggerField.value
    : (triggerField.checked ? 'true' : 'false');
  return currentVal === field.showWhen.equals;
}
```

**触发机制**：在 mkSelect 中为 TTS provider 注册 change 事件，触发时重新渲染整个 TTS 卡片：
```javascript
el.addEventListener('change', () => {
  if (field.triggersVisibility) {
    renderSection(currentSection);  // 重新渲染保留当前值
  }
});
```

**值保留问题**：重新渲染会丢失用户未保存的修改。解决方案：
- 渲染前快照当前卡片的所有字段值
- 重新渲染后恢复非 showWhen 控制的字段值
- 或者用 CSS display:none 隐藏而非重新渲染（推荐）

**最终方案**：用 CSS 控制显隐，不重新渲染：
```javascript
function updateVisibility(card) {
  card.querySelectorAll('[data-show-when]').forEach(el => {
    const cond = JSON.parse(el.dataset.showWhen);
    el.style.display = shouldShow(cond) ? '' : 'none';
  });
}
```

## 3. 各模块补齐方案

### 3.1 voice 模块

**总开关卡片** — 补充字段：
| 字段 | 类型 | 选项 |
|------|------|------|
| `voice.voice_mode` | select | replace（替换）、append（追加） |
| `voice.voice_decision` | select | ai（AI 判断）、always（总是）、never（从不） |

**TTS 卡片** — 补充字段 + 条件显隐：
| 字段 | 类型 | 显示条件 |
|------|------|---------|
| `voice.tts.mimo_voice` | select | provider = mimo |
| `voice.tts.mimo_style` | text | provider = mimo |
| `voice.tts.mimo_model` | text | provider = mimo |
| `voice.tts.ffmpeg_path` | text | 始终 |
| `voice.tts.output_format` | select | 始终 |
| `voice.tts.voice_sample_path` | text | provider = cosyvoice2 |
| `voice.tts.voice_sample_text` | textarea | provider = cosyvoice2 |

provider select 新增 `mimo` 选项。

**RVC 卡片**（新增）：
| 字段 | 类型 |
|------|------|
| `voice.rvc.enabled` | bool |
| `voice.rvc.model_name` | text |
| `voice.rvc.model_dir` | text |
| `voice.rvc.f0up_key` | number |
| `voice.rvc.f0_method` | select (rmvpe/pm/harvest/crepe) |
| `voice.rvc.index_rate` | range (0-1) |
| `voice.rvc.filter_radius` | number |
| `voice.rvc.rms_mix_rate` | range (0-1) |
| `voice.rvc.protect` | range (0-0.5) |
| `voice.rvc.device` | select (cpu/cuda:0) |
| `voice.rvc.half_precision` | bool |
| `voice.rvc.sample_rate` | number |

**ASR 卡片** — 补充：
| 字段 | 类型 |
|------|------|
| `voice.asr.base_url` | text |

**Wake Word 卡片**（新增）：
| 字段 | 类型 |
|------|------|
| `voice.wake_word.provider` | select (porcupine/none) |
| `voice.wake_word.keywords` | tags |

### 3.2 platforms 模块

**QQ 卡片** — 补充：
| 字段 | 类型 |
|------|------|
| `platforms.qq.connection.suffix` | text |
| `platforms.qq.allowed_groups` | tags |
| `platforms.qq.allowed_users` | tags |
| `platforms.qq.block_list` | tags |

**Discord 卡片** — 补充：
| 字段 | 类型 |
|------|------|
| `platforms.discord.guilds` | object-list |
| └ `id` | text |
| └ `name` | text |
| └ `allowed_channels` | tags |
| `platforms.discord.rate_limit.per_channel` | number |

**Telegram 卡片** — 补充：
| 字段 | 类型 |
|------|------|
| `platforms.telegram.allowed_users` | tags |
| `platforms.telegram.allowed_chats` | tags |
| `platforms.telegram.block_list` | tags |

**微信卡片** — 补充：
| 字段 | 类型 |
|------|------|
| `platforms.wechat.allowed_users` | tags |

### 3.3 memory 模块

功能特性开关卡片展开为独立子卡片，每个 feature 的参数可见：

| 字段 | 类型 |
|------|------|
| `memory.features.reranker.model` | text |
| `memory.features.reranker.top_k` | number |
| `memory.features.composer.max_tokens` | number |
| `memory.features.lifecycle.short_term_ttl` | number |
| `memory.features.lifecycle.long_term_archive_after` | number |
| `memory.features.graph.persist_path` | text |
| `memory.features.versioning.max_versions` | number |

### 3.4 mcp 模块

| 字段 | 类型 |
|------|------|
| `mcp.builtin_tools` | tags |
| `mcp.tool_discovery.directories` | tags |
| `mcp.hardware.mqtt.esp32_topics` | tags |

### 3.5 visual 模块

| 字段 | 类型 | 选项 |
|------|------|------|
| `visual.camera.provider` | select | esp32, usb, local |
| `visual.vision.provider` | select | openai, local |

## 4. 边界条件与风险

### 4.1 值类型转换

config.yaml 中的值可能是字符串或数字。UI 收集时需统一类型：
- `number` 字段：`Number(el.value)`，空值跳过
- `bool` 字段：`el.checked` 返回 boolean
- `select` 字段：匹配 option value 类型

### 4.2 空值处理

- object-list 为空时返回 `[]`，不返回 undefined
- tags 为空时返回 `[]`
- text 字段空值返回 `''`

### 4.3 敏感字段保护

新增字段中的敏感字段（如 `voice.asr.api_key`）已在后端 SENSITIVE_FIELDS 中定义，UI 中用 `type: 'sensitive'` 渲染为只读。

### 4.4 后端 PUT 合并

现有 `/api/config/sections/{section}` 使用 deep merge。object-list 字段需要整体替换（PUT body 中的值覆盖原值），不能追加。当前后端实现已支持此行为。

## 5. 测试策略

由于是纯前端单文件修改，无自动化测试框架：
1. **手动验证**：逐个 section 打开 UI，确认所有字段可见且可编辑
2. **保存验证**：修改后保存，检查 config.yaml 内容正确
3. **边界测试**：空值、特殊字符、超长输入
4. **条件显隐**：切换 TTS provider，确认字段正确显隐
5. **object-list**：添加/删除 guild，保存后验证 YAML 结构
