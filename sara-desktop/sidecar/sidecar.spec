# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Sara desktop sidecar.
#
# Frozen so a fresh Sara install doesn't need the user to run `pip install`
# against a hand-rolled venv. Everything imported lazily inside command
# handlers must be listed in hiddenimports because PyInstaller's static
# analyzer can't see imports gated behind try/except inside method bodies.

block_cipher = None


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
    hiddenimports=[
        # Local sidecar modules — keep these explicit so a refactor that breaks
        # static analysis doesn't silently miss them.
        'config',
        'activity_monitor',
        'backend_client',
        'electron_bridge',
        'metrics',
        'screenshot',
        # Used at runtime by the desktop actuators (lazy imports in main.py).
        'pyperclip',
        'pygetwindow',
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._win32',
        'pynput.mouse',
        'pynput.mouse._win32',
        # Activity, screenshots, metrics.
        'mss',
        'mss.windows',
        'PIL',
        'PIL.Image',
        'psutil',
        # Network.
        'httpx',
        'websockets',
        'websockets.server',
        'websockets.client',
        'websockets.legacy',
        'websockets.legacy.server',
        'websockets.legacy.client',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # The voice/audio stack was removed in the Phase 0 burn-down. Make
        # sure none of it sneaks back in via transitive imports.
        'sounddevice',
        'pulsectl',
        'pycaw',
        'comtypes',
        'numpy',
    ],
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
