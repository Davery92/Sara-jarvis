"""
macOS Package Builder for Sara Voice Agent
Uses py2app to create standalone .app bundle
"""
import sys
import subprocess
import shutil
from pathlib import Path
import json
import plistlib

# Paths
PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist" / "macos"
BUILD_DIR = PROJECT_ROOT / "build"
MODELS_DIR = PROJECT_ROOT / "models"

def check_dependencies():
    """Ensure py2app is installed"""
    try:
        import py2app
        print(f"✓ py2app installed")
    except ImportError:
        print("✗ py2app not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "py2app"])
        print("✓ py2app installed")

def create_setup_py():
    """Generate py2app setup.py"""
    setup_content = """from setuptools import setup

APP = ['src/main_voice.py']
DATA_FILES = [
    ('models', ['models/sarah.tflite', 'models/sarah.onnx']),
    ('.', ['config.json.example']),
]

OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'resources/sara_icon.icns' if Path('resources/sara_icon.icns').exists() else None,
    'plist': {
        'CFBundleName': 'Sara Shadow Agent',
        'CFBundleDisplayName': 'Sara Shadow Agent',
        'CFBundleIdentifier': 'com.sara.shadowagent',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,  # No dock icon (menu bar only)
        'NSMicrophoneUsageDescription': 'Sara needs microphone access for voice commands',
        'LSMinimumSystemVersion': '10.13',
    },
    'packages': [
        'openwakeword',
        'sounddevice',
        'numpy',
        'scipy',
        'torch',
        'onnxruntime',
        'websockets',
        'pystray',
        'PIL',
    ],
    'includes': [
        'wave',
        'io',
        'json',
        'logging',
        'threading',
        'asyncio',
    ],
    'excludes': [
        'matplotlib',
        'pandas',
        'pytest',
        'IPython',
        'tkinter',
    ],
    'resources': [],
    'frameworks': [],
}

setup(
    app=APP,
    name='SaraShadowAgent',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
"""

    setup_file = PROJECT_ROOT / "setup.py"
    with open(setup_file, 'w') as f:
        f.write(setup_content)

    print(f"✓ Created setup.py: {setup_file}")
    return setup_file

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

def build_app():
    """Run py2app"""
    print("\n🔨 Building macOS .app bundle...")
    print("This may take several minutes...\n")

    # Clean previous builds
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if (PROJECT_ROOT / "dist" / "SaraShadowAgent.app").exists():
        shutil.rmtree(PROJECT_ROOT / "dist" / "SaraShadowAgent.app")

    # Build
    subprocess.check_call([
        sys.executable,
        "setup.py",
        "py2app",
        "--no-strip",  # Keep debug symbols for troubleshooting
    ])

    print("\n✓ Build complete!")

def create_installer_package():
    """Create final DMG installer (single-file distribution)"""
    print("\n📦 Creating DMG installer...")

    # For non-macOS systems, just copy the .app
    if sys.platform != "darwin":
        print("⚠️  Not on macOS - skipping DMG creation")
        print("   The .app bundle is ready in dist/SaraShadowAgent.app")
        print("   Build the DMG on a macOS machine for distribution")
        return

    app_source = PROJECT_ROOT / "dist" / "SaraShadowAgent.app"
    if not app_source.exists():
        print(f"✗ .app bundle not found at {app_source}")
        return

    # Create temporary directory for DMG contents
    dmg_temp = PROJECT_ROOT / "dmg_temp"
    if dmg_temp.exists():
        shutil.rmtree(dmg_temp)
    dmg_temp.mkdir()

    # Copy .app to temp
    shutil.copytree(app_source, dmg_temp / "SaraShadowAgent.app")

    # Create Applications symlink for drag-and-drop installation
    (dmg_temp / "Applications").symlink_to("/Applications")

    # Create README
    readme_content = """Sara Shadow Agent - Voice Control

Installation:
1. Drag SaraShadowAgent.app to Applications folder
2. Launch from Applications
3. Grant microphone permission when prompted

The agent will appear in your menu bar.
Right-click the icon to change modes and settings.

Say "sarah" to activate voice control!

## Menu Bar Controls

Click the menu bar icon to access:

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
2. Speak your command
3. Wait for Sara's response
4. During response, you can interrupt (barge-in) by speaking

## Auto-Start (Optional)

To launch at login:

1. System Preferences → Users & Groups
2. Click "Login Items"
3. Click "+" and add SaraShadowAgent.app

Or use the built-in setting:
- Right-click menu bar icon → Settings → Auto-start

## Troubleshooting

**Agent won't start:**
- Check Console.app for crash logs
- Ensure microphone permission is granted
- Check Security & Privacy → Microphone

**Wake word not detected:**
- Test microphone in System Preferences → Sound
- Try adjusting threshold in config.json (lower = more sensitive)
- Ensure you have a sarah.tflite model

**No audio output:**
- Check System Preferences → Sound → Output
- Verify backend_url in config.json is correct

**Network/Firewall:**
- Allow outbound connections to backend (default: ws://10.185.1.180:8000)

## Support

Logs location: `~/.sara/shadow-agent-voice.log`

For issues, check Console.app and the log file.
"""

    with open(dmg_temp / "README.txt", 'w') as f:
        f.write(readme_content)

    # Create DMG
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    dmg_path = DIST_DIR / "SaraShadowAgent-Installer.dmg"

    if dmg_path.exists():
        dmg_path.unlink()

    print("   Creating DMG image...")
    subprocess.check_call([
        "hdiutil",
        "create",
        "-volname", "Sara Voice Agent",
        "-srcfolder", str(dmg_temp),
        "-ov",
        "-format", "UDZO",  # Compressed
        str(dmg_path)
    ])

    # Cleanup
    shutil.rmtree(dmg_temp)

    # Show file size
    size_mb = dmg_path.stat().st_size / (1024 * 1024)

    print(f"\n✅ macOS installer complete!")
    print(f"   Single file: {dmg_path}")
    print(f"   Size: {size_mb:.1f} MB")
    print(f"\n   Upload this single DMG file to backend for distribution.")

def main():
    """Main packaging workflow"""
    print("=" * 60)
    print("🎙️  SARA SHADOW AGENT - macOS PACKAGING")
    print("=" * 60)
    print()

    # Check dependencies
    check_dependencies()

    # Create config template
    create_config_template()

    # Create setup.py
    setup_file = create_setup_py()

    # Build .app
    build_app()

    # Create DMG installer (single-file distribution)
    create_installer_package()

    print("\n" + "=" * 60)
    print("✅ PACKAGING COMPLETE!")
    print("=" * 60)

    if sys.platform == "darwin":
        print(f"\nSingle-file installer: {DIST_DIR / 'SaraShadowAgent-Installer.dmg'}")
    else:
        print(f"\n.app bundle: {PROJECT_ROOT / 'dist' / 'SaraShadowAgent.app'}")
        print("   (Build DMG on macOS machine)")

    print("\nNext steps:")
    print("1. Test the installer on a clean macOS machine")
    print("2. Upload to backend: shadow-agent/dist/macos/")
    print("3. Distribute single DMG file to users")
    print("\nNote: For production, consider code signing with Apple Developer account")

if __name__ == "__main__":
    main()
