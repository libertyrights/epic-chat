# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'aiohttp',
        'rebootpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
        'distutils',
        'setuptools',
        'pip',
        'idlelib',
        'turtle',
        'turtledemo',
        'unittest',
        'email',
        'http.server',
        'sqlite3',
        'pydoc',
    ],
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
    name='EpicChat',
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
    icon=None,
)
