# 🎙️ Sara Voice Control - Quick Start

## For David (Windows)

### Step 1: Setup (5 minutes)

Double-click: **`START_HERE.bat`**

Choose option `[1] Setup voice control`

This installs all dependencies and tests your microphone.

---

### Step 2: Record Your Voice (~2 minutes)

Double-click: **`RECORD_SARAH.bat`**

**What to do:**
- Say "sarah" when prompted (10 times - quick test mode)
- Vary your tone, speed, and emphasis

**Output:**
- Creates `training_data/positive/` with 10 WAV files
- Each file is you saying "sarah"

**Note:** 10 samples is enough for basic testing. For better accuracy:
- Edit `scripts/record_wake_word_windows.py`
- Change `NUM_SAMPLES = 10` to `NUM_SAMPLES = 50` or higher
- Run again to record more samples

---

### Step 3: Generate Negatives (2 minutes)

Double-click: **`GENERATE_NEGATIVES.bat`**

**What it does:**
- Uses Sara's TTS to generate 80 negative samples
- Words like "sorry", "seriously", "search", etc.
- Prevents false positives

**Output:**
- Creates `training_data/negative/` with 80 WAV files

---

### Step 4: Train Model (30-60 minutes)

**Using Google Colab (Recommended - Free GPU):**

1. Go to: https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb

2. Click "Open in Colab"

3. Upload your `training_data/` folder (positive + negative)

4. Set wake word name to `"sarah"`

5. Run all cells (takes ~30-60 min on GPU)

6. Download `sarah.tflite` when done

---

### Step 5: Install Model

1. Create folder:
   ```
   mkdir models
   ```

2. Copy your trained model:
   ```
   copy sarah.tflite models\sarah.tflite
   ```

---

### Step 6: Test!

Double-click: **`START_HERE.bat`**

Choose option `[4] Test wake word detection`

Say **"sarah"** and it should detect it!

```
🎉 WAKE WORD DETECTED!
   Name: sarah
   Score: 0.92
```

---

## Troubleshooting

### Microphone not working?

Run:
```cmd
python -c "from src.audio_capture import AudioCapture; AudioCapture().test_microphone()"
```

### TTS not responding?

Check if TTS service is running:
```cmd
curl http://10.185.1.8:9000
```

### Need more help?

Read: **`VOICE_SETUP_GUIDE.md`** (comprehensive guide)

---

## What's Next?

After wake word detection works:

1. ✅ **Wyoming Protocol Client** - Stream audio to backend
2. ✅ **Backend STT Integration** - Transcribe speech
3. ✅ **Sara Chat Integration** - Execute voice commands
4. ✅ **TTS Responses** - Sara talks back
5. ✅ **Shadow Mode Voice** - Voice-controlled work sessions

We'll implement these together step by step!

---

**Ready?** Double-click **`START_HERE.bat`** to begin!
