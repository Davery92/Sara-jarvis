"""Full pipeline test: mic -> wake word -> VAD -> STT.
Shows live scores for wake word and VAD so we can diagnose issues.
"""
import numpy as np
import sounddevice as sd
import onnxruntime as ort
from scipy.signal import resample_poly
from openwakeword.model import Model as WakeModel
import time
import sys

# --- Setup ---
NATIVE_RATE = 48000
TARGET_RATE = 16000
BLOCK = 1024

# Find AIRHUG
devices = sd.query_devices()
dev_idx = None
for i, d in enumerate(devices):
    if d["max_input_channels"] > 0 and "airhug" in d["name"].lower():
        dev_idx = i
        break
if dev_idx is None:
    print("AIRHUG not found")
    sys.exit(1)
print(f"Mic: {devices[dev_idx]['name']}")

# Load wake word
print("Loading wake word model...")
wake_model = WakeModel(inference_framework="onnx")
print(f"Wake words: {list(wake_model.models.keys())}")

# Load Silero VAD
print("Loading Silero VAD...")
vad_opts = ort.SessionOptions()
vad_opts.inter_op_num_threads = 1
vad_opts.intra_op_num_threads = 1
vad_opts.log_severity_level = 3
vad_session = ort.InferenceSession(
    "models/silero_vad.onnx",
    sess_options=vad_opts,
    providers=["CPUExecutionProvider"],
)
vad_state = np.zeros((2, 1, 128), dtype=np.float32)

def vad_predict(audio_chunk):
    global vad_state
    inp = audio_chunk.reshape(1, -1).astype(np.float32)
    sr = np.array(TARGET_RATE, dtype=np.int64)
    out, vad_state = vad_session.run(None, {"input": inp, "state": vad_state, "sr": sr})
    return float(out[0][0])

# --- State ---
state = "IDLE"  # IDLE -> LISTENING
wake_triggered_at = 0
vad_speech_start = None
vad_last_speech = None
vad_audio_chunks = []
chunk_count = [0]
start_time = time.time()

print("\n=== READY === Say 'Hey Jarvis' then ask a question. 60 second test.\n")

def callback(indata, frames, time_info, status):
    global state, wake_triggered_at, vad_speech_start, vad_last_speech, vad_audio_chunks, vad_state

    audio = indata[:, 0].copy().astype(np.float32).flatten()
    audio_16k = resample_poly(audio, 1, 3).astype(np.float32)
    elapsed = time.time() - start_time
    chunk_count[0] += 1

    rms = float(np.sqrt(np.mean(audio_16k ** 2) + 1e-10))
    rms_db = 20 * np.log10(max(rms, 1e-10))

    if state == "IDLE":
        # Wake word detection (needs int16)
        audio_int16 = np.clip(audio_16k * 32767, -32768, 32767).astype(np.int16)
        result = wake_model.predict(audio_int16)
        jarvis = result.get("hey_jarvis", 0)

        if chunk_count[0] % 47 == 0:  # ~1s
            print(f"[{elapsed:5.1f}s] IDLE  rms={rms_db:5.1f}dB  jarvis={jarvis:.4f}")

        if jarvis >= 0.5:
            print(f"\n*** WAKE WORD DETECTED (jarvis={jarvis:.4f}) ***")
            print(">>> Now listening for speech... talk now!\n")
            state = "LISTENING"
            wake_triggered_at = time.time()
            vad_speech_start = None
            vad_last_speech = None
            vad_audio_chunks = []
            # Reset VAD state
            vad_state = np.zeros((2, 1, 128), dtype=np.float32)

    elif state == "LISTENING":
        # VAD detection (needs float32)
        # Process in 512-sample chunks
        buf = audio_16k
        max_prob = 0.0
        while len(buf) >= 512:
            chunk = buf[:512]
            buf = buf[512:]
            prob = vad_predict(chunk)
            max_prob = max(max_prob, prob)

            if prob >= 0.5:
                if vad_speech_start is None:
                    vad_speech_start = time.time()
                    print(f"[{elapsed:5.1f}s] SPEECH STARTED (prob={prob:.3f})")
                vad_last_speech = time.time()
                vad_audio_chunks.append(chunk.copy())
            elif vad_speech_start is not None:
                vad_audio_chunks.append(chunk.copy())
                silence_ms = (time.time() - vad_last_speech) * 1000
                if silence_ms >= 500:
                    duration_ms = (vad_last_speech - vad_speech_start) * 1000
                    if duration_ms >= 250:
                        print(f"[{elapsed:5.1f}s] SPEECH ENDED (duration={duration_ms:.0f}ms, silence={silence_ms:.0f}ms)")
                        print(f"  Captured {len(vad_audio_chunks)} chunks = {len(vad_audio_chunks)*512/TARGET_RATE:.1f}s audio")
                        state = "DONE"
                    else:
                        print(f"[{elapsed:5.1f}s] Speech too short ({duration_ms:.0f}ms), resetting")
                        vad_speech_start = None
                        vad_audio_chunks = []

        if chunk_count[0] % 23 == 0:  # ~0.5s
            listen_time = time.time() - wake_triggered_at
            speech_str = "speaking" if vad_speech_start else "waiting"
            print(f"[{elapsed:5.1f}s] LISTEN rms={rms_db:5.1f}dB  vad={max_prob:.3f}  ({speech_str}, {listen_time:.0f}s)")

        if time.time() - wake_triggered_at > 15:
            print(f"\n[{elapsed:5.1f}s] Listen timeout (15s)")
            state = "IDLE"
            print("Back to IDLE, say Hey Jarvis again...\n")

dev_info = sd.query_devices(dev_idx)
channels = min(dev_info["max_input_channels"], 2)
with sd.InputStream(device=dev_idx, samplerate=NATIVE_RATE, channels=channels,
                    blocksize=BLOCK, dtype="float32", callback=callback):
    try:
        while time.time() - start_time < 60:
            time.sleep(0.1)
            if state == "DONE":
                print("\nPipeline test PASSED - full wake word + VAD cycle completed!")
                break
    except KeyboardInterrupt:
        pass

print("Test finished.")
