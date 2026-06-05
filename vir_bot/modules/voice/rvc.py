"""RVC 语音转换推理引擎

使用 rvc-python 库执行音色转换。懒加载模型，首次调用时初始化。
模型文件存放于 data/rvc_models/{model_name}/ 目录。
"""

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class RVCEngineError(Exception):
    """RVC 引擎错误"""


class RVCInferenceEngine:
    """RVC 语音转换推理引擎

    懒加载模型，首次 convert() 时初始化。
    遵循 SenseVoiceASRProvider 的 _get_model() 模式。
    """

    def __init__(
        self,
        model_dir: str = "data/rvc_models",
        model_name: str = "default",
        device: str = "cpu",
        half_precision: bool = True,
        sample_rate: int = 48000,
    ):
        self.model_dir = Path(model_dir)
        self.model_name = model_name
        self.device = device
        self.half_precision = half_precision
        self.sample_rate = sample_rate

        # 懒加载状态
        self._model_loaded = False
        self._vc = None  # VoiceConverter 实例
        self._model_path: str | None = None
        self._index_path: str | None = None
        self._metadata: dict = {}

    def _discover_model(self) -> tuple[str, str]:
        """发现模型文件 (.pth + .index)

        扫描 model_dir/model_name/ 目录。
        返回 (pth_path, index_path)

        Raises:
            RVCEngineError: 模型文件不存在或目录异常
        """
        model_path = self.model_dir / self.model_name

        if not model_path.exists():
            raise RVCEngineError(
                f"RVC 模型目录不存在: {model_path}\n"
                f"请将 .pth 和 .index 文件放入 {self.model_dir}/{self.model_name}/"
            )

        # 查找 .pth 文件（排除 *.opt.pth）
        pth_files = [f for f in model_path.glob("*.pth") if not f.name.endswith(".opt.pth")]
        if not pth_files:
            raise RVCEngineError(f"未找到 .pth 模型文件: {model_path}")
        pth_path = str(pth_files[0])

        # 查找 .index 文件
        index_files = list(model_path.glob("*.index"))
        index_path = str(index_files[0]) if index_files else ""

        # 读取 metadata.json（可选）
        metadata_path = model_path / "metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, encoding="utf-8") as f:
                    self._metadata = json.load(f)
                # 从 metadata 更新 sample_rate
                if "sample_rate" in self._metadata:
                    self.sample_rate = self._metadata["sample_rate"]
            except Exception as e:
                logger.warning(f"[RVC] 读取 metadata.json 失败: {e}")

        logger.info(f"[RVC] 发现模型: pth={pth_path}, index={index_path or '无'}")
        return pth_path, index_path

    def _get_model(self):
        """懒加载 RVC 模型

        首次调用时初始化 VoiceConverter。
        后续调用直接返回（已加载的模型）。

        Raises:
            RVCEngineError: 模型加载失败
        """
        if self._model_loaded:
            return

        try:
            from rvc_python.infer import VC
        except ImportError:
            raise RVCEngineError(
                "rvc-python 未安装。请运行: uv add rvc-python"
            )

        self._model_path, self._index_path = self._discover_model()

        try:
            self._vc = VC(self.device, self.half_precision)
            self._vc.get_vc(self._model_path)
            self._model_loaded = True
            logger.info(
                f"[RVC] 模型加载成功: {self.model_name} "
                f"(device={self.device}, half={self.half_precision})"
            )
        except Exception as e:
            raise RVCEngineError(f"RVC 模型加载失败: {e}")

    async def convert(
        self,
        input_path: str,
        output_path: str,
        f0up_key: int = 0,
        f0_method: str = "rmvpe",
        index_rate: float = 0.75,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
    ) -> str:
        """执行 RVC 音色转换

        Args:
            input_path: 输入音频路径（TTS 输出的 WAV）
            output_path: 输出音频路径
            f0up_key: 音高偏移（半音）
            f0_method: 基频提取方法
            index_rate: 索引匹配率
            filter_radius: 滤波半径
            rms_mix_rate: RMS 混合率
            protect: 辅音保护率

        Returns:
            输出文件路径

        Raises:
            RVCEngineError: 转换失败
        """
        self._get_model()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._convert_sync,
            input_path,
            output_path,
            f0up_key,
            f0_method,
            index_rate,
            filter_radius,
            rms_mix_rate,
            protect,
        )

    def _convert_sync(
        self,
        input_path: str,
        output_path: str,
        f0up_key: int,
        f0_method: str,
        index_rate: float,
        filter_radius: int,
        rms_mix_rate: float,
        protect: float,
    ) -> str:
        """同步推理（在线程池中执行）"""
        try:
            # 确保输出目录存在
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            # 执行 RVC 转换
            self._vc.single(
                input_path=input_path,
                output_path=output_path,
                f0up_key=f0up_key,
                f0_method=f0_method,
                index_path=self._index_path or "",
                index_rate=index_rate,
                filter_radius=filter_radius,
                rms_mix_rate=rms_mix_rate,
                protect=protect,
            )

            if not Path(output_path).exists():
                raise RVCEngineError("RVC 转换完成但输出文件不存在")

            file_size = Path(output_path).stat().st_size
            logger.info(f"[RVC] 转换完成: {output_path} ({file_size} bytes)")
            return output_path

        except RVCEngineError:
            raise
        except Exception as e:
            raise RVCEngineError(f"RVC 转换失败: {e}")

    def switch_model(self, model_name: str):
        """切换模型（重置懒加载状态）"""
        if model_name == self.model_name and self._model_loaded:
            return
        self.model_name = model_name
        self._model_loaded = False
        self._vc = None
        self._model_path = None
        self._index_path = None
        self._metadata = {}
        logger.info(f"[RVC] 切换模型: {model_name}")

    @property
    def is_loaded(self) -> bool:
        return self._model_loaded

    @property
    def model_info(self) -> dict:
        """返回当前模型信息"""
        return {
            "model_name": self.model_name,
            "model_dir": str(self.model_dir),
            "model_path": self._model_path,
            "index_path": self._index_path,
            "device": self.device,
            "half_precision": self.half_precision,
            "sample_rate": self.sample_rate,
            "loaded": self._model_loaded,
            "metadata": self._metadata,
        }
