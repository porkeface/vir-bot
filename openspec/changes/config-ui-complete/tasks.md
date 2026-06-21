# Tasks: 补齐配置管理 UI

## T1: 新增 object-list 组件
- [x] 新增 `mkObjectList(path, value, itemFields)` 函数
- [x] 可折叠卡片：展开显示表单，折叠显示摘要
- [x] 支持添加新对象、删除已有对象
- [x] 内嵌字段复用 mkText、mkTags 等 builder
- [x] collectData 中处理 object-list 类型的数据收集

## T2: 新增条件显隐机制
- [x] 字段定义支持 `showWhen: { field, value }` 属性
- [x] renderField 时检查 showWhen，不满足则隐藏
- [x] 切换触发字段时重新渲染所在卡片

## T3: 补齐 voice 模块（~15 字段）
- [x] 总开关卡片：补充 `voice_mode`（select）、`voice_decision`（select）
- [x] TTS 卡片：补充 mimo provider 选项 + `mimo_voice`/`mimo_style`/`mimo_model` 字段
- [x] TTS 卡片：补充 `ffmpeg_path`、`output_format`、`voice_sample_path`、`voice_sample_text`
- [x] TTS 卡片：实现 provider 条件显隐（edge/cosyvoice2/mimo）
- [x] 新增 RVC 卡片：`rvc.enabled` + 8 个参数字段
- [x] ASR 卡片：补充 `base_url` 字段
- [x] 新增 Wake Word 卡片：`provider`（select）+ `keywords`（tags）

## T4: 补齐 platforms 模块（~10 字段）
- [x] QQ 卡片：补充 `connection.suffix`、`allowed_groups`（tags）、`allowed_users`（tags）、`block_list`（tags）
- [x] Discord 卡片：新增 `guilds`（object-list，含 id/name/allowed_channels）
- [x] Telegram 卡片：补充 `allowed_users`（tags）、`allowed_chats`（tags）、`block_list`（tags）
- [x] 微信卡片：补充 `allowed_users`（tags）

## T5: 补齐 memory 模块（~7 字段）
- [x] Re-Ranker 卡片：补充 `model`（text）、`top_k`（number）
- [x] Composer 字段：补充 `max_tokens`（number）
- [x] Lifecycle 字段：补充 `short_term_ttl`（number）、`long_term_archive_after`（number）
- [x] Graph 字段：补充 `persist_path`（text）
- [x] Versioning 字段：补充 `max_versions`（number）

## T6: 补齐 mcp 模块（~3 字段）
- [x] 工具系统卡片：补充 `builtin_tools`（tags）
- [x] 工具发现：补充 `directories`（tags）
- [x] 硬件卡片：补充 `esp32_topics`（tags）

## T7: 补齐 visual + web_console 模块（~3 字段）
- [x] 摄像头卡片：补充 `camera.provider`（select: esp32/usb/local）
- [x] 视觉模型卡片：补充 `vision.provider`（select: openai/local）

## T8: 验证
- [x] JS 语法平衡检查通过（437 对花括号、133 对方括号）
- [x] 所有 7 个 commit 按任务顺序提交
- [x] 代码逻辑审查完成，无语法错误

> 运行时验证将在 verify 阶段手动执行
