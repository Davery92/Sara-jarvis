"""
Windows Package Builder for Sara Voice Agent
Uses PyInstaller to create standalone executable
"""
import sys
import subprocess
import shutil
from pathlib import Path
import json

# Paths
PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist" / "windows"
BUILD_DIR = PROJECT_ROOT / "build"
MODELS_DIR = PROJECT_ROOT / "models"

def check_dependencies():
    """Ensure PyInstaller is installed"""
    try:
        import PyInstaller
        print(f"✓ PyInstaller {PyInstaller.__version__} installed")
    except ImportError:
        print("✗ PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller installed")

def create_spec_file():
    """Generate PyInstaller spec file for single-file executable"""
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
        # Include models directory
        ('models', 'models'),
        # Include config template
        ('config.json.example', '.'),
    ] + openwakeword_data,
    hiddenimports=[
        'openwakeword',
        'openwakeword.model',
        'openwakeword.utils',
        'sounddevice',
        'numpy',
        'scipy',
        'torch',
        'onnxruntime',
        'onnxruntime.capi',
        'onnxruntime.capi.onnxruntime_pybind11_state',
        'websockets',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'pyaudio',
        'wave',
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
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Filter out unnecessary files
a.datas = [x for x in a.datas if not x[0].startswith('share/')]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# SINGLE FILE EXECUTABLE
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
    console=True,  # Show console window for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/sara_icon.ico' if Path('resources/sara_icon.ico').exists() else None,
)
"""

    spec_file = PROJECT_ROOT / "sara_voice.spec"
    with open(spec_file, 'w') as f:
        f.write(spec_content)

    print(f"✓ Created spec file: {spec_file}")
    return spec_file

def create_config_template():
    """Create example config file"""
    config_template = {
        "backend_url": "ws://10.185.1.180:8000",
        "voice_mode": "always_on",
        "wake_word": {
            "model_path": None,  # Auto-detect
            "threshold": 0.5,
            "debounce_seconds": 1.5
        },
        "vad": {
            "threshold": 0.5,
            "min_speech_duration_ms": 200,
            "min_silence_duration_ms": 500
        },
        "ui": {
            "show_notifications": True,
            "auto_start": True
        }
    }

    config_file = PROJECT_ROOT / "config.json.example"
    with open(config_file, 'w') as f:
        json.dump(config_template, f, indent=2)

    print(f"✓ Created config template: {config_file}")

def build_executable(spec_file):
    """Run PyInstaller"""
    print("\n🔨 Building Windows executable...")
    print("This may take several minutes...\n")

    subprocess.check_call([
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file)
    ])

    print("\n✓ Build complete!")

def create_installer_package():
    """Create final single-file installer"""
    print("\n📦 Finalizing installer...")

    # Create dist directory
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # Copy single executable to final location
    exe_source = PROJECT_ROOT / "dist" / "SaraShadowAgent.exe"
    exe_final = DIST_DIR / "SaraShadowAgent-Installer.exe"

    if exe_source.exists():
        shutil.copy2(exe_source, exe_final)
        print(f"✓ Single-file installer created: {exe_final}")

        # Show file size
        size_mb = exe_final.stat().st_size / (1024 * 1024)
        print(f"   Size: {size_mb:.1f} MB")
    else:
        print(f"✗ Executable not found at {exe_source}")
        return

    # Create README for users
    readme_content = """# Sara Shadow Agent - Voice Control

## Single-File Installation

This is a standalone executable - no installation required!

## Installation

1. **Download SaraShadowAgent-Installer.exe**

2. **Run the executable**
   - Windows may show a security warning (unsigned app)
   - Click "More info" → "Run anyway"

3. **First Launch**
   - Agent will appear in system tray (microphone icon)
   - Default mode: Always-On (listening for "sarah")
   - Config file auto-created in same directory

4. **Configuration** (Optional)
   - Right-click executable → "Open file location"
   - Edit `config.json` in the same folder
   - Restart agent to apply changes

## System Tray Controls

Right-click the tray icon to access:

- **Status**: Shows current state (Listening, Recording, Processing, Speaking)
- **Voice Mode**:
  - ● Always-On: Always listens for "sarah"
  - ○ Shadow-Only: Only listens during Shadow Mode sessions
  - ○ Push-to-Talk: Manual activation only
- **Test Voice**: Trigger manual listening (Push-to-Talk mode)
- **Settings**: Configuration (coming soon)
- **View Logs**: Open log file
- **Restart Agent**: Reload configuration
- **Quit**: Stop the agent

## Status Icons

- 🟢 Green: Listening for wake word
- 🔴 Red: Recording your voice
- 🟡 Yellow: Processing/thinking
- 🔵 Blue: Speaking (playing response)
- ⚫ Gray: Idle (Shadow-Only mode, no session)

## Usage

1. Say "**sarah**" to activate
2. Speak your command after the beep/tone
3. Wait for Sara's response
4. During response, you can interrupt (barge-in) by speaking

## Auto-Start (Optional)

To run at Windows startup:

1. Press `Win + R`
2. Type: `shell:startup`
3. Copy `SaraShadowAgent.exe` to the Startup folder

## Troubleshooting

**Agent won't start:**
- Check logs: Right-click tray icon → View Logs
- Ensure microphone permissions are granted

**Wake word not detected:**
- Check microphone is working (test in Windows settings)
- Try adjusting threshold in config.json (lower = more sensitive)
- Ensure you have a `sarah.onnx` model in the models/ folder

**No audio output:**
- Check default audio device in Windows
- Verify backend_url in config.json is correct

**Firewall/Network:**
- Allow outbound connections to backend (default: ws://10.185.1.180:8000)

## Support

Logs location: `%USERPROFILE%\.sara\shadow-agent-voice.log`

For issues, check the log file first.
"""

    readme_file = DIST_DIR / "README.txt"
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    print("✓ Created README.txt")

    print(f"\n✅ Windows installer complete!")
    print(f"   Single file: {exe_final}")
    print(f"   Size: {size_mb:.1f} MB")
    print(f"\n   Upload this single file to backend for distribution.")

def main():
    """Main packaging workflow"""
    print("=" * 60)
    print("🎙️  SARA SHADOW AGENT - WINDOWS PACKAGING")
    print("=" * 60)
    print()

    # Check dependencies
    check_dependencies()

    # Create config template
    create_config_template()

    # Create PyInstaller spec
    spec_file = create_spec_file()

    # Build executable
    build_executable(spec_file)

    # Create installer package
    create_installer_package()

    print("\n" + "=" * 60)
    print("✅ PACKAGING COMPLETE!")
    print("=" * 60)
    print(f"\nSingle-file installer: {DIST_DIR / 'SaraShadowAgent-Installer.exe'}")
    print("\nNext steps:")
    print("1. Test the .exe on a clean Windows machine")
    print("2. Upload to backend: shadow-agent/dist/windows/")
    print("3. Distribute single .exe file to users")

if __name__ == "__main__":
    main()
