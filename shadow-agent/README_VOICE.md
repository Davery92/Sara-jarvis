# 🎙️ Sara Voice Control - Quick Reference

## 🚀 Getting Started (3 Easy Steps)

### 1️⃣ Install Dependencies

Double-click: **`SETUP.bat`**

This installs Python packages and tests your microphone.

---

### 2️⃣ Record Your Voice (2 minutes)

Double-click: **`RECORD_SARAH.bat`**

Say "sarah" 10 times when prompted. The script will guide you.

---

### 3️⃣ Generate Negatives (2 minutes)

Double-click: **`GENERATE_NEGATIVES.bat`**

Creates synthetic samples automatically using Sara's TTS.

---

## 📋 What You'll Have

After steps 1-3:
```
training_data/
├── positive/     (10 samples of you saying "sarah")
└── negative/     (80 synthetic samples)
```

---

## 🎓 Training Your Model

### Option A: Google Colab (Recommended)

1. Go to: https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb

2. Click "Open in Colab"

3. Upload your `training_data/` folder

4. Set `WAKE_WORD_NAME = "sarah"`

5. Run all cells (~30-60 min)

6. Download `sarah.tflite`

7. Copy to `shadow-agent/models/sarah.tflite`

### Option B: Local (Advanced)

If you have a GPU:
```bash
# Install training dependencies
pip install tensorflow

# Run training
python scripts/train_local.py
```

---

## ✅ Testing

After training, test your model:

```cmd
python scripts\test_wake_word.py
```

Say "sarah" and it should detect it!

```
🎉 WAKE WORD DETECTED!
   Name: sarah
   Score: 0.92
```

---

## 🔧 Adjusting Sample Count

Want to record more/fewer samples?

Edit `scripts/record_wake_word_windows.py`:
```python
NUM_SAMPLES = 10  # Change this number
```

Recommendations:
- **10 samples**: Quick test (may have lower accuracy)
- **50 samples**: Good balance (recommended)
- **100+ samples**: Best accuracy (production quality)

---

## 🐛 Troubleshooting

### Script closes immediately

Use `SETUP.bat` instead of `START_HERE.bat` for first-time setup.

### Microphone not working

Test it:
```cmd
python -c "from src.audio_capture import AudioCapture; AudioCapture().test_microphone()"
```

### Python not found

Install Python 3.8+ from https://www.python.org/

### TTS not responding

Make sure Sara's TTS is running:
```cmd
curl http://10.185.1.8:9000
```

---

## 📁 Files Reference

**Quick Launchers:**
- `SETUP.bat` - Install dependencies (run first!)
- `RECORD_SARAH.bat` - Record your voice
- `GENERATE_NEGATIVES.bat` - Create negative samples
- `START_HERE.bat` - Interactive menu (use after setup)

**Documentation:**
- `README_VOICE.md` - This file (quick reference)
- `QUICKSTART.md` - Step-by-step guide
- `VOICE_SETUP_GUIDE.md` - Comprehensive guide

**Scripts:**
- `scripts/record_wake_word_windows.py` - Recording script
- `scripts/generate_negative_samples.py` - Negative generator
- `scripts/test_wake_word.py` - Test detection

---

## 🎯 Next Steps After Detection Works

Once "sarah" detection is working:

1. ✅ Wyoming protocol integration
2. ✅ Backend STT/TTS connection
3. ✅ Voice commands for Sara
4. ✅ Shadow Mode voice control
5. ✅ Multi-device support

We'll build these together!

---

**Need help?** Check `VOICE_SETUP_GUIDE.md` for detailed troubleshooting.
