import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from app.paths import BASE_DIR, CONFIG_FILE, EXAMPLE_CONFIG_FILE


def _check(name, ok, detail="", hint=""):
    return {
        "name": name,
        "ok": bool(ok),
        "detail": str(detail or ""),
        "hint": str(hint or ""),
    }


def _optional(module_name):
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def run_checks():
    checks = []

    try:
        from dotenv import load_dotenv

        load_dotenv(BASE_DIR / ".env", override=True)
    except Exception:
        pass

    checks.append(
        _check(
            "Python",
            sys.version_info >= (3, 10),
            sys.version.split()[0],
            "Нужен Python 3.10+.",
        )
    )

    config_path = (
        CONFIG_FILE if CONFIG_FILE.exists() else EXAMPLE_CONFIG_FILE
    )
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            checks.append(
                _check("Конфигурация", True, str(config_path))
            )
        except (OSError, ValueError) as error:
            checks.append(
                _check(
                    "Конфигурация",
                    False,
                    f"{config_path}: {error}",
                    "Проверьте JSON-синтаксис.",
                )
            )
    else:
        checks.append(
            _check(
                "Конфигурация",
                False,
                "config.json не найден",
                "Скопируйте config.example.json в config.json.",
            )
        )

    groq_api_key = (
        os.getenv("GROQ_API_KEY")
        or config.get("groq_api_key")
        or ""
    )
    llm_config = (
        config.get("llm", {})
        if isinstance(config.get("llm"), dict)
        else {}
    )
    provider = str(llm_config.get("provider", "deepseek")).lower()
    deepseek_api_key = (
        llm_config.get("api_key")
        or os.getenv("DEEPSEEK_API_KEY")
        or config.get("deepseek_api_key")
        or ""
    )
    llm_local = bool(
        provider == "ollama"
        or llm_config.get("base_url")
    )

    stt_local = bool(config.get("stt_local_model"))
    checks.append(
        _check(
            "GROQ_API_KEY (STT/vision)",
            bool(groq_api_key) or stt_local,
            (
                "ключ найден"
                if groq_api_key
                else "не нужен: выбрана локальная STT-модель"
            ),
            "Добавьте GROQ_API_KEY в .env или stt_local_model "
            "в config.json.",
        )
    )
    checks.append(
        _check(
            "DEEPSEEK_API_KEY (LLM)",
            bool(deepseek_api_key) or llm_local,
            (
                "ключ найден"
                if deepseek_api_key
                else "не нужен: выбран локальный LLM-эндпоинт"
            ),
            "Добавьте DEEPSEEK_API_KEY в .env или llm.api_key "
            "в config.json.",
        )
    )

    data_dir = BASE_DIR / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=str(data_dir),
            delete=True,
        ) as file:
            file.write(b"ok")
        writable = True
        detail = str(data_dir)
    except Exception as error:
        writable = False
        detail = f"{BASE_DIR / 'data'}: {error}"
    checks.append(
        _check(
            "Запись data",
            writable,
            detail,
            "Проверьте права на папку data.",
        )
    )

    try:
        usage = shutil.disk_usage(BASE_DIR)
        free_gb = usage.free / (1024 ** 3)
        checks.append(
            _check(
                "Свободное место",
                free_gb >= 1,
                f"{free_gb:.1f} ГБ",
                "Освободите хотя бы 1 ГБ.",
            )
        )
    except OSError as error:
        checks.append(
            _check("Свободное место", False, str(error))
        )

    required_modules = {
        "requests": "requests",
        "psutil": "psutil",
        "pyautogui": "PyAutoGUI",
        "PIL": "Pillow",
        "groq": "groq",
        "edge_tts": "edge-tts",
        "dotenv": "python-dotenv",
        "sounddevice": "sounddevice",
    }
    for module, package in required_modules.items():
        checks.append(
            _check(
                f"Модуль {package}",
                _optional(module),
                module,
                f"pip install {package}",
            )
        )

    optional_modules = {
        "playwright": "playwright",
        "pytesseract": "pytesseract",
        "cv2": "opencv-python",
        "docx": "python-docx",
        "openpyxl": "openpyxl",
        "pptx": "python-pptx",
        "pypdf": "pypdf",
        "icalendar": "icalendar",
        "pystray": "pystray",
        "pyttsx3": "pyttsx3",
    }
    for module, package in optional_modules.items():
        checks.append(
            _check(
                f"Опционально {package}",
                _optional(module),
                module,
                f"pip install {package}",
            )
        )

    if config.get("stt_local_model"):
        checks.append(
            _check(
                "faster-whisper",
                _optional("faster_whisper"),
                "локальная STT-модель настроена",
                "pip install -r requirements-optional.txt",
            )
        )

    tesseract = shutil.which("tesseract")
    checks.append(
        _check(
            "Tesseract OCR",
            bool(tesseract),
            tesseract or "не найден в PATH",
            "Установите Tesseract-OCR и добавьте в PATH.",
        )
    )

    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        checks.append(_check("ffmpeg", bool(ffmpeg), ffmpeg))
    except Exception as error:
        checks.append(
            _check(
                "ffmpeg",
                bool(shutil.which("ffmpeg")),
                str(error),
                "pip install imageio-ffmpeg.",
            )
        )

    browser_root = Path.home() / "AppData" / "Local" / "ms-playwright"
    checks.append(
        _check(
            "Playwright Chromium",
            browser_root.exists() and any(browser_root.glob("chromium-*")),
            str(browser_root),
            "python -m playwright install chromium",
        )
    )

    return checks


def format_report(checks=None):
    checks = checks if checks is not None else run_checks()
    lines = ["JARVIS DIAGNOSTICS", "=" * 50]
    for item in checks:
        mark = "[OK]  " if item["ok"] else "[FAIL]"
        line = f"{mark} {item['name']}: {item['detail']}"
        if not item["ok"] and item["hint"]:
            line += f" | {item['hint']}"
        lines.append(line)
    failed = sum(1 for item in checks if not item["ok"])
    lines.append("=" * 50)
    lines.append(
        f"Итог: {len(checks) - failed} OK, {failed} требуют внимания."
    )
    return "\n".join(lines)


def main():
    checks = run_checks()
    print(format_report(checks))
    return 0 if all(item["ok"] for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
