# RVC 语音转换后处理层 — 任务规格书

> **状态**: 已实现（commit bbf330c）
> **作者**: vir-bot team
> **日期**: 2026-06-05

---

## 1. 功能需求

### 1.1 背景

当前 TTS 链路（MiMo API / edge-tts）输出的语音音色固定，无法自定义为目标角色（陈暖树）的音色。需要在 TTS 输出后增加 **RVC（Retrieval-based Voice Conversion）** 后处理层，将任意 TTS 输出转换为目标音色。

### 1.2 核心需求

| 编号 | 需求 | 优先级 |
|------|------|--------|
| RVC-01 | 支持加载 RVC 模型（.pth + .index），执行音色转换 | P0 |
| RVC-02 | 模型懒加载：首次 convert() 时才初始化，避免启动耗时 | P0 |
| RVC-03 | RVC 作为装饰器包装现有 TTSProvider，TTS → RVC 链式调用 | P0 |
| RVC-04 | RVC 转换失败时自动回退到原始 TTS 音频，不破坏消息链路 | P0 |
| RVC-05 | 通过 config.yaml 开关控制，一行配置切换 | P0 |
| RVC-06 | RVC 依赖（rvc-python / fairseq）为 optional，未安装时不报错 | P1 |
| RVC-07 | 支持音高偏移、基频提取方法、索引匹配率等参数调优 | P1 |
| RVC-08 | 模型文件自动发现（扫描 data/rvc_models/{name}/ 目录） | P1 |
| RVC-09 | 读取 metadata.json 更新采样率等元信息 | P2 |

### 1.3 非功能需求

- RVC 推理必须在线程池中执行（`run_in_executor`），不阻塞 asyncio 事件循环
- 支持 CPU / CUDA 设备切换
- 支持半精度推理节省显存
- 单元测试覆盖率 > 80%（14 个测试用例）

---

## 2. 技术方案

### 2.1 架构设计

```
TTSProvider (MiMo/Edge)
    ↓ synthesize()
RVCWrappedTTSProvider (装饰器)
    ↓ convert()
RVCInferenceEngine
    ↓ _get_model() [懒加载]
    ↓ _convert_sync() [线程池]
    ↓ rvc_python.infer.VC
```

### 2.2 模块划分

| 文件 | 职责 |
|------|------|
| `vir_bot/modules/voice/rvc.py` | RVCInferenceEngine 推理引擎 + RVCEngineError |
| `vir_bot/modules/voice/__init__.py` | RVCWrappedTTSProvider 装饰器 + create_tts() 工厂集成 |
| `vir_bot/config.py` | VoiceRVCConfig 配置类 |
| `tests/unit/test_rvc.py` | 14 个单元测试 |

### 2.3 关键设计决策

1. **装饰器模式**: RVCWrappedTTSProvider 实现 TTSProvider 接口，包装任意 TTS 实现，符合开闭原则
2. **懒加载**: 复用 SenseVoiceASRProvider 的 `_get_model()` 模式，首次调用时初始化
3. **optional 依赖**: `from rvc_python.infer import VC` 在 `_get_model()` 内部导入，未安装时抛出 RVCEngineError 而非 ImportError
4. **文件替换策略**: RVC 输出写入 `_rvc.wav` 临时文件，成功后 rename 覆盖原始 TTS 文件

---

## 3. 接口定义

### 3.1 RVCInferenceEngine

```python
class RVCInferenceEngine:
    def __init__(self, model_dir, model_name, device, half_precision, sample_rate)
    def _discover_model(self) -> tuple[str, str]  # (pth_path, index_path)
    def _get_model(self)                           # 懒加载，无返回值
    async def convert(self, input_path, output_path, **params) -> str
    def switch_model(self, model_name)             # 切换模型，重置状态
    @property is_loaded -> bool
    @property model_info -> dict
```

### 3.2 RVCWrappedTTSProvider

```python
class RVCWrappedTTSProvider(TTSProvider):
    def __init__(self, inner: TTSProvider, rvc_engine: RVCInferenceEngine, rvc_config: VoiceRVCConfig)
    async def synthesize(self, text, output_path, **kwargs) -> str | None
    # 内部逻辑: inner.synthesize() → rvc_engine.convert() → 回退
```

### 3.3 VoiceRVCConfig

```python
class VoiceRVCConfig(BaseModel):
    enabled: bool = False
    model_name: str = "default"
    model_dir: str = "data/rvc_models"
    f0up_key: int = 0
    f0_method: str = "rmvpe"
    index_rate: float = 0.75
    filter_radius: int = 3
    rms_mix_rate: float = 0.25
    protect: float = 0.33
    device: str = "cpu"
    half_precision: bool = True
    sample_rate: int = 48000
```

---

## 4. 验收标准

| 编号 | 标准 | 验证方式 |
|------|------|----------|
| AC-01 | RVC 未启用时 create_tts() 返回普通 TTS | test_create_tts_rvc_disabled |
| AC-02 | RVC 启用时 create_tts() 返回 RVCWrappedTTSProvider | test_create_tts_rvc_enabled |
| AC-03 | TTS 成功 + RVC 成功 → 返回 RVC 输出 | test_tts_success_rvc_success |
| AC-04 | TTS 成功 + RVC 失败 → 回退到原始 TTS | test_tts_success_rvc_fail_fallback |
| AC-05 | TTS 失败 → 返回 None | test_tts_fail_returns_none |
| AC-06 | 模型目录不存在 → 抛出 RVCEngineError | test_discover_model_dir_not_exists_raises |
| AC-07 | 无 .pth 文件 → 抛出 RVCEngineError | test_discover_model_no_pth_raises |
| AC-08 | 跳过 *.opt.pth 文件 | test_discover_model_skips_opt_pth |
| AC-09 | 从 metadata.json 读取 sample_rate | test_discover_model_success |
| AC-10 | 切换模型重置加载状态 | test_switch_model_resets_state |
| AC-11 | 切换到相同已加载模型不做操作 | test_switch_same_model_noop |
| AC-12 | 全部 14 个测试通过 | `uv run pytest tests/unit/test_rvc.py -q` |

---

## 5. 配置示例

```yaml
voice:
  enabled: true
  rvc:
    enabled: true
    model_name: "nuanshu"
    model_dir: "data/rvc_models"
    f0up_key: 0
    f0_method: "rmvpe"
    index_rate: 0.75
    device: "cuda:0"
    half_precision: true
```

---

## 6. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-06-05 | 初始实现：RVCInferenceEngine + RVCWrappedTTSProvider + 14 个测试 |

---

## 7. 审查代码文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `vir_bot/modules/voice/rvc.py` | 236 | RVC 推理引擎 |
| `vir_bot/modules/voice/__init__.py` | +85 | RVCWrappedTTSProvider + create_tts() 集成 |
| `vir_bot/config.py` | +17 | VoiceRVCConfig 配置类 |
| `tests/unit/test_rvc.py` | 281 | 14 个单元测试 |
| `pyproject.toml` | +4 | rvc-python optional 依赖 |

---

*本规格书对应 commit `bbf330c feat(voice): 新增 RVC 语音转换层，支持音色后处理`*

> **审查指引**: 请审查上述 5 个文件中的实际代码实现，规格书作为上下文参考。

