# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Yoto-UP GUI application."""

import sys
from pathlib import Path

# Paths
gui_path = Path("gui")
core_path = Path("core")

a = Analysis(
    [str(gui_path / "yoto_up_gui" / "main.py")],
    pathex=[str(gui_path), str(core_path)],
    binaries=[],
    datas=[
        (str(gui_path / "yoto_up_gui" / "resources"), "yoto_up_gui/resources"),
    ],
    hiddenimports=[
        "yoto_up",
        "yoto_up.models",
        "yoto_up.models.card",
        "yoto_up.models.device",
        "yoto_up.models.user",
        "yoto_up.api",
        "yoto_up.api.client",
        "yoto_up.api.auth",
        "yoto_up.api.cards",
        "yoto_up.api.devices",
        "yoto_up.api.icons",
        "yoto_up.api.media",
        "yoto_up.storage",
        "yoto_up.storage.config",
        "yoto_up.storage.paths",
        "yoto_up.storage.tokens",
        "yoto_up.storage.cache",
        "yoto_up.storage.versions",
        "yoto_up.audio",
        "yoto_up.audio.normalize",
        "yoto_up.audio.trim",
        "yoto_up.audio.waveform",
        "PySide6",
        "httpx",
        "pydantic",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="yoto-up",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Add app icon
)
