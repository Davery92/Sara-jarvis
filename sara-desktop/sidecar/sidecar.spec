# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Sara desktop sidecar.
#
# Frozen so a fresh Sara install doesn't need the user to run `pip install`
# against a hand-rolled venv. Everything imported lazily inside command
# handlers must be listed in hiddenimports because PyInstaller's static
# analyzer can't see imports gated behind try/except inside method bodies.
#
# Run ON the target OS — PyInstaller does not cross-compile. A frozen
# Windows sidecar must be built on Windows, a frozen macOS sidecar on macOS
# (arm64 build on Apple Silicon, x64 on Intel; use --target-arch on macOS
# for a universal2 binary if both are needed).

import sys

block_cipher = None

hiddenimports = [
    # Local sidecar modules — keep these explicit so a refactor that breaks
    # static analysis doesn't silently miss them.
    'config',
    'activity_monitor',
    'backend_client',
    'electron_bridge',
    'metrics',
    'screenshot',
    'focus_tracker',
    'voice',
    'voice.playback',
    'voice.recorder',
    'voice.jetson_client',
    'media_state',
    # Used at runtime by the desktop actuators (lazy imports in main.py).
    'pyperclip',
    'pygetwindow',
    'pynput',
    'pynput.keyboard',
    'pynput.mouse',
    # Activity, screenshots, metrics.
    'mss',
    'PIL',
    'PIL.Image',
    'psutil',
    # Voice module: local TTS playback, mic capture (A3/A6).
    'sounddevice',
    'numpy',
    # Network.
    'httpx',
    'websockets',
    'websockets.server',
    'websockets.client',
    'websockets.legacy',
    'websockets.legacy.server',
    'websockets.legacy.client',
]

if sys.platform == 'win32':
    hiddenimports += [
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        'mss.windows',
        'winsdk',
    ]
elif sys.platform == 'darwin':
    hiddenimports += [
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
        'mss.darwin',
        # macOS permission detection (A8).
        'permissions_macos',
        'Quartz',
        'ApplicationServices',
        'AVFoundation',
        'objc',
    ]
else:
    hiddenimports += [
        'pynput.keyboard._xorg',
        'pynput.mouse._xorg',
        'mss.linux',
    ]

a = Analysis(
    ['main.py'],
    # The sidecar's own modules (config.py, activity_monitor.py, etc.) live in
    # the same directory as main.py. PyInstaller doesn't auto-add the script
    # directory to pathex when invoked with a .spec file, so we add it
    # explicitly. Without this, `from config import config` fails with
    # ModuleNotFoundError at runtime.
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='sidecar',
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
