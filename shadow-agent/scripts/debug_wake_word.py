"""
Debug Wake Word Setup
Checks if everything is configured correctly
"""
import sys
from pathlib import Path

print("=" * 60)
print("🔍 WAKE WORD DEBUG SCRIPT")
print("=" * 60)
print()

# Check Python version
print("[1/6] Checking Python version...")
print(f"   Python: {sys.version}")
print()

# Check if openwakeword is installed
print("[2/6] Checking openwakeword installation...")
try:
    import openwakeword
    print(f"   ✅ openwakeword installed: {openwakeword.__version__}")
except ImportError as e:
    print(f"   ❌ openwakeword NOT installed: {e}")
    print("   Run: pip install openwakeword")
    sys.exit(1)
print()

# Check if sounddevice is installed
print("[3/6] Checking sounddevice installation...")
try:
    import sounddevice as sd
    print(f"   ✅ sounddevice installed")
except ImportError as e:
    print(f"   ❌ sounddevice NOT installed: {e}")
    print("   Run: pip install sounddevice")
    sys.exit(1)
print()

# Check for sarah.tflite model
print("[4/6] Checking for sarah.tflite model...")
agent_root = Path(__file__).parent.parent
model_path = agent_root / "models" / "sarah.tflite"
print(f"   Looking for: {model_path}")
if model_path.exists():
    size_mb = model_path.stat().st_size / (1024 * 1024)
    print(f"   ✅ Model found! Size: {size_mb:.2f} MB")
else:
    print(f"   ❌ Model NOT found at {model_path}")
    print("   Copy your sarah.tflite file to the models/ folder")
print()

# Try loading the model
print("[5/6] Testing model load...")
try:
    from openwakeword.model import Model

    if model_path.exists():
        print(f"   Loading custom model: {model_path}")
        owwModel = Model(wakeword_models=[str(model_path)])
        print(f"   ✅ Model loaded successfully!")
    else:
        print(f"   Loading fallback model: hey_mycroft")
        owwModel = Model(wakeword_models=["hey_mycroft"])
        print(f"   ✅ Fallback model loaded!")

except Exception as e:
    print(f"   ❌ Failed to load model: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
print()

# Check audio devices
print("[6/6] Checking audio devices...")
try:
    devices = sd.query_devices()
    print("   Available input devices:")
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            default = " (DEFAULT)" if i == sd.default.device[0] else ""
            print(f"      [{i}] {dev['name']}{default}")
    print(f"   ✅ Found {len([d for d in devices if d['max_input_channels'] > 0])} input devices")
except Exception as e:
    print(f"   ❌ Failed to query devices: {e}")
print()

print("=" * 60)
print("✅ ALL CHECKS PASSED!")
print("=" * 60)
print()
print("You can now run: python scripts\\test_wake_word.py")
print()
