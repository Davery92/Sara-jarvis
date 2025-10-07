# Wake Word Models

Place your trained wake word models here.

## Expected File

- `sarah.tflite` - Your custom trained "sarah" wake word model

## File Location

Your model should be at:
```
shadow-agent/models/sarah.tflite
```

## Testing

After placing the model here, test it:

```cmd
cd ..
python scripts\test_wake_word.py
```

Say "sarah" and it should detect it!

## Fallback

If `sarah.tflite` is not found, the wake word detector will use the pre-trained "hey mycroft" model for testing.
