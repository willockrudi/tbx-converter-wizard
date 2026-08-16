# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for TBX Converter Wizard. One shared spec for all three
platforms, branching on sys.platform internally rather than diverging into
three separate spec files to keep in sync.

Build (from the repo root, /home/filament/tbx_dvd_wizard):
    pip install -r requirements.txt pyinstaller
    pyinstaller packaging/tbx_converter_wizard.spec

Output lands in dist/ - a single onefile executable on Windows/Linux, a
proper .app BUNDLE on macOS.
"""

import sys
from pathlib import Path

block_cipher = None

REPO_ROOT = Path(SPECPATH).parent
ICON_PNG = REPO_ROOT / "packaging" / "icons" / "icon.png"
ICON_ICO = REPO_ROOT / "packaging" / "icons" / "icon.ico"
ICON_ICNS = REPO_ROOT / "packaging" / "icons" / "icon.icns"  # built by the macOS CI job; may not exist locally

if sys.platform == "win32":
    icon_path = str(ICON_ICO) if ICON_ICO.exists() else None
elif sys.platform == "darwin":
    icon_path = str(ICON_ICNS) if ICON_ICNS.exists() else None
else:
    icon_path = None  # Linux executables don't embed an icon this way

a = Analysis(
    [str(REPO_ROOT / "run_entry.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TBXConverterWizard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # no console window behind the tkinter GUI on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="TBX Converter Wizard.app",
        icon=icon_path,
        bundle_identifier="com.tbx.converterwizard",
        info_plist={
            "NSHighResolutionCapable": "True",
            "CFBundleShortVersionString": "0.1.0",
        },
    )
