"""
Minimal test - just load the model without audio
This tests if the sarah.tflite model is valid
"""
import sys
from pathlib import Path

print("=" * 60)
print("🔍 MODEL LOAD TEST (No Microphone)")
print("=" * 60)
print()

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

print("[1/2] Importing openwakeword...")
try:
    from openwakeword.model import Model
    print("   ✅ openwakeword imported")
except Exception as e:
    print(f"   ❌ Failed to import: {e}")
    input("\nPress Enter to exit...")
    sys.exit(1)
print()

print("[2/2] Loading sarah.tflite model...")
agent_root = Path(__file__).parent.parent
model_path = agent_root / "models" / "sarah.tflite"
print(f"   Model path: {model_path}")
print(f"   Exists: {model_path.exists()}")

if not model_path.exists():
    print("   ❌ Model file not found!")
    input("\nPress Enter to exit...")
    sys.exit(1)

try:
    print("   Loading model...")
    owwModel = Model(wakeword_models=[str(model_path)])
    print("   ✅ Model loaded successfully!")
    print()
    print("=" * 60)
    print("✅ SUCCESS!")
    print("=" * 60)
    print()
    print("Your sarah.tflite model is valid and can be loaded.")
    print("The issue must be with audio capture or microphone permissions.")
    print()
    print("Next: Try running TEST_WAKE.bat")
    print()
except Exception as e:
    print(f"   ❌ Failed to load model: {e}")
    print()
    print("=" * 60)
    print("❌ MODEL ERROR")
    print("=" * 60)
    print()
    print("Your sarah.tflite file may be corrupted or incompatible.")
    print()
    print("Error details:")
    import traceback
    traceback.print_exc()
    print()

input("\nPress Enter to exit...")
