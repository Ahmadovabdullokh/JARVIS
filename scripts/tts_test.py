"""Диагностика TTS JARVIS: проверяет голоса Edge и офлайн-фолбэк.

    .venv\\Scripts\\python.exe scripts\\tts_test.py
    .venv\\Scripts\\python.exe scripts\\tts_test.py --speak
    .venv\\Scripts\\python.exe scripts\\tts_test.py --offline
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import edge_tts  # noqa: E402

from app.config import get_tts_config, load_config  # noqa: E402
from app.tts import TTS  # noqa: E402


async def _probe(voice, text, timeout=20):
    total = 0
    started = time.monotonic()
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+0%",
        volume="+0%",
        pitch="-8Hz",
    )
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            total += len(chunk["data"])
    return total, time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description="Проверка голосов JARVIS.")
    parser.add_argument("--text", default="Привет. Проверка синтеза речи.")
    parser.add_argument("--speak", action="store_true",
                        help="озвучить текст через динамики")
    parser.add_argument("--offline", action="store_true",
                        help="проверить только pyttsx3/SAPI")
    args = parser.parse_args()

    config = get_tts_config(load_config())
    voices = list(dict.fromkeys([config["voice"], *config["voices"]]))
    print("Настроенные голоса:", ", ".join(voices))
    print("Устройство вывода:", config.get("output_device") or "по умолчанию")

    if not args.offline:
        for voice in voices:
            try:
                size, elapsed = asyncio.run(
                    asyncio.wait_for(
                        _probe(voice, args.text),
                        timeout=25,
                    )
                )
                status = f"OK, {size} байт за {elapsed:.1f} c"
            except Exception as error:
                status = f"ОШИБКА {type(error).__name__}: {error}"
            print(f"  {voice}: {status}")

    if args.speak:
        tts = TTS(
            rate=config["rate"],
            voice=config["voice"],
            pitch=config["pitch"],
            voices=config["voices"],
            offline_fallback=True,
            output_device=config["output_device"],
            stream_sentences=config["stream_sentences"],
        )
        print("Озвучка:", "успешно" if tts.speak(args.text) else "не удалось")

    if args.offline or args.speak:
        tts = TTS(rate=config["rate"], voice=config["voice"])
        print("Офлайн-фолбэк:", "успешно" if tts._speak_offline(args.text)
              else "не удалось")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
