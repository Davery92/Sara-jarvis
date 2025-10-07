"""
Test Wake Word Detection
Tests the wake word detector with live microphone input

For now, uses "hey mycroft" (pre-trained model)
After you record samples and train "sarah", it will use your custom model
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wake_word import WakeWordDetector
from audio_buffer import PreRollBuffer
from audio_capture import AudioCapture
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    print("=" * 60)
    print("🎤 WAKE WORD DETECTION TEST")
    print("=" * 60)
    print()

    # Initialize components
    logger.info("Initializing wake word detector...")
    wake_detector = WakeWordDetector(
        threshold=0.5,  # Adjust if too sensitive/insensitive
        debounce_seconds=1.5
    )

    logger.info("Initializing pre-roll buffer...")
    pre_roll_buffer = PreRollBuffer(duration_seconds=1.5)

    logger.info("Initializing audio capture...")
    audio_capture = AudioCapture(
        sample_rate=16000,
        blocksize=1280  # 80ms chunks
    )

    # Detection counter
    detection_count = 0

    def audio_callback(audio_chunk):
        """Process each audio chunk"""
        nonlocal detection_count

        # Add to pre-roll buffer
        pre_roll_buffer.add_chunk(audio_chunk)

        # Check for wake word
        detection = wake_detector.process_chunk(audio_chunk)

        if detection:
            detection_count += 1
            print("\n" + "=" * 60)
            print(f"🎉 WAKE WORD DETECTED! (#{detection_count})")
            print(f"   Name: {detection['name']}")
            print(f"   Score: {detection['score']:.2f}")
            print(f"   Timestamp: {detection['timestamp']:.3f}")
            print("=" * 60)

            # Show pre-roll buffer status
            buffer_duration = pre_roll_buffer.get_duration_seconds()
            print(f"📼 Pre-roll buffer: {buffer_duration:.2f}s of audio captured")
            print()

    # Set callback and start
    audio_capture.set_callback(audio_callback)

    print()
    print("=" * 60)
    print("🎤 LISTENING FOR WAKE WORD...")
    print("=" * 60)
    print()

    # Check which model is loaded
    sarah_model = Path(__file__).parent.parent / "models" / "sarah.tflite"
    if sarah_model.exists():
        print("✅ Using custom 'sarah' wake word model")
        print("   Say: 'sarah'")
    else:
        print("ℹ️  Using pre-trained 'hey mycroft' model (sarah not trained yet)")
        print("   Say: 'hey mycroft'")
        print()
        print("   To train your own 'sarah' model:")
        print("   1. Run: python scripts/record_wake_word_windows.py")
        print("   2. Follow training instructions")

    print()
    print("Press Ctrl+C to stop...")
    print("=" * 60)
    print()

    try:
        audio_capture.start()

        # Keep running until interrupted
        import time
        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping...")

    finally:
        audio_capture.stop()

        print()
        print("=" * 60)
        print("📊 SUMMARY")
        print("=" * 60)
        print(f"Total detections: {detection_count}")
        print()


if __name__ == "__main__":
    main()
