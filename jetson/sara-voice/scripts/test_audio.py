#!/usr/bin/env python3
"""Audio device sanity check.

Records 5 seconds from the AIRHUG mic, displays level meters,
and optionally plays back via the desktop bridge.
"""

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np


def list_devices():
    """List all audio input devices."""
    import sounddevice as sd
    print("\n=== Audio Devices ===")
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            marker = " <-- " if "AIRHUG" in dev["name"] or "OBSBOT" in dev["name"] else ""
            print(f"  [{i}] {dev['name']} (in={dev['max_input_channels']}, "
                  f"rate={dev['default_samplerate']:.0f}){marker}")
    print()


def record_test(duration: float = 5.0, device_name: str = "AIRHUG"):
    """Record audio and show level meters."""
    import sounddevice as sd

    print(f"Recording {duration}s from '{device_name}'...")

    # Find device
    devices = sd.query_devices()
    device_idx = None
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0 and device_name.lower() in dev["name"].lower():
            device_idx = i
            break

    if device_idx is None:
        print(f"Device '{device_name}' not found! Available input devices:")
        list_devices()
        return None

    dev_info = sd.query_devices(device_idx)
    print(f"Using device [{device_idx}]: {dev_info['name']}")

    sample_rate = 48000
    channels = min(dev_info["max_input_channels"], 2)
    all_audio = []

    def callback(indata, frames, time_info, status):
        if status:
            print(f"  Status: {status}")
        # Store mono
        mono = indata[:, 0] if indata.ndim > 1 else indata.flatten()
        all_audio.append(mono.copy())

        # Level meter
        rms = np.sqrt(np.mean(mono ** 2) + 1e-10)
        db = 20 * np.log10(max(rms, 1e-10))
        bar_len = max(0, int((db + 60) * 0.8))
        bar = "█" * bar_len
        print(f"\r  Level: {db:6.1f} dB |{bar:<50}|", end="", flush=True)

    with sd.InputStream(
        device=device_idx,
        samplerate=sample_rate,
        channels=channels,
        blocksize=1024,
        dtype="float32",
        callback=callback,
    ):
        time.sleep(duration)

    print()  # Newline after level meter

    if all_audio:
        audio = np.concatenate(all_audio)
        rms = np.sqrt(np.mean(audio ** 2) + 1e-10)
        peak = np.max(np.abs(audio))
        print(f"\nResults:")
        print(f"  Duration: {len(audio) / sample_rate:.2f}s")
        print(f"  Samples: {len(audio)}")
        print(f"  RMS: {20 * np.log10(max(rms, 1e-10)):.1f} dB")
        print(f"  Peak: {20 * np.log10(max(peak, 1e-10)):.1f} dB")
        return audio, sample_rate
    return None


def save_wav(audio: np.ndarray, sample_rate: int, path: str = "test_recording.wav"):
    """Save audio to WAV file."""
    from scipy.io import wavfile
    pcm16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    wavfile.write(path, sample_rate, pcm16)
    print(f"Saved to {path}")


if __name__ == "__main__":
    print("Sara Voice — Audio Test")
    print("=" * 40)

    list_devices()

    device = sys.argv[1] if len(sys.argv) > 1 else "AIRHUG"
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

    result = record_test(duration=duration, device_name=device)
    if result:
        audio, sr = result
        save_wav(audio, sr)
        print("\nAudio test passed!")
    else:
        print("\nAudio test failed!")
        sys.exit(1)
