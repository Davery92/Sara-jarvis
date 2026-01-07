# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Sara Desktop Sidecar

Build with:
    pyinstaller sidecar.spec

This creates a standalone executable that includes:
- All Python dependencies
- The hey_sara.onnx wake word model
"""

import os
import sys
from pathlib import Path

# Get the sidecar directory
sidecar_dir = Path(SPECPATH)
models_dir = sidecar_dir.parent / 'models'

# Collect data files
datas = [
    # Include the wake word model
    (str(models_dir / 'hey_sara.onnx'), 'models'),
]

# Hidden imports needed by the various dependencies
hiddenimports = [
    'openwakeword',
    'openwakeword.model',
    'pynput',
    'pynput.keyboard',
    'pynput.mouse',
    'mss',
    'mss.tools',
    'PIL',
    'PIL.Image',
    'websockets',
    'websockets.client',
    'websockets.server',
    'httpx',
    'numpy',
    'onnxruntime',
]

# Platform-specific hidden imports
if sys.platform == 'win32':
    hiddenimports.extend([
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
    ])
elif sys.platform == 'darwin':
    hiddenimports.extend([
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
    ])
else:
    hiddenimports.extend([
        'pynput.keyboard._xorg',
        'pynput.mouse._xorg',
    ])

a = Analysis(
    ['main.py'],
    pathex=[str(sidecar_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
    ],
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
    name='sidecar',
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
    icon=None,  # Can add an icon here
)
