"""
Sara Voice Agent - Main Entry Point
Complete voice-controlled assistant with system tray
"""
import sys
import logging
from pathlib import Path
import json

# Setup logging
LOG_DIR = Path.home() / ".sara"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "shadow-agent-voice.log"

# Set UTF-8 encoding for console output on Windows
if sys.platform == 'win32':
    import io
    # Force UTF-8 for stdout/stderr BEFORE logging setup
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Import voice components
from audio_session import VoiceAgent, VoiceMode
from system_tray import SystemTrayUI, TRAY_AVAILABLE


def load_config() -> dict:
    """Load configuration from config.json"""
    config_file = Path(__file__).parent.parent / "config.json"

    default_config = {
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

    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
                # Merge with defaults
                default_config.update(user_config)
                logger.info(f"Loaded configuration from {config_file}")
        except Exception as e:
            logger.warning(f"Failed to load config: {e}, using defaults")

    return default_config


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("🎙️  SARA VOICE AGENT")
    logger.info("=" * 60)
    logger.info("")

    # Load configuration
    config = load_config()
    logger.info(f"Backend: {config['backend_url']}")
    logger.info(f"Voice Mode: {config['voice_mode']}")
    logger.info("")

    # Create voice agent
    voice_mode_map = {
        "always_on": VoiceMode.ALWAYS_ON,
        "shadow_only": VoiceMode.SHADOW_ONLY,
        "push_to_talk": VoiceMode.PUSH_TO_TALK
    }
    voice_mode = voice_mode_map.get(config["voice_mode"], VoiceMode.ALWAYS_ON)

    voice_agent = VoiceAgent(
        backend_url=config["backend_url"],
        voice_mode=voice_mode,
        on_transcript=lambda t: logger.info(f"📝 User said: {t}")
    )

    # Start voice agent
    try:
        voice_agent.start()
    except Exception as e:
        logger.error(f"Failed to start voice agent: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Start system tray UI
    if TRAY_AVAILABLE:
        try:
            logger.info("Starting system tray UI...")
            tray = SystemTrayUI(voice_agent)
            tray.run()  # Blocking
        except Exception as e:
            logger.error(f"System tray error: {e}")
            import traceback
            traceback.print_exc()
    else:
        logger.warning("System tray not available")
        logger.info("Voice agent running in console mode")
        logger.info("Press Ctrl+C to stop...")

        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nStopping voice agent...")
            voice_agent.stop()

    logger.info("Voice agent terminated")


if __name__ == "__main__":
    main()
