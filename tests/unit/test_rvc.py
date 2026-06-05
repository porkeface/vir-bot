"""RVC 语音转换单元测试"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vir_bot.modules.voice.rvc import RVCEngineError, RVCInferenceEngine


@pytest.fixture
def tmp_model_dir(tmp_path):
    """创建临时模型目录，包含 .pth 和 .index 文件"""
    model_dir = tmp_path / "rvc_models" / "test_model"
    model_dir.mkdir(parents=True)

    # 创建假的 .pth 文件
    (model_dir / "test_model.pth").write_bytes(b"fake model data")

    # 创建假的 .index 文件
    (model_dir / "test_model.index").write_bytes(b"fake index data")

    # 创建 metadata.json
    metadata = {
        "name": "test_model",
        "version": "v2",
        "sample_rate": 48000,
        "f0_method": "rmvpe",
        "description": "测试模型",
    }
    (model_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    return tmp_path / "rvc_models"


@pytest.fixture
def tmp_model_dir_no_index(tmp_path):
    """创建只有 .pth 没有 .index 的模型目录"""
    model_dir = tmp_path / "rvc_models" / "no_index_model"
    model_dir.mkdir(parents=True)
    (model_dir / "model.pth").write_bytes(b"fake model data")
    return tmp_path / "rvc_models"


@pytest.fixture
def tmp_model_dir_empty(tmp_path):
    """创建空的模型目录"""
    model_dir = tmp_path / "rvc_models" / "empty_model"
    model_dir.mkdir(parents=True)
    return tmp_path / "rvc_models"


class TestRVCInferenceEngineDiscovery:
    """模型发现测试"""

    def test_discover_model_success(self, tmp_model_dir):
        """正常发现 .pth + .index + metadata.json"""
        engine = RVCInferenceEngine(
            model_dir=str(tmp_model_dir),
            model_name="test_model",
        )
        pth_path, index_path = engine._discover_model()

        assert pth_path.endswith(".pth")
        assert index_path.endswith(".index")
        assert engine.sample_rate == 48000  # 从 metadata 读取

    def test_discover_model_no_index(self, tmp_model_dir_no_index):
        """没有 .index 文件时返回空字符串"""
        engine = RVCInferenceEngine(
            model_dir=str(tmp_model_dir_no_index),
            model_name="no_index_model",
        )
        pth_path, index_path = engine._discover_model()

        assert pth_path.endswith(".pth")
        assert index_path == ""

    def test_discover_model_no_pth_raises(self, tmp_model_dir_empty):
        """没有 .pth 文件时抛出 RVCEngineError"""
        engine = RVCInferenceEngine(
            model_dir=str(tmp_model_dir_empty),
            model_name="empty_model",
        )
        with pytest.raises(RVCEngineError, match="未找到 .pth"):
            engine._discover_model()

    def test_discover_model_dir_not_exists_raises(self, tmp_path):
        """模型目录不存在时抛出 RVCEngineError"""
        engine = RVCInferenceEngine(
            model_dir=str(tmp_path / "nonexistent"),
            model_name="test",
        )
        with pytest.raises(RVCEngineError, match="不存在"):
            engine._discover_model()

    def test_discover_model_skips_opt_pth(self, tmp_model_dir):
        """发现模型时跳过 *.opt.pth 文件"""
        # 添加一个 opt.pth 文件
        (tmp_model_dir / "test_model" / "test_model.opt.pth").write_bytes(b"opt data")

        engine = RVCInferenceEngine(
            model_dir=str(tmp_model_dir),
            model_name="test_model",
        )
        pth_path, _ = engine._discover_model()
        assert "opt.pth" not in pth_path


class TestRVCInferenceEngineModelInfo:
    """模型信息测试"""

    def test_model_info_before_load(self, tmp_model_dir):
        """加载前的模型信息"""
        engine = RVCInferenceEngine(
            model_dir=str(tmp_model_dir),
            model_name="test_model",
        )
        info = engine.model_info

        assert info["model_name"] == "test_model"
        assert info["loaded"] is False
        assert info["device"] == "cpu"

    def test_is_loaded_false_initially(self, tmp_model_dir):
        """初始状态未加载"""
        engine = RVCInferenceEngine(
            model_dir=str(tmp_model_dir),
            model_name="test_model",
        )
        assert engine.is_loaded is False


class TestRVCSwitchModel:
    """模型切换测试"""

    def test_switch_model_resets_state(self, tmp_model_dir):
        """切换模型重置加载状态"""
        engine = RVCInferenceEngine(
            model_dir=str(tmp_model_dir),
            model_name="test_model",
        )
        # 模拟已加载状态
        engine._model_loaded = True

        engine.switch_model("other_model")

        assert engine.model_name == "other_model"
        assert engine._model_loaded is False
        assert engine._vc is None

    def test_switch_same_model_noop(self, tmp_model_dir):
        """切换到相同模型且已加载时不做任何事"""
        engine = RVCInferenceEngine(
            model_dir=str(tmp_model_dir),
            model_name="test_model",
        )
        engine._model_loaded = True

        engine.switch_model("test_model")
        assert engine._model_loaded is True


class TestRVCWrappedTTSProvider:
    """RVC 装饰器测试"""

    @pytest.mark.asyncio
    async def test_tts_success_rvc_success(self, tmp_path):
        """TTS 成功 + RVC 成功 → 返回 RVC 输出"""
        from vir_bot.config import VoiceRVCConfig
        from vir_bot.modules.voice import RVCWrappedTTSProvider, TTSProvider

        # Mock TTS provider
        class MockTTS(TTSProvider):
            async def synthesize(self, text, output_path, **kwargs):
                Path(output_path).write_bytes(b"tts audio")
                return output_path

        # Mock RVC engine
        mock_engine = MagicMock()
        mock_engine.convert = MagicMock(
            side_effect=lambda input_path, output_path, **kwargs: (
                Path(output_path).write_bytes(b"rvc audio"),
                output_path,
            )[-1]
        )
        # Make convert async
        import asyncio

        async def mock_convert(input_path, output_path, **kwargs):
            Path(output_path).write_bytes(b"rvc audio")
            return output_path

        mock_engine.convert = mock_convert

        rvc_config = VoiceRVCConfig(enabled=True)
        provider = RVCWrappedTTSProvider(MockTTS(), mock_engine, rvc_config)

        output = str(tmp_path / "test.wav")
        result = await provider.synthesize("你好", output)

        assert result == output
        assert Path(output).read_bytes() == b"rvc audio"

    @pytest.mark.asyncio
    async def test_tts_success_rvc_fail_fallback(self, tmp_path):
        """TTS 成功 + RVC 失败 → 回退到原始 TTS"""
        from vir_bot.config import VoiceRVCConfig
        from vir_bot.modules.voice import RVCWrappedTTSProvider, TTSProvider

        class MockTTS(TTSProvider):
            async def synthesize(self, text, output_path, **kwargs):
                Path(output_path).write_bytes(b"tts audio")
                return output_path

        # Mock RVC engine that raises
        mock_engine = MagicMock()

        async def mock_convert_fail(*args, **kwargs):
            raise RVCEngineError("模型加载失败")

        mock_engine.convert = mock_convert_fail

        rvc_config = VoiceRVCConfig(enabled=True)
        provider = RVCWrappedTTSProvider(MockTTS(), mock_engine, rvc_config)

        output = str(tmp_path / "test.wav")
        result = await provider.synthesize("你好", output)

        assert result == output
        assert Path(output).read_bytes() == b"tts audio"  # 原始 TTS 音频

    @pytest.mark.asyncio
    async def test_tts_fail_returns_none(self, tmp_path):
        """TTS 失败 → 返回 None"""
        from vir_bot.config import VoiceRVCConfig
        from vir_bot.modules.voice import RVCWrappedTTSProvider, TTSProvider

        class MockTTS(TTSProvider):
            async def synthesize(self, text, output_path, **kwargs):
                return None

        mock_engine = MagicMock()
        rvc_config = VoiceRVCConfig(enabled=True)
        provider = RVCWrappedTTSProvider(MockTTS(), mock_engine, rvc_config)

        output = str(tmp_path / "test.wav")
        result = await provider.synthesize("你好", output)

        assert result is None


class TestCreateTTSWithRVC:
    """create_tts 工厂函数 RVC 集成测试"""

    def test_create_tts_rvc_disabled(self):
        """RVC 未启用时不包装"""
        from vir_bot.config import VoiceConfig, VoiceRVCConfig, VoiceTTSConfig
        from vir_bot.modules.voice import MiMoTTSProvider, TTSFallbackProvider, create_tts

        config = VoiceConfig(enabled=True)
        config.rvc.enabled = False

        tts = create_tts(config)
        assert tts is not None
        # 不应该是 RVCWrappedTTSProvider
        assert not hasattr(tts, "rvc_engine")

    def test_create_tts_rvc_enabled(self):
        """RVC 启用时包装为 RVCWrappedTTSProvider"""
        from vir_bot.config import VoiceConfig, VoiceRVCConfig
        from vir_bot.modules.voice import RVCWrappedTTSProvider, create_tts

        config = VoiceConfig(enabled=True)
        config.rvc.enabled = True
        config.rvc.model_name = "test"

        tts = create_tts(config)
        assert tts is not None
        assert isinstance(tts, RVCWrappedTTSProvider)
