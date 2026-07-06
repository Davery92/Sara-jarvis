"""Quick standalone test: mic -> wake word detection, bypassing service pipeline."""
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from openwakeword.model import Model
import time

# Find AIRHUG
devices = sd.query_devices()
dev_idx = None
for i, d in enumerate(devices):
    if d["max_input_channels"] > 0 and "airhug" in d["name"].lower():
        dev_idx = i
        print(f"Using: {d['name']} (index {i})")
        break

if dev_idx is None:
    print("AIRHUG not found, trying any mic...")
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            dev_idx = i
            print(f"Using fallback: {d['name']} (index {i})")
            break

if dev_idx is None:
    print("No mic found")
    exit(1)

# Load model
print("Loading wake word model...")
model = Model(inference_framework="onnx")
print(f"Models: {list(model.models.keys())}")

# Record and test
NATIVE_RATE = 48000
TARGET_RATE = 16000
BLOCK = 1024
start = time.time()
chunk_count = [0]

def callback(indata, frames, time_info, status):
    audio = indata[:, 0].copy().astype(np.float32).flatten()
    audio_16k = resample_poly(audio, 1, 3).astype(np.float32)

    # Convert to int16 for OpenWakeWord
    audio_int16 = np.clip(audio_16k * 32767, -32768, 32767).astype(np.int16)

    result = model.predict(audio_int16)

    chunk_count[0] += 1

    # Print scores every ~2 seconds (roughly every 94 chunks at 1024 block / 48kHz)
    if chunk_count[0] % 94 == 0:
        rms = float(np.sqrt(np.mean(audio_16k ** 2) + 1e-10))
        rms_db = 20 * np.log10(max(rms, 1e-10))
        elapsed = time.time() - start
        jarvis = result.get("hey_jarvis", 0)
        alexa = result.get("alexa", 0)
        print(f"[{elapsed:5.1f}s] RMS={rms_db:5.1f}dB  hey_jarvis={jarvis:.4f}  alexa={alexa:.4f}")

    # Check for detection
    for name, score in result.items():
        if score >= 0.3:
            elapsed = time.time() - start
            print(f"\n*** [{elapsed:.1f}s] DETECTED: {name} = {score:.4f} ***\n")

print("Listening for 30 seconds... say 'Hey Jarvis' or 'Alexa'")
dev_info = sd.query_devices(dev_idx)
channels = min(dev_info["max_input_channels"], 2)
with sd.InputStream(device=dev_idx, samplerate=NATIVE_RATE, channels=channels,
                    blocksize=BLOCK, dtype="float32", callback=callback):
    time.sleep(30)

print("Done.")
