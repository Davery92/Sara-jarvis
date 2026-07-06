"""Test wake word + VAD pipeline only. No STT, no backend, no recording."""
import numpy as np
import sounddevice as sd
import torch
from scipy.signal import resample_poly
from openwakeword.model import Model as WakeModel
import time
import sys

NATIVE_RATE = 48000
TARGET_RATE = 16000
BLOCK = 1024

# Find AIRHUG
dev_idx = None
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0 and "airhug" in d["name"].lower():
        dev_idx = i
        break
if dev_idx is None:
    print("No AIRHUG mic found")
    sys.exit(1)

print("Loading wake word model...")
wake = WakeModel(inference_framework="onnx")

print("Loading Silero VAD (PyTorch)...")
vad_model, _ = torch.hub.load("snakers4/silero-vad", "silero_vad", onnx=False, trust_repo=True)
vad_model.eval()

state = "IDLE"
wake_time = 0
speech_start = None
last_speech = None
chunk_n = [0]
start = time.time()
vad_buffer = np.array([], dtype=np.float32)  # accumulate across callbacks

print("\n=== Say 'Hey Jarvis', then talk. 60 seconds. ===\n")

def cb(indata, frames, time_info, status):
    global state, wake_time, speech_start, last_speech, vad_buffer

    audio = indata[:, 0].copy().astype(np.float32).flatten()
    audio_16k = resample_poly(audio, 1, 3).astype(np.float32)
    t = time.time() - start
    chunk_n[0] += 1
    rms = float(np.sqrt(np.mean(audio_16k ** 2) + 1e-10))
    rms_db = 20 * np.log10(max(rms, 1e-10))

    if state == "IDLE":
        audio_int16 = np.clip(audio_16k * 32767, -32768, 32767).astype(np.int16)
        result = wake.predict(audio_int16)
        jarvis = result.get("hey_jarvis", 0)
        if chunk_n[0] % 47 == 0:
            print(f"[{t:5.1f}s] IDLE  rms={rms_db:5.1f}dB  jarvis={jarvis:.3f}")
        if jarvis >= 0.5:
            print(f"\n*** WAKE ({jarvis:.3f}) — listening now, talk! ***\n")
            state = "LISTEN"
            wake_time = time.time()
            speech_start = None
            last_speech = None
            vad_buffer = np.array([], dtype=np.float32)
            vad_model.reset_states()

    elif state == "LISTEN":
        # Accumulate audio for 512-sample chunks
        vad_buffer = np.concatenate([vad_buffer, audio_16k])
        max_p = 0.0
        while len(vad_buffer) >= 512:
            chunk = vad_buffer[:512]
            vad_buffer = vad_buffer[512:]
            p = vad_model(torch.from_numpy(chunk), TARGET_RATE).item()
            if p > max_p:
                max_p = p

            if p >= 0.5:
                if speech_start is None:
                    speech_start = time.time()
                    print(f"[{t:5.1f}s] >> SPEECH START (p={p:.3f})")
                last_speech = time.time()
            elif speech_start is not None:
                gap = (time.time() - last_speech) * 1000
                if gap >= 500:
                    dur = (last_speech - speech_start) * 1000
                    print(f"[{t:5.1f}s] << SPEECH END ({dur:.0f}ms)")
                    speech_start = None
                    state = "IDLE"
                    vad_model.reset_states()
                    print(f"\nBack to IDLE. Say 'Hey Jarvis' again.\n")
                    return

        if chunk_n[0] % 23 == 0:
            s = "SPEECH" if speech_start else "waiting"
            elapsed = time.time() - wake_time
            print(f"[{t:5.1f}s] LISTEN rms={rms_db:5.1f}dB  vad={max_p:.3f}  [{s}] {elapsed:.0f}s")

        if time.time() - wake_time > 15:
            print(f"[{t:5.1f}s] Timeout. Back to IDLE.\n")
            state = "IDLE"

dev_info = sd.query_devices(dev_idx)
ch = min(dev_info["max_input_channels"], 2)
with sd.InputStream(device=dev_idx, samplerate=NATIVE_RATE, channels=ch,
                    blocksize=BLOCK, dtype="float32", callback=cb):
    try:
        end = start + 60
        while time.time() < end:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

print("Done.")
