"""Сабсет UI-шрифтов в WOFF2 (латиница + кириллица).

TTF-набор весит ~530 КБ; в интерфейсе используются только
латиница, кириллица, цифры и типографика, поэтому остальные
глифы можно выбросить. Запуск (нужны fonttools[brotli]):

    .venv\\Scripts\\python.exe scripts\\subset_fonts.py

Скрипт перезаписывает *.woff2 рядом с исходными TTF; fonts.css
подключает WOFF2 первым, TTF остаётся запасным вариантом.
"""

from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "ui" / "assets" / "fonts"
UNICODES = (
    "U+0000-00FF,"     # базовая латиница, цифры, пунктуация
    "U+0400-045F,"     # кириллица
    "U+0490-0491,"     # Ґ ґ
    "U+2010-2027,"     # тире, кавычки, многоточие
    "U+20AC,"          # €
    "U+2116,"          # №
    "U+2190-2193"      # стрелки
)


def main():
    sources = sorted(FONTS.glob("*-Variable.ttf"))
    if not sources:
        raise SystemExit(f"Шрифты не найдены: {FONTS}")
    for source in sources:
        target = source.with_suffix(".woff2")
        subset.main(
            [
                str(source),
                f"--output-file={target}",
                "--flavor=woff2",
                f"--unicodes={UNICODES}",
                "--layout-features=*",
                "--name-IDs=*",
            ]
        )
        before = source.stat().st_size / 1024
        after = target.stat().st_size / 1024
        print(f"{source.name}: {before:.0f} КБ -> {after:.0f} КБ")


if __name__ == "__main__":
    main()
