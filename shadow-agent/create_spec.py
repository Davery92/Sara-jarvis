"""
Create PyInstaller spec file with ONNX support
"""
from pathlib import Path

spec_content = """# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
import os

block_cipher = None

# Find openwakeword models directory
openwakeword_data = []
try:
    import openwakeword
    oww_path = Path(openwakeword.__file__).parent
    resources_path = oww_path / 'resources'
    if resources_path.exists():
        openwakeword_data = [(str(resources_path), 'openwakeword/resources')]
        print(f"Found openwakeword resources at {resources_path}")
except Exception as e:
    print(f"Warning: Could not find openwakeword resources: {e}")

# Collect all voice agent files
a = Analysis(
    ['src/main_voice.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('models', 'models'),
        ('config.json.example', '.'),
    ] + openwakeword_data,
    hiddenimports=[
        'openwakeword',
        'openwakeword.model',
        'openwakeword.utils',
        'sounddevice',
        'numpy',
        'scipy',
        'onnxruntime',
        'onnxruntime.capi',
        'onnxruntime.capi.onnxruntime_pybind11_state',
        'websockets',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'wave',
        'webrtcvad',
        'io',
        'encodings.utf_8',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'pandas',
        'pytest',
        'IPython',
        'torch',
        'torchaudio',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.datas = [x for x in a.datas if not x[0].startswith('share/')]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SaraShadowAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""

with open('sara_voice_fixed.spec', 'w', encoding='utf-8') as f:
    f.write(spec_content)

print('✓ Spec file created: sara_voice_fixed.spec')
