# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Material Cert Validator.

Build with: pyinstaller build_exe.spec
"""

import sys
from pathlib import Path

# Paths
BASE_DIR = Path(SPECPATH)
GUI_DIR = BASE_DIR / 'src' / 'gui'
LIB_DIR = BASE_DIR / 'src' / 'lib'
SPECS_DIR = BASE_DIR / 'specs'

a = Analysis(
    ['run_gui.py'],
    pathex=[str(BASE_DIR), str(BASE_DIR / 'src')],
    binaries=[],
    datas=[
        # Include spec YAML files
        (str(SPECS_DIR / '*.yaml'), 'specs'),
    ],
    hiddenimports=[
        'customtkinter',
        'tkinterdnd2',
        'PIL',
        'PIL.Image',
        'fitz',
        'httpx',
        'yaml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='MaterialCertValidator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Add icon file
)
