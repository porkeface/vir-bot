---
archived-with: 2026-06-21-config-ui-complete
status: final
---
# 配置管理 UI 补齐 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 config/index.html 中缺失的 38 个配置字段，新增 object-list 编辑器和条件显隐机制

**Architecture:** 在现有单文件 vanilla JS 配置 UI 中新增两种组件能力（object-list 可折叠卡片、showWhen 条件显隐），然后逐模块补齐缺失字段定义

**Tech Stack:** Vanilla JS, HTML, CSS（无框架，单文件）

**Base Commit:** b5d924e18a9a85b06bbc83d0af2fd302600f97c7

**Target File:** `vir_bot/api/static/config/index.html`

---

### Task 1: 新增 object-list 组件

**Files:**
- Modify: `vir_bot/api/static/config/index.html`

本任务在 SECTIONS 定义之前新增 object-list 相关的 CSS 样式和 JS 函数。

- [ ] **Step 1: 添加 object-list CSS 样式**

在 `</style>` 标签之前（约第 112 行），追加以下 CSS：

```css
/* Object list (collapsible cards) */
.object-list{display:flex;flex-direction:column;gap:8px;max-width:480px}
.object-list-item{border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden}
.object-item-header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);cursor:pointer;user-select:none}
.object-item-header:hover{background:var(--border)}
.object-item-summary{font-size:13px;color:var(--text2);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.object-item-actions{display:flex;align-items:center;gap:8px}
.object-item-btn{background:none;border:none;color:var(--text3);cursor:pointer;font-size:16px;padding:2px 6px;border-radius:4px}
.object-item-btn:hover{color:var(--text);background:var(--surface)}
.object-item-btn.danger:hover{color:var(--danger)}
.object-item-body{padding:14px;display:none}
.object-item-body.open{display:block}
.object-item-body .field-group{margin-bottom:12px}
.object-item-body .field-group:last-child{margin-bottom:0}
.object-list-add{margin-top:8px;padding:6px 14px;background:var(--surface2);border:1px dashed var(--border);border-radius:var(--radius-sm);color:var(--text2);font-size:13px;cursor:pointer;width:100%;text-align:center}
.object-list-add:hover{border-color:var(--accent);color:var(--accent)}
```

- [ ] **Step 2: 添加 mkObjectList 函数**

在 `mkTags` 函数之后（约第 907 行），追加 object-list 构建器：

```javascript
function mkObjectList(path, value, itemFields) {
  const container = document.createElement('div');
  container.className = 'object-list';
  container.dataset.path = path;
  const items = Array.isArray(value) ? [...value] : [];

  function renderItems() {
    container.querySelectorAll('.object-list-item').forEach(el => el.remove());
    const addBtn = container.querySelector('.object-list-add');
    items.forEach((item, idx) => {
      const el = createObjectListItem(path, idx, item, itemFields, items, () => {
        renderItems();
      });
      container.insertBefore(el, addBtn);
    });
  }

  const addBtn = document.createElement('button');
  addBtn.className = 'object-list-add';
  addBtn.type = 'button';
  addBtn.textContent = '+ 添加';
  addBtn.addEventListener('click', () => {
    const newObj = {};
    itemFields.forEach(f => { newObj[f.key] = f.type === 'tags' ? [] : ''; });
    items.push(newObj);
    renderItems();
  });
  container.appendChild(addBtn);

  container._getItems = () => {
    // Collect current values from DOM
    const result = [];
    container.querySelectorAll('.object-list-item').forEach(el => {
      const obj = {};
      itemFields.forEach(f => {
        if (f.type === 'tags') {
          const tagsEl = el.querySelector(`.tags-container[data-path$="${f.key}"]`);
          obj[f.key] = tagsEl && tagsEl._getItems ? tagsEl._getItems() : [];
        } else {
          const input = el.querySelector(`[data-sub-key="${f.key}"]`);
          obj[f.key] = input ? input.value : '';
        }
      });
      result.push(obj);
    });
    return result;
  };

  renderItems();
  return container;
}

function createObjectListItem(parentPath, idx, item, itemFields, items, onRemove) {
  const el = document.createElement('div');
  el.className = 'object-list-item';

  const header = document.createElement('div');
  header.className = 'object-item-header';

  const summary = document.createElement('span');
  summary.className = 'object-item-summary';
  const firstText = itemFields.find(f => f.type === 'text' || !f.type);
  const summaryVal = firstText ? (item[firstText.key] || '') : '';
  summary.textContent = summaryVal || `项目 #${idx + 1}`;

  const actions = document.createElement('span');
  actions.className = 'object-item-actions';

  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'object-item-btn';
  toggleBtn.type = 'button';
  toggleBtn.textContent = '▼';
  const delBtn = document.createElement('button');
  delBtn.className = 'object-item-btn danger';
  delBtn.type = 'button';
  delBtn.textContent = '✕';

  actions.appendChild(toggleBtn);
  actions.appendChild(delBtn);
  header.appendChild(summary);
  header.appendChild(actions);

  const body = document.createElement('div');
  body.className = 'object-item-body';

  itemFields.forEach(f => {
    const fg = document.createElement('div');
    fg.className = 'field-group';
    const lbl = document.createElement('label');
    lbl.className = 'field-label';
    lbl.textContent = f.label;
    fg.appendChild(lbl);
    if (f.type === 'tags') {
      fg.appendChild(mkTags(`${parentPath}[${idx}].${f.key}`, item[f.key] || []));
    } else {
      const input = document.createElement('input');
      input.type = 'text';
      input.dataset.subKey = f.key;
      input.value = item[f.key] ?? '';
      fg.appendChild(input);
    }
    body.appendChild(fg);
  });

  header.addEventListener('click', (e) => {
    if (e.target === delBtn || delBtn.contains(e.target)) return;
    body.classList.toggle('open');
    toggleBtn.textContent = body.classList.contains('open') ? '▲' : '▼';
  });

  delBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    items.splice(idx, 1);
    onRemove();
  });

  el.appendChild(header);
  el.appendChild(body);
  return el;
}
```

- [ ] **Step 3: 在 collectData 中处理 object-list 类型**

在 `collectData` 函数的 switch 块中（约第 938 行的 `case 'range'` 之前），添加：

```javascript
      if (field.type === 'object-list') {
        const el = document.querySelector(`.object-list[data-path="${field.path}"]`);
        if (el && el._getItems) setVal(data, field.path, el._getItems());
      } else if
```

- [ ] **Step 4: 在 renderField 中处理 object-list 类型**

在 `renderField` 函数的 switch 块中（约第 716 行），在 `case 'tags'` 之前添加：

```javascript
    case 'object-list': group.appendChild(mkObjectList(field.path, value, field.itemFields)); break;
```

- [ ] **Step 5: 提交**

```bash
git add vir_bot/api/static/config/index.html
git commit -m "feat(config-ui): add object-list collapsible card component"
```

---

### Task 2: 新增条件显隐机制

**Files:**
- Modify: `vir_bot/api/static/config/index.html`

- [ ] **Step 1: 添加 shouldShow 和 updateVisibility 函数**

在 `mkObjectList` 函数之后，`createObjectListItem` 函数之前，添加：

```javascript
function shouldShow(condition) {
  const trigger = document.querySelector(`[data-path="${condition.field}"]`);
  if (!trigger) return true;
  let currentVal;
  if (trigger.type === 'checkbox') {
    currentVal = String(trigger.checked);
  } else {
    currentVal = trigger.value;
  }
  return currentVal === String(condition.equals);
}

function updateVisibility(cardEl) {
  cardEl.querySelectorAll('[data-show-when]').forEach(el => {
    const cond = JSON.parse(el.dataset.showWhen);
    el.style.display = shouldShow(cond) ? '' : 'none';
  });
}
```

- [ ] **Step 2: 修改 renderField 支持 showWhen**

在 `renderField` 函数开头（`const group = document.createElement('div');` 之后），添加 showWhen 数据属性：

```javascript
  if (field.showWhen) {
    group.dataset.showWhen = JSON.stringify(field.showWhen);
    group.style.display = shouldShow(field.showWhen) ? '' : 'none';
  }
```

- [ ] **Step 3: 修改 mkSelect 支持触发可见性更新**

在 `mkSelect` 函数末尾（`return el;` 之前），添加 change 事件监听：

```javascript
  el.addEventListener('change', () => {
    const card = el.closest('.card');
    if (card) updateVisibility(card);
  });
```

- [ ] **Step 4: 修改 mkToggle 支持触发可见性更新**

在 `mkToggle` 函数中，`input.addEventListener('change', ...)` 的回调末尾追加：

```javascript
    const card = input.closest('.card');
    if (card) updateVisibility(card);
```

- [ ] **Step 5: 修改 renderSection 在渲染后触发可见性更新**

在 `renderSection` 函数末尾（`container.appendChild(cardEl);` 之后），添加：

```javascript
    updateVisibility(cardEl);
```

- [ ] **Step 6: 提交**

```bash
git add vir_bot/api/static/config/index.html
git commit -m "feat(config-ui): add showWhen conditional visibility mechanism"
```

---

### Task 3: 补齐 voice 模块

**Files:**
- Modify: `vir_bot/api/static/config/index.html` — SECTIONS.voice 部分

本任务重写 voice 的 SECTIONS 定义，补充所有缺失字段。

- [ ] **Step 1: 替换 voice SECTIONS 定义**

将整个 `voice:` section（约第 452-497 行）替换为：

```javascript
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
```

- [ ] **Step 2: 验证语法**

在浏览器中打开 config 页面，检查 voice section 是否正常渲染。控制台无报错。

- [ ] **Step 3: 提交**

```bash
git add vir_bot/api/static/config/index.html
git commit -m "feat(config-ui): complete voice module fields (rvc/wake_word/mimo)"
```

---

### Task 4: 补齐 platforms 模块

**Files:**
- Modify: `vir_bot/api/static/config/index.html` — SECTIONS.platforms 部分

- [ ] **Step 1: 修改 QQ 卡片，补充访问控制字段**

在 QQ 卡片的 fields 数组末尾（`rate_limit.per_group` 之后）追加：

```javascript
          { path: 'platforms.qq.connection.suffix', label: '路径后缀', type: 'text', desc: 'WebSocket 路径后缀（如 /ws）' },
          { path: 'platforms.qq.allowed_groups', label: '允许的群号', type: 'tags', desc: '留空表示不限制' },
          { path: 'platforms.qq.allowed_users', label: '允许的用户号', type: 'tags', desc: '留空表示不限制' },
          { path: 'platforms.qq.block_list', label: '黑名单', type: 'tags' },
```

- [ ] **Step 2: 修改 Discord 卡片，补充 guilds 和 rate_limit**

将 Discord 卡片的 fields 替换为：

```javascript
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
```

- [ ] **Step 3: 修改 Telegram 卡片，补充访问控制字段**

在 Telegram 卡片的 `rate_limit.per_chat` 之后追加：

```javascript
          { path: 'platforms.telegram.allowed_users', label: '允许的用户', type: 'tags' },
          { path: 'platforms.telegram.allowed_chats', label: '允许的聊天', type: 'tags' },
          { path: 'platforms.telegram.block_list', label: '黑名单', type: 'tags' },
```

- [ ] **Step 4: 修改企业微信卡片，补充 allowed_users**

在企业微信卡片的 fields 末尾追加：

```javascript
          { path: 'platforms.wechat.allowed_users', label: '允许的用户', type: 'tags' },
```

- [ ] **Step 5: 提交**

```bash
git add vir_bot/api/static/config/index.html
git commit -m "feat(config-ui): complete platforms access control fields"
```

---

### Task 5: 补齐 memory 模块

**Files:**
- Modify: `vir_bot/api/static/config/index.html` — SECTIONS.memory 部分

- [ ] **Step 1: 将功能特性开关卡片拆分为独立子卡片**

将原来的「功能特性开关」单卡片（约第 318-330 行）替换为多个独立卡片，每个 feature 有自己的参数：

```javascript
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
```

- [ ] **Step 2: 提交**

```bash
git add vir_bot/api/static/config/index.html
git commit -m "feat(config-ui): expand memory feature cards with parameter fields"
```

---

### Task 6: 补齐 mcp 模块

**Files:**
- Modify: `vir_bot/api/static/config/index.html` — SECTIONS.mcp 部分

- [ ] **Step 1: 修改工具系统卡片，补充 builtin_tools 和 directories**

在工具系统卡片的 fields 末尾追加：

```javascript
          { path: 'mcp.builtin_tools', label: '内置工具', type: 'tags', desc: '启动时自动加载的工具列表' },
          { path: 'mcp.tool_discovery.directories', label: '工具目录', type: 'tags', desc: '扫描工具文件的目录列表' },
```

- [ ] **Step 2: 修改硬件卡片，补充 esp32_topics**

在硬件卡片的 fields 末尾追加：

```javascript
          { path: 'mcp.hardware.mqtt.esp32_topics', label: 'ESP32 主题', type: 'tags', desc: 'MQTT 订阅主题列表' },
```

- [ ] **Step 3: 提交**

```bash
git add vir_bot/api/static/config/index.html
git commit -m "feat(config-ui): add mcp tool lists and mqtt topics fields"
```

---

### Task 7: 补齐 visual + web_console 模块

**Files:**
- Modify: `vir_bot/api/static/config/index.html` — SECTIONS.visual 部分

- [ ] **Step 1: 修改摄像头卡片，补充 provider 选择器**

在摄像头卡片的 fields 开头（`esp32_url` 之前）插入：

```javascript
          { path: 'visual.camera.provider', label: '摄像头类型', type: 'select', options: [
            { value: 'esp32', label: 'ESP32-CAM（网络摄像头）' },
            { value: 'usb', label: 'USB 摄像头' },
            { value: 'local', label: '本地图像' },
          ]},
```

- [ ] **Step 2: 修改视觉模型卡片，补充 provider 选择器**

在视觉模型卡片的 fields 开头（`model` 之前）插入：

```javascript
          { path: 'visual.vision.provider', label: '视觉引擎', type: 'select', options: [
            { value: 'openai', label: 'OpenAI 兼容 API' },
            { value: 'local', label: '本地模型' },
          ]},
```

- [ ] **Step 3: 提交**

```bash
git add vir_bot/api/static/config/index.html
git commit -m "feat(config-ui): add visual provider selectors"
```

---

### Task 8: 验证所有 section 渲染正常

**Files:**
- Modify: `openspec/changes/config-ui-complete/tasks.md`（勾选任务）

- [ ] **Step 1: 启动服务验证**

```bash
uv run python -m vir_bot.main
```

在浏览器中依次打开 13 个 section，检查：
- 所有字段可见且可编辑
- voice section 的 TTS provider 切换时字段正确显隐
- Discord guilds 的 object-list 增删正常
- 保存后 config.yaml 内容正确
- 敏感字段只读显示

- [ ] **Step 2: 勾选 tasks.md 所有任务**

将 `openspec/changes/config-ui-complete/tasks.md` 中所有 `- [ ]` 改为 `- [x]`。

- [ ] **Step 3: 最终提交**

```bash
git add openspec/changes/config-ui-complete/tasks.md
git commit -m "chore: mark all config-ui-complete tasks as done"
```
