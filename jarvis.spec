# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = collect_submodules("app")
hiddenimports += [
    "pystray",
    "pyttsx3",
    "winotify",
    "PIL._tkinter_finder",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "pythonnet",
    "clr_loader",
    "pythoncom",
    "win32gui",
    "win32con",
    "mediapipe",
    "mediapipe.tasks",
    "mediapipe.tasks.python",
    "mediapipe.tasks.python.vision",
]
hiddenimports += collect_submodules("mediapipe.tasks.python")

datas = [
    ("config/config.example.json", "config"),
    ("ui", "ui"),
    ("app/locales", "app/locales"),
    ("plugins", "plugins"),
    ("models", "models"),
]
datas += collect_data_files("imageio_ffmpeg")
datas += collect_data_files("webview")
datas += collect_data_files("mediapipe")


a = Analysis(
    ["launcher_web.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JARVIS",
    icon="packaging/jarvis.ico",
    version="build/jarvis_version.txt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JARVIS",
)
