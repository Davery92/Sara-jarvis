"""
Generate Negative Training Samples
Creates samples of words that sound similar to "sarah" but aren't the wake word
Uses Sara's TTS endpoint to generate synthetic negative samples
"""
import requests
import wave
import io
import numpy as np
from pathlib import Path
import time

# Configuration
TTS_URL = "http://10.185.1.8:9000/v1/audio/speech"
OUTPUT_DIR = Path(__file__).parent.parent / "training_data" / "negative"
SAMPLE_RATE = 16000

# Similar sounding words and phrases to "sarah" (false positive candidates)
NEGATIVE_WORDS = [
    # Single words that sound similar
    "sorry", "sari", "sara", "sahara", "sorrow", "serene", "serum",
    "serious", "syria", "sierra", "siren", "syrup", "sovereign",
    "several", "therapy", "various", "area", "fair", "chair",
    "search", "send", "said", "save", "sale", "same",

    # Common phrases that might trigger false positives
    "seriously though", "sorry about that", "send it over",
    "search for it", "several times", "that's fair",
    "over there", "anywhere", "somewhere", "compare",

    # Random common words (general negative samples)
    "hello", "thank you", "please", "okay", "yes", "no",
    "what", "where", "when", "how", "why", "who",
    "computer", "assistant", "help", "stop", "continue",
    "music", "volume", "lights", "temperature", "weather",

    # Longer phrases (background conversation)
    "can you help me with this", "what time is it",
    "I need to finish this work", "let me check that",
    "that sounds good to me", "I don't think so",
    "maybe we should try", "I'll get back to you"
]


def generate_tts_sample(text: str, output_path: Path) -> bool:
    """
    Generate a single TTS sample

    Args:
        text: Text to synthesize
        output_path: Where to save the WAV file

    Returns:
        True if successful, False otherwise
    """
    try:
        # Request TTS
        response = requests.post(
            TTS_URL,
            json={
                "input": text,
                "voice": "alloy",  # Or whatever voice your TTS supports
                "response_format": "wav"
            },
            timeout=10
        )

        if response.status_code != 200:
            print(f"❌ TTS failed for '{text}': {response.status_code}")
            return False

        # Save WAV file
        with open(output_path, 'wb') as f:
            f.write(response.content)

        return True

    except Exception as e:
        print(f"❌ Error generating '{text}': {e}")
        return False


def main():
    print("=" * 60)
    print("🎙️  NEGATIVE SAMPLE GENERATOR")
    print("=" * 60)
    print()
    print(f"Generating {len(NEGATIVE_WORDS)} negative samples...")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Test TTS connection
    print("Testing TTS connection...")
    test_response = requests.get("http://10.185.1.8:9000", timeout=5)
    if test_response.status_code >= 500:
        print("❌ TTS service not responding!")
        print("   Make sure TTS is running at http://10.185.1.8:9000")
        return
    print("✅ TTS service connected")
    print()

    # Generate samples
    success_count = 0
    fail_count = 0

    for i, word in enumerate(NEGATIVE_WORDS, 1):
        # Progress
        print(f"[{i}/{len(NEGATIVE_WORDS)}] Generating '{word}'...", end=" ", flush=True)

        # Generate filename
        safe_filename = word.replace(" ", "_").replace("'", "")[:30]
        output_path = OUTPUT_DIR / f"neg_{i:03d}_{safe_filename}.wav"

        # Generate TTS
        if generate_tts_sample(word, output_path):
            print(f"✅")
            success_count += 1
        else:
            print(f"❌")
            fail_count += 1

        # Rate limit (be nice to the TTS service)
        time.sleep(0.2)

    # Summary
    print()
    print("=" * 60)
    print("✅ GENERATION COMPLETE!")
    print("=" * 60)
    print(f"Success: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Total: {len(NEGATIVE_WORDS)}")
    print()
    print(f"📂 Samples saved to: {OUTPUT_DIR}")
    print()

    # Check if we have enough samples
    positive_dir = OUTPUT_DIR.parent / "positive"
    if positive_dir.exists():
        positive_count = len(list(positive_dir.glob("*.wav")))
        print(f"📊 Training data status:")
        print(f"   Positive samples (your voice): {positive_count}")
        print(f"   Negative samples (synthetic): {success_count}")
        print()

        if positive_count >= 50 and success_count >= 50:
            print("🎉 You have enough samples to train a model!")
            print()
            print("Next steps:")
            print("  1. Review samples (delete any corrupted files)")
            print("  2. Use openWakeWord training notebook:")
            print("     https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb")
            print("  3. Upload to Google Colab and train")
            print("  4. Download sarah.tflite and place in shadow-agent/models/")
        elif positive_count < 50:
            print(f"⚠️  Need more positive samples (you have {positive_count}, need 50+)")
            print("   Run: python scripts/record_wake_word_windows.py")
    else:
        print("⚠️  No positive samples found!")
        print("   Run: python scripts/record_wake_word_windows.py")

    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
