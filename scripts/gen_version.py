"""Генерирует version-ресурс для JARVIS.exe (FileDescription, ProductName и т.д.).

Единственный источник версии — ``#define MyAppVersion`` в
``packaging/jarvis.iss``: EXE и установщик всегда показывают одно
и то же, а обновлять нужно ровно одну строку.

Запуск: python scripts/gen_version.py  ->  build/jarvis_version.txt
"""

import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "jarvis_version.txt"
INNO = ROOT / "packaging" / "jarvis.iss"


def project_version():
    text = INNO.read_text(encoding="utf-8")
    match = re.search(
        r'#define\s+MyAppVersion\s+"([^"]+)"', text
    )
    if match is None:
        raise SystemExit(f"MyAppVersion не найден в {INNO}")
    return match.group(1)


def version_tuple(version):
    parts = [int(part) for part in re.findall(r"\d+", version)][:4]
    return tuple(parts + [0] * (4 - len(parts)))


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    version = project_version()
    numbers = version_tuple(version)
    dot_version = ".".join(str(part) for part in numbers)

    strings = [
        StringStruct("CompanyName", "JARVIS"),
        StringStruct("FileDescription", "JARVIS Personal Assistant"),
        StringStruct("FileVersion", dot_version),
        StringStruct("InternalName", "JARVIS"),
        StringStruct("LegalCopyright", "JARVIS"),
        StringStruct("OriginalFilename", "JARVIS.exe"),
        StringStruct("ProductName", "JARVIS"),
        StringStruct("ProductVersion", dot_version),
    ]

    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numbers,
            prodvers=numbers,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([StringTable("040904B0", strings)]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

    OUT.write_text(str(version_info), encoding="utf-8")
    print(f"[JARVIS] Version info written: {OUT} ({version})")


if __name__ == "__main__":
    main()
