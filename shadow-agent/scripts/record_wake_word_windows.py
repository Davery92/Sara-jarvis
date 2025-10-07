"""
Wake Word Recording Script for Windows
Record multiple samples of "sarah" for training custom wake word model

Usage:
    python record_wake_word_windows.py

This will record 100 samples of you saying "sarah" with natural variation.
Each sample is ~2 seconds long.
"""
import sounddevice as sd
import numpy as np
import wave
import os
from pathlib import Path
import time
import sys

# Configuration
SAMPLE_RATE = 16000  # 16kHz required for openWakeWord
DURATION = 2.0  # seconds per sample
NUM_SAMPLES = 10  # Number of recordings to collect (adjust as needed: 10=quick, 50=good, 100=excellent)
OUTPUT_DIR = Path(__file__).parent.parent / "training_data" / "positive"
COUNTDOWN_SECONDS = 2


def create_output_directory():
    """Create output directory for recordings"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✅ Output directory: {OUTPUT_DIR}")
    return OUTPUT_DIR


def test_microphone():
    """Test microphone and show volume levels"""
    print("\n🎤 Testing microphone...")
    print("Speak now to test your microphone!")
    print("=" * 60)

    volumes = []

    def callback(indata, frames, time, status):
        if status:
            print(f"Status: {status}")
        volume_norm = np.linalg.norm(indata) * 10
        volumes.append(volume_norm)
        bars = int(volume_norm)
        meter = "█" * min(bars, 50)
        print(f"\rVolume: {meter:<50}", end="", flush=True)

    with sd.InputStream(callback=callback, channels=1, samplerate=SAMPLE_RATE):
        time.sleep(3)

    print("\n" + "=" * 60)

    if volumes:
        avg_volume = np.mean(volumes)
        if avg_volume < 1:
            print("⚠️  WARNING: Volume very low! Check microphone settings.")
            response = input("Continue anyway? (y/N): ")
            if response.lower() != 'y':
                sys.exit(1)
        else:
            print(f"✅ Microphone working! Average volume: {avg_volume:.1f}")
    else:
        print("❌ ERROR: No audio detected. Check microphone permissions.")
        sys.exit(1)


def record_sample(sample_num: int, total: int) -> np.ndarray:
    """
    Record a single sample with countdown

    Args:
        sample_num: Current sample number (1-indexed)
        total: Total number of samples to record

    Returns:
        Recorded audio as numpy array
    """
    print(f"\n{'=' * 60}")
    print(f"📝 Sample {sample_num}/{total}")
    print(f"{'=' * 60}")

    # Instructions
    print("\n💡 Tips:")
    print("   • Say 'sarah' clearly and naturally")
    print("   • Try different tones and speeds")
    print("   • Variations help the model learn better")
    print()

    # Countdown
    for i in range(COUNTDOWN_SECONDS, 0, -1):
        print(f"   Starting in {i}...", end="\r", flush=True)
        time.sleep(1)

    print("   🔴 RECORDING NOW - Say 'SARAH'!" + " " * 20)

    # Record audio
    recording = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='int16'
    )
    sd.wait()

    # Show volume
    volume = np.linalg.norm(recording)
    print(f"   ✅ Recorded! Volume: {volume/1000:.1f}")

    return recording


def save_wav(audio: np.ndarray, filepath: Path):
    """Save audio as WAV file"""
    with wave.open(str(filepath), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())


def main():
    """Main recording loop"""
    print("=" * 60)
    print("🎙️  SARAH WAKE WORD RECORDER")
    print("=" * 60)
    print()
    print(f"This script will record you saying 'sarah' {NUM_SAMPLES} times.")
    print("Each recording is 2 seconds long.")
    print()
    print(f"NOTE: You're recording {NUM_SAMPLES} samples (quick test mode).")
    print("      For better accuracy, increase NUM_SAMPLES in the script to 50-100.")
    print()
    print("Tips for good training data:")
    print("  ✓ Vary your tone (normal, excited, tired)")
    print("  ✓ Vary your speed (fast, slow, normal)")
    print("  ✓ Try different emphasis ('SAH-rah' vs 'sah-RAH')")
    print("  ✓ Record in different locations (desk, across room)")
    print("  ✓ Some background noise is okay (TV, music)")
    print()
    print("You can pause anytime by pressing Ctrl+C")
    print()

    input("Press ENTER to start recording...")

    # Test microphone first
    test_microphone()

    # Create output directory
    output_dir = create_output_directory()

    # Main recording loop
    recorded_count = 0
    try:
        for i in range(1, NUM_SAMPLES + 1):
            # Record sample
            audio = record_sample(i, NUM_SAMPLES)

            # Save to file
            filename = f"sarah_{i:03d}.wav"
            filepath = output_dir / filename
            save_wav(audio, filepath)

            recorded_count += 1

            # Progress
            progress = (recorded_count / NUM_SAMPLES) * 100
            print(f"   💾 Saved: {filename}")
            print(f"   📊 Progress: {recorded_count}/{NUM_SAMPLES} ({progress:.1f}%)")

            # Break suggestion (only if recording many samples)
            if NUM_SAMPLES >= 20 and i % 20 == 0 and i < NUM_SAMPLES:
                print(f"\n{'=' * 60}")
                print(f"🎉 Great job! {recorded_count} samples recorded so far.")
                print(f"💡 Consider taking a short break to rest your voice.")
                print(f"{'=' * 60}")
                response = input("\nPress ENTER to continue (or Ctrl+C to stop)...")

    except KeyboardInterrupt:
        print(f"\n\n⏸️  Recording paused at {recorded_count} samples.")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"✅ RECORDING COMPLETE!")
    print(f"{'=' * 60}")
    print(f"📁 Recorded {recorded_count} samples")
    print(f"📂 Location: {output_dir}")
    print()

    if recorded_count >= 50:
        print("🎉 You have enough samples to train a good model!")
        print()
        print("Next steps:")
        print("  1. Review recordings (delete any bad ones)")
        print("  2. Generate negative samples (other words, noise)")
        print("  3. Train model using Google Colab notebook")
    elif recorded_count >= 10:
        print("⚠️  You have some samples - enough for basic testing!")
        print(f"   You recorded {recorded_count} samples.")
        print(f"   For better accuracy, aim for 50-100 samples.")
        print()
        print("Next steps:")
        print("  1. Generate negative samples")
        print("  2. Train model (may have lower accuracy with few samples)")
        print("  3. Test and record more samples if needed")
    else:
        print("⚠️  Not enough samples for training.")
        print(f"   You need at least 10 samples (you have {recorded_count})")

    print()
    print(f"Run this script again to record more samples.")
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress ENTER to exit...")
