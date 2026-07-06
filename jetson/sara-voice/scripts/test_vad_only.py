"""Diagnose Silero VAD: record speech and check if model produces any output."""
import numpy as np
import sounddevice as sd
import onnxruntime as ort
from scipy.signal import resample_poly
import time

# Record 5 seconds
print("Recording 5 seconds - SPEAK NOW...")
dev_idx = None
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0 and "airhug" in d["name"].lower():
        dev_idx = i
        break

audio_48k = sd.rec(48000 * 5, samplerate=48000, channels=1, device=dev_idx, dtype="float32")
sd.wait()
audio_16k = resample_poly(audio_48k.flatten(), 1, 3).astype(np.float32)
rms = float(np.sqrt(np.mean(audio_16k ** 2)))
print(f"Recorded: {len(audio_16k)} samples, RMS={20*np.log10(max(rms,1e-10)):.1f}dB, max={np.max(np.abs(audio_16k)):.4f}")

# Load VAD
print("\nLoading Silero VAD...")
opts = ort.SessionOptions()
opts.log_severity_level = 3
session = ort.InferenceSession("models/silero_vad.onnx", sess_options=opts, providers=["CPUExecutionProvider"])

# Check model inputs/outputs
print("\nModel inputs:")
for inp in session.get_inputs():
    print(f"  {inp.name}: shape={inp.shape}, type={inp.type}")
print("Model outputs:")
for out in session.get_outputs():
    print(f"  {out.name}: shape={out.shape}, type={out.type}")

# Run inference on 512-sample chunks
print(f"\nRunning VAD on {len(audio_16k)//512} chunks...")
state = np.zeros((2, 1, 128), dtype=np.float32)
sr = np.array(16000, dtype=np.int64)

max_prob = 0
speech_chunks = 0
for i in range(0, len(audio_16k) - 512, 512):
    chunk = audio_16k[i:i+512]
    inp = chunk.reshape(1, -1)

    out, state = session.run(None, {"input": inp, "state": state, "sr": sr})
    prob = float(out[0][0])

    if prob > max_prob:
        max_prob = prob
    if prob >= 0.5:
        speech_chunks += 1

    chunk_rms = float(np.sqrt(np.mean(chunk ** 2)))
    if prob > 0.01 or (i // 512) % 30 == 0:
        t = i / 16000
        print(f"  [{t:5.2f}s] prob={prob:.4f}  rms={20*np.log10(max(chunk_rms,1e-10)):6.1f}dB")

print(f"\nMax probability: {max_prob:.4f}")
print(f"Speech chunks (>=0.5): {speech_chunks}/{len(audio_16k)//512}")

if max_prob < 0.01:
    print("\n>>> VAD NEVER DETECTED SPEECH - model may be wrong")
    print("Trying with int16 conversion...")
    state2 = np.zeros((2, 1, 128), dtype=np.float32)
    audio_int16 = np.clip(audio_16k * 32767, -32768, 32767).astype(np.int16)
    audio_back = audio_int16.astype(np.float32) / 32767.0

    max_prob2 = 0
    for i in range(0, len(audio_back) - 512, 512):
        chunk = audio_back[i:i+512]
        inp = chunk.reshape(1, -1)
        out, state2 = session.run(None, {"input": inp, "state": state2, "sr": sr})
        prob = float(out[0][0])
        if prob > max_prob2:
            max_prob2 = prob
    print(f"  Max probability with int16 roundtrip: {max_prob2:.4f}")

    # Try raw int16 as float
    print("Trying with raw int16 values as float (no normalization)...")
    state3 = np.zeros((2, 1, 128), dtype=np.float32)
    max_prob3 = 0
    for i in range(0, len(audio_int16) - 512, 512):
        chunk = audio_int16[i:i+512].astype(np.float32)  # int16 range: -32768 to 32767
        inp = chunk.reshape(1, -1)
        out, state3 = session.run(None, {"input": inp, "state": state3, "sr": sr})
        prob = float(out[0][0])
        if prob > max_prob3:
            max_prob3 = prob
    print(f"  Max probability with raw int16-as-float: {max_prob3:.4f}")

print("\nDone.")
