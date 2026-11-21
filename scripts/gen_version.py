"""Генерирует version-ресурс для JARVIS.exe (FileDescription, ProductName и т.д.).

Запуск: python scripts/gen_version.py  ->  build/jarvis_version.txt
"""

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


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)

    strings = [
        StringStruct("CompanyName", "JARVIS"),
        StringStruct("FileDescription", "JARVIS Personal Assistant"),
        StringStruct("FileVersion", "1.0.0.0"),
        StringStruct("InternalName", "JARVIS"),
        StringStruct("LegalCopyright", "JARVIS"),
        StringStruct("OriginalFilename", "JARVIS.exe"),
        StringStruct("ProductName", "JARVIS"),
        StringStruct("ProductVersion", "1.0.0.0"),
    ]

    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=(1, 0, 0, 0),
            prodvers=(1, 0, 0, 0),
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
    print(f"[JARVIS] Version info written: {OUT}")


if __name__ == "__main__":
    main()
