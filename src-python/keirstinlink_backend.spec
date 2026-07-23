# -*- mode: python ; coding: utf-8 -*-

import sys
sys.setrecursionlimit(5000)

# Ensure PyInstaller uses this project's clean build venv, not the Hermes venv.
import os
BUILD_VENV = os.path.abspath(os.path.join(os.getcwd(), '.venv-build', 'Lib', 'site-packages'))
HOOKSPATH = os.path.join(BUILD_VENV, 'PyInstaller', 'hooks')
CONTRIB_HOOKSPATH = os.path.join(BUILD_VENV, '_pyinstaller_hooks_contrib', 'stdhooks')

block_cipher = None

a = Analysis(
    ['keirstinlink_backend_entry.py'],
    pathex=[BUILD_VENV],
    binaries=[],
    datas=[],
    hiddenimports=[
        'keirstin_link.api',
        'keirstin_link.config',
        'keirstin_link.discovery',
        'keirstin_link.folder_index',
        'keirstin_link.main',
        'keirstin_link.models',
        'keirstin_link.settings_store',
        'keirstin_link.store',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        'uvicorn.logging',
        'fastapi',
        'pydantic',
        'pydantic_core',
        'pydantic_core._pydantic_core',
        'zeroconf',
        'python_multipart',
    ],
    hookspath=[HOOKSPATH, CONTRIB_HOOKSPATH],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PIL',
        'Pillow',
        'pygments',
        'rich',
        'numpy',
        'pandas',
        'matplotlib',
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
    name='keirstinlink_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,
)
