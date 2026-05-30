"""测试 CosyVoice2 输出质量"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

async def main():
    from vir_bot.config import load_config
    from vir_bot.modules.voice import CosyVoice2TTSProvider

    config = load_config()
    tts = CosyVoice2TTSProvider(
        model_dir=config.voice.tts.model_dir,
        speed=config.voice.tts.speed,
        instruct_text=config.voice.tts.instruct_text,
    )

    output = str(Path("./data/cache/test_quality.wav"))
    print(f"合成中... (instruct2 模式, instruct_text='{tts.instruct_text}')")
    result = await tts.synthesize("你好，我是暖树，很高兴认识你呀", output)

    if result and Path(result).exists():
        size = Path(result).stat().st_size
        print(f"合成成功: {result} ({size} bytes)")
    else:
        print(f"合成失败: {result}")

if __name__ == "__main__":
    asyncio.run(main())
