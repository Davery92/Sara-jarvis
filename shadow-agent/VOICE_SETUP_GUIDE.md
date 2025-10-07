# 🎙️ Sara Voice Control Setup Guide

Complete guide for setting up voice control with custom "sarah" wake word detection.

---

## 📋 Prerequisites

- **Windows 10/11** (macOS/Linux instructions coming soon)
- **Python 3.8+** installed
- **Working microphone** (USB or built-in)
- **Internet connection** (for downloading models and TTS)

---

## 🚀 Quick Start (Windows)

### Step 1: Install Dependencies

Open Command Prompt or PowerShell in the `shadow-agent` directory:

```cmd
cd C:\path\to\jarvis\shadow-agent
scripts\setup_voice_windows.bat
```

This will:
- ✅ Install all required Python packages
- ✅ Download pre-trained wake word models
- ✅ Test your microphone

**Expected output:**
```
[1/5] Python found
[2/5] Working directory: C:\...\shadow-agent
[3/5] Installing voice control dependencies...
[4/5] Downloading openWakeWord models...
[5/5] Testing your microphone...
SETUP COMPLETE!
```

---

### Step 2: Test Wake Word Detection (Optional)

Test with the pre-trained "hey mycroft" model:

```cmd
python scripts\test_wake_word.py
```

Say **"hey mycroft"** and you should see:

```
🎉 WAKE WORD DETECTED! (#1)
   Name: hey_mycroft
   Score: 0.87
   Timestamp: 1234567890.123
```

Press `Ctrl+C` to stop.

---

### Step 3: Record Your Voice Saying "Sarah"

This is the most important step! Record yourself saying "sarah" 100 times:

```cmd
python scripts\record_wake_word_windows.py
```

**What it does:**
- Records 100 samples of you saying "sarah"
- Each sample is 2 seconds long
- Saves to `training_data/positive/`

**Tips for best results:**
- ✅ Vary your tone (happy, tired, excited, normal)
- ✅ Vary your speed (fast, slow, normal)
- ✅ Try different emphasis ("SAH-rah" vs "sah-RAH")
- ✅ Record in different locations (desk, across room)
- ✅ Some background noise is okay (TV, music, fan)

**Progress:**
```
📝 Sample 1/100
💡 Tips:
   • Say 'sarah' clearly and naturally
   • Try different tones and speeds

   Starting in 3...
   🔴 RECORDING NOW - Say 'SARAH!'
   ✅ Recorded! Volume: 25.3
   💾 Saved: sarah_001.wav
   📊 Progress: 1/100 (1.0%)
```

You can pause anytime with `Ctrl+C` and resume later.

---

### Step 4: Generate Negative Samples

Generate synthetic samples of similar-sounding words (to reduce false positives):

```cmd
python scripts\generate_negative_samples.py
```

**What it does:**
- Uses Sara's TTS to generate ~80 negative samples
- Words like "sorry", "seriously", "search", etc.
- Saves to `training_data/negative/`

**Expected output:**
```
[1/80] Generating 'sorry'... ✅
[2/80] Generating 'seriously'... ✅
...
✅ GENERATION COMPLETE!
Success: 80
```

---

### Step 5: Train Your Custom "Sarah" Model

Now the exciting part - train your model!

#### Option A: Google Colab (Recommended - Free GPU)

1. **Open the training notebook:**
   - Go to: https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb
   - Click "Open in Colab"

2. **Upload your training data:**
   ```python
   # In Colab, upload your folders:
   training_data/
   ├── positive/  (your 100 "sarah" recordings)
   └── negative/  (80 synthetic samples)
   ```

3. **Configure training:**
   ```python
   WAKE_WORD_NAME = "sarah"
   POSITIVE_DIR = "/content/training_data/positive/"
   NEGATIVE_DIR = "/content/training_data/negative/"
   EPOCHS = 30
   BATCH_SIZE = 32
   ```

4. **Run all cells** (takes ~30-60 minutes on Colab GPU)

5. **Download `sarah.tflite`** when complete

#### Option B: Local Training (Advanced)

If you have a GPU locally:

```cmd
pip install tensorflow
cd training
python train_sarah_model.py
```

---

### Step 6: Install Your Trained Model

1. **Create models directory:**
   ```cmd
   mkdir shadow-agent\models
   ```

2. **Copy your trained model:**
   ```cmd
   copy sarah.tflite shadow-agent\models\sarah.tflite
   ```

---

### Step 7: Test Your Custom "Sarah" Wake Word!

```cmd
python scripts\test_wake_word.py
```

Now say **"sarah"** and it should detect it!

```
✅ Using custom 'sarah' wake word model
   Say: 'sarah'

🎉 WAKE WORD DETECTED! (#1)
   Name: sarah
   Score: 0.92
```

---

## 🎯 Tuning and Troubleshooting

### Wake Word Not Detecting

**Too insensitive?** Lower the threshold:

Edit `scripts/test_wake_word.py`:
```python
wake_detector = WakeWordDetector(
    threshold=0.3,  # Lower = more sensitive (was 0.5)
)
```

### Too Many False Positives

**Too sensitive?** Raise the threshold:

```python
wake_detector = WakeWordDetector(
    threshold=0.7,  # Higher = less sensitive (was 0.5)
)
```

### Microphone Issues

**Test your microphone:**

```cmd
python -c "from src.audio_capture import AudioCapture; AudioCapture().test_microphone()"
```

**List available devices:**

```cmd
python -c "import sounddevice as sd; print(sd.query_devices())"
```

**Select specific device:**

Edit code to specify device index:
```python
audio_capture = AudioCapture(device=1)  # Use device 1
```

### Low Quality Detection

**Train more samples!**

The model improves with more data:
- 50 samples: Basic (works but has errors)
- 100 samples: Good (recommended minimum)
- 200+ samples: Excellent (professional quality)

Run the recording script again to add more samples:
```cmd
python scripts\record_wake_word_windows.py
```

---

## 📊 Training Data Checklist

Before training, verify you have:

- ✅ **100+ positive samples** (your voice saying "sarah")
  - Location: `training_data/positive/*.wav`
  - Check: `dir training_data\positive` should show 100+ files

- ✅ **80+ negative samples** (similar words)
  - Location: `training_data/negative/*.wav`
  - Check: `dir training_data\negative` should show 80+ files

- ✅ **Sample quality**
  - Listen to a few samples - clear audio?
  - No silent files? (delete if found)
  - Reasonable volume? (not clipping, not too quiet)

---

## 🔧 Advanced Configuration

### Adjust Recording Duration

Edit `scripts/record_wake_word_windows.py`:
```python
DURATION = 1.5  # Shorter recordings (was 2.0)
NUM_SAMPLES = 150  # Record more samples (was 100)
```

### Add More Negative Samples

Edit `scripts/generate_negative_samples.py`:
```python
NEGATIVE_WORDS = [
    # Add your own words here
    "seriously", "sorry", "send",
    # ...
]
```

### Custom Voice for Negatives

If your TTS supports different voices:
```python
response = requests.post(TTS_URL, json={
    "input": text,
    "voice": "alloy",  # Try: alloy, echo, fable, onyx, nova, shimmer
})
```

---

## 📁 File Structure

```
shadow-agent/
├── scripts/
│   ├── setup_voice_windows.bat          # Install dependencies
│   ├── record_wake_word_windows.py      # Record your voice
│   ├── generate_negative_samples.py     # Generate negatives
│   └── test_wake_word.py                # Test detection
├── src/
│   ├── wake_word.py                     # Wake word detector
│   ├── audio_buffer.py                  # Pre-roll buffer
│   └── audio_capture.py                 # Microphone input
├── models/
│   └── sarah.tflite                     # Your trained model (after training)
├── training_data/
│   ├── positive/                        # Your "sarah" recordings
│   └── negative/                        # Synthetic negative samples
└── requirements-voice.txt               # Python dependencies
```

---

## 🎓 Understanding the Training Process

### What is openWakeWord?

openWakeWord is an open-source wake word detector that:
- ✅ Runs 100% locally (no cloud)
- ✅ Uses machine learning (neural network)
- ✅ Trains on synthetic speech (TTS-generated)
- ✅ Works on modest hardware (Raspberry Pi 3+)

### How Training Works

1. **Positive samples** - Examples of the wake word ("sarah")
   - Your voice recordings
   - Model learns what "sarah" sounds like in your voice

2. **Negative samples** - Everything that's NOT the wake word
   - Similar words: "sorry", "seriously"
   - Random words: "hello", "help", "computer"
   - Model learns what to ignore

3. **Training** - Model learns to distinguish
   - Neural network adjusts weights
   - Optimizes for: low false positives + low false negatives

4. **Result** - A tiny .tflite model (~1MB)
   - Fast inference (runs 100x per second)
   - Accurate detection (>95% true positive, <2% false positive)

### Model Metrics

Good model performance:
- **True Positive Rate**: >95% (detects "sarah" when you say it)
- **False Positive Rate**: <2% (<1 per hour of ambient noise)
- **Latency**: <100ms (responds quickly)
- **CPU Usage**: <2% (doesn't drain battery)

---

## 🐛 Common Issues

### "ModuleNotFoundError: No module named 'openwakeword'"

**Fix:**
```cmd
pip install openwakeword
```

### "Audio device not found" or "Microphone permission denied"

**Windows Fix:**
1. Open Windows Settings → Privacy → Microphone
2. Enable "Allow apps to access your microphone"
3. Restart your terminal

### "TTS service not responding"

**Check TTS service:**
```cmd
curl http://10.185.1.8:9000
```

If it fails:
- Make sure TTS service is running
- Check network connectivity
- Update TTS URL in `scripts/generate_negative_samples.py`

### Recording is silent / very quiet

**Check microphone level:**
1. Right-click speaker icon → Sounds
2. Recording tab → Select microphone
3. Properties → Levels
4. Set to 80-100%

---

## 🎉 Next Steps

After successfully detecting "sarah":

1. **Integrate with Shadow Agent** (coming next)
   - Wake word → Start listening
   - VAD → Detect speech
   - STT → Transcribe
   - Sara → Respond

2. **Add Multi-Device Support**
   - Wake word on all agents
   - Device arbitration
   - Handoff between devices

3. **Fine-tune Performance**
   - Adjust threshold based on usage
   - Re-train with more samples
   - Test in different environments

---

## 📞 Support

Issues? Questions?

1. Check this guide thoroughly
2. Review error messages carefully
3. Test each step individually
4. Check Python/package versions

Common resources:
- openWakeWord docs: https://github.com/dscripka/openWakeWord
- sounddevice docs: https://python-sounddevice.readthedocs.io/

---

**Ready to record?** Run:
```cmd
python scripts\record_wake_word_windows.py
```

Good luck! 🎙️
