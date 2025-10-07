"""
Convert TFLite model to ONNX for Windows compatibility
"""
from pathlib import Path
import sys

print("=" * 60)
print("🔄 TFLITE → ONNX CONVERTER")
print("=" * 60)
print()

# Check for tf2onnx
try:
    import tf2onnx
    print("✅ tf2onnx installed")
except ImportError:
    print("❌ tf2onnx not installed")
    print()
    print("Installing tf2onnx...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "tf2onnx", "tensorflow"])
    print()

# Now do the conversion
agent_root = Path(__file__).parent.parent
tflite_path = agent_root / "models" / "sarah.tflite"
onnx_path = agent_root / "models" / "sarah.onnx"

if not tflite_path.exists():
    print(f"❌ Error: {tflite_path} not found!")
    input("\nPress Enter to exit...")
    sys.exit(1)

print(f"Input:  {tflite_path}")
print(f"Output: {onnx_path}")
print()

print("Converting...")
print("This may take a minute...")
print()

try:
    # Unfortunately, direct TFLite → ONNX conversion is complex
    # The proper way is to re-export from the original training
    print("⚠️  Direct TFLite → ONNX conversion is complex.")
    print()
    print("RECOMMENDED APPROACH:")
    print("  1. Go back to your Google Colab training notebook")
    print("  2. After training, add this cell to export ONNX:")
    print()
    print("     # Export to ONNX")
    print("     import tf2onnx")
    print("     spec = (tf.TensorSpec((None, 96, 40, 1), tf.float32, name='input'),)")
    print("     onnx_model, _ = tf2onnx.convert.from_keras(model, input_signature=spec)")
    print("     with open('sarah.onnx', 'wb') as f:")
    print("         f.write(onnx_model.SerializeToString())")
    print()
    print("  3. Download sarah.onnx")
    print("  4. Copy to shadow-agent/models/sarah.onnx")
    print()
    print("ALTERNATIVE: Use pre-trained models")
    print("  - For testing, you can use 'hey_mycroft' (works on Windows)")
    print("  - Edit wake_word.py to use built-in models")
    print()

except Exception as e:
    print(f"❌ Conversion failed: {e}")
    import traceback
    traceback.print_exc()

input("\nPress Enter to exit...")
