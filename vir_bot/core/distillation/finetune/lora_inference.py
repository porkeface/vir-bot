# -*- coding: utf-8 -*-
"""
LoRA Adapter 推理模块

支持：
- 加载训练好的 LoRA adapter 进行推理
- 与 AIProvider 集成，提供统一的生成接口
- Adapter 热切换（多角色支持）
- 系统提示词注入（角色卡作为 system prompt）

使用方式：
    from vir_bot.core.distillation.finetune import create_inference
    engine = create_inference(adapter_path="data/lora_adapters/persona_adapter")
    response = engine.generate("你好啊", system_prompt="你是小雅...")
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GenerationConfig:
    """生成参数配置。"""
    max_new_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50
    repetition_penalty: float = 1.1
    do_sample: bool = True
    num_beams: int = 1


@dataclass
class InferenceResult:
    """推理结果。"""
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    adapter: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "adapter": self.adapter,
        }


class LoRAInference:
    """
    LoRA Adapter 推理引擎。

    封装 HuggingFace transformers + PEFT 的推理流程：
    1. 加载基座模型（支持量化加载以节省显存）
    2. 加载 LoRA adapter
    3. 提供 generate() 接口进行推理
    4. 支持 adapter 热切换

    与 AIProvider 的区别：
    - AIProvider 是 API 调用（远程模型），LoRAInference 是本地推理
    - LoRAInference 加载了微调 adapter，生成风格更贴近目标角色
    """

    def __init__(
        self,
        adapter_path: str,
        *,
        base_model: Optional[str] = None,
        device: str = "auto",
        load_in_4bit: bool = False,
        load_in_8bit: bool = False,
        generation_config: Optional[GenerationConfig] = None,
    ) -> None:
        """
        Args:
            adapter_path: LoRA adapter 目录路径
            base_model: 基座模型路径/名称（如为 None，从 adapter 配置读取）
            device: 设备（auto/cpu/cuda/mps）
            load_in_4bit: 是否 4-bit 量化加载（节省显存）
            load_in_8bit: 是否 8-bit 量化加载
            generation_config: 默认生成参数
        """
        self._adapter_path = Path(adapter_path)
        self._base_model_override = base_model
        self._device = device
        self._load_in_4bit = load_in_4bit
        self._load_in_8bit = load_in_8bit
        self._gen_config = generation_config or GenerationConfig()

        self._model = None
        self._tokenizer = None
        self._base_model_name: str = ""
        self._current_adapter: str = ""
        self._lock = threading.Lock()

        # 自动加载
        self._load()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def adapter_path(self) -> str:
        return str(self._adapter_path)

    @property
    def base_model(self) -> str:
        return self._base_model_name

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """加载基座模型 + LoRA adapter。"""
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            from peft import PeftModel
        except ImportError as e:
            raise ImportError(
                "需要安装 transformers, torch, peft: "
                "pip install transformers torch peft"
            ) from e

        # 读取 adapter 配置
        config_path = self._adapter_path / "training_config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                train_config = json.load(f)
            self._base_model_name = self._base_model_override or train_config.get("base_model", "")
        else:
            self._base_model_name = self._base_model_override or ""

        if not self._base_model_name:
            raise ValueError(
                f"无法确定基座模型：adapter 目录 {self._adapter_path} 中无 training_config.json，"
                "且未指定 base_model 参数"
            )

        logger.info("加载基座模型：%s", self._base_model_name)

        # 量化配置
        quantization_config = None
        if self._load_in_4bit or self._load_in_8bit:
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=self._load_in_4bit,
                load_in_8bit=self._load_in_8bit,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )

        # 确定模型路径（优先本地）
        model_path = self._resolve_model_path()

        # 加载基座模型
        model_kwargs: Dict[str, Any] = {
            "trust_remote_code": True,
            "torch_dtype": torch.bfloat16,
            "device_map": self._device if self._device != "auto" else "auto",
        }
        if quantization_config:
            model_kwargs["quantization_config"] = quantization_config

        base_model = AutoModelForCausalLM.from_pretrained(model_path, **model_kwargs)

        # 加载 LoRA adapter
        logger.info("加载 LoRA adapter：%s", self._adapter_path)
        self._model = PeftModel.from_pretrained(base_model, str(self._adapter_path))
        self._model.eval()

        # 加载 tokenizer
        tokenizer_path = str(self._adapter_path) if (self._adapter_path / "tokenizer.json").exists() else model_path
        self._tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_path,
            trust_remote_code=True,
            padding_side="left",
        )
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        self._current_adapter = str(self._adapter_path)
        logger.info("LoRA 推理引擎加载完成")

    def _resolve_model_path(self) -> str:
        """解析模型路径（优先本地 pretrained_models/）。"""
        model_name = self._base_model_name
        local_path = Path("./pretrained_models") / model_name.split("/")[-1]
        if local_path.exists():
            logger.info("从本地加载模型：%s", local_path)
            return str(local_path)
        return model_name

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------

    def generate(
        self,
        user_input: str,
        *,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        generation_config: Optional[GenerationConfig] = None,
    ) -> InferenceResult:
        """
        生成回复。

        Args:
            user_input: 用户输入
            system_prompt: 系统提示词（角色卡描述）
            history: 对话历史 [{"role": "user/assistant", "content": "..."}]
            generation_config: 生成参数覆盖

        Returns:
            InferenceResult 推理结果
        """
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("推理引擎未加载")

        config = generation_config or self._gen_config

        # 使用 Alpaca 格式（与训练格式一致）
        input_text = self._build_alpaca_prompt(user_input, system_prompt, history)

        inputs = self._tokenizer(
            input_text,
            return_tensors="pt",
            truncation=True,
            max_length=4096,
        ).to(self._model.device)

        input_len = inputs["input_ids"].shape[1]

        # 生成
        with self._lock:
            import torch
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=config.max_new_tokens,
                    temperature=config.temperature if config.do_sample else 1.0,
                    top_p=config.top_p if config.do_sample else 1.0,
                    top_k=config.top_k if config.do_sample else 0,
                    repetition_penalty=config.repetition_penalty,
                    do_sample=config.do_sample,
                    num_beams=config.num_beams,
                    pad_token_id=self._tokenizer.pad_token_id,
                )

        # 解码
        generated_ids = outputs[0][input_len:]
        output_text = self._tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
        # 清理可能泄漏的 Alpaca 格式标记
        for marker in ["###", "### 指令", "### 输入", "### 回复"]:
            if marker in output_text:
                output_text = output_text[:output_text.index(marker)].strip()

        return InferenceResult(
            text=output_text,
            input_tokens=input_len,
            output_tokens=len(generated_ids),
            total_tokens=input_len + len(generated_ids),
            model=self._base_model_name,
            adapter=self._current_adapter,
        )

    def generate_stream(
        self,
        user_input: str,
        *,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        generation_config: Optional[GenerationConfig] = None,
    ):
        """
        流式生成回复（逐 token 输出）。

        Yields:
            str: 每次生成的 token 文本片段
        """
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("推理引擎未加载")

        try:
            from transformers import TextIteratorStreamer
        except ImportError:
            raise ImportError("需要安装 transformers >= 4.33 以支持 TextIteratorStreamer")

        config = generation_config or self._gen_config
        input_text = self._build_alpaca_prompt(user_input, system_prompt, history)

        inputs = self._tokenizer(
            input_text,
            return_tensors="pt",
            truncation=True,
            max_length=4096,
        ).to(self._model.device)

        streamer = TextIteratorStreamer(
            self._tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        import threading as _threading
        generation_kwargs = {
            **inputs,
            "max_new_tokens": config.max_new_tokens,
            "temperature": config.temperature if config.do_sample else 1.0,
            "top_p": config.top_p if config.do_sample else 1.0,
            "top_k": config.top_k if config.do_sample else 0,
            "repetition_penalty": config.repetition_penalty,
            "do_sample": config.do_sample,
            "pad_token_id": self._tokenizer.pad_token_id,
            "streamer": streamer,
        }

        thread = _threading.Thread(target=self._model.generate, kwargs=generation_kwargs)
        thread.start()

        for text_chunk in streamer:
            if text_chunk:
                yield text_chunk

        thread.join()

    # ------------------------------------------------------------------
    # Adapter 热切换
    # ------------------------------------------------------------------

    def swap_adapter(self, new_adapter_path: str) -> None:
        """
        热切换 LoRA adapter（用于多角色支持）。

        Args:
            new_adapter_path: 新 adapter 目录路径
        """
        if self._model is None:
            raise RuntimeError("推理引擎未加载")

        new_path = Path(new_adapter_path)
        if not new_path.exists():
            raise FileNotFoundError(f"Adapter 目录不存在：{new_path}")

        logger.info("切换 adapter：%s → %s", self._current_adapter, new_adapter_path)

        with self._lock:
            from peft import PeftModel
            # 卸载当前 adapter，加载新的
            self._model.unload()
            self._model = PeftModel.from_pretrained(
                self._model.base_model,
                str(new_path),
            )
            self._model.eval()

        self._current_adapter = str(new_path)
        self._adapter_path = new_path

        # 更新 base_model 配置
        config_path = new_path / "training_config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                train_config = json.load(f)
            self._base_model_name = train_config.get("base_model", self._base_model_name)

        logger.info("Adapter 切换完成：%s", new_adapter_path)

    # ------------------------------------------------------------------
    # 消息构建
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        user_input: str,
        system_prompt: Optional[str],
        history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        """构建消息列表（旧方法，保留兼容）。"""
        messages: List[Dict[str, str]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": user_input})
        return messages

    def _build_alpaca_prompt(
        self,
        user_input: str,
        system_prompt: Optional[str],
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        """构建 Alpaca 格式 prompt（与训练格式一致）。"""
        instruction = (
            system_prompt
            or "你正在扮演一个角色。请以该角色的风格回复。"
        )

        context_parts: List[str] = []
        if history:
            for msg in history[-10:]:
                role = "用户" if msg.get("role") == "user" else "助手"
                context_parts.append(f"{role}: {msg.get('content', '')}")
        context_parts.append(f"用户: {user_input}")
        context = "\n".join(context_parts)

        return (
            f"### 指令：\n{instruction}\n\n"
            f"### 输入：\n{context}\n\n"
            f"### 回复：\n"
        )

    # ------------------------------------------------------------------
    # 工厂方法
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config_path: str, **kwargs: Any) -> "LoRAInference":
        """
        从训练配置文件创建推理实例。

        Args:
            config_path: adapter 目录路径或 training_config.json 路径
            **kwargs: 传递给 __init__ 的额外参数
        """
        p = Path(config_path)
        if p.is_file() and p.name == "training_config.json":
            adapter_path = str(p.parent)
        else:
            adapter_path = str(p)

        return cls(adapter_path=adapter_path, **kwargs)

    @classmethod
    def from_training_result(cls, result_path: str, **kwargs: Any) -> "LoRAInference":
        """
        从训练结果目录创建推理实例。

        Args:
            result_path: 训练结果目录路径（包含 adapter_model.safetensors 等）
            **kwargs: 传递给 __init__ 的额外参数
        """
        return cls(adapter_path=result_path, **kwargs)


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def create_inference(
    adapter_path: str,
    *,
    base_model: Optional[str] = None,
    load_in_4bit: bool = False,
    **kwargs: Any,
) -> LoRAInference:
    """创建 LoRA 推理引擎的便捷函数。"""
    return LoRAInference(
        adapter_path=adapter_path,
        base_model=base_model,
        load_in_4bit=load_in_4bit,
        **kwargs,
    )
