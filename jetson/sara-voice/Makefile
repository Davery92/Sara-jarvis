.PHONY: install start stop restart logs test status

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
SERVICE := sara-voice

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	mkdir -p logs models
	@echo "Installation complete. Place model files in models/"
	@echo "  - hey_sara.onnx (OpenWakeWord)"
	@echo "  - silero_vad.onnx (Silero VAD)"
	@echo "  - david_face.npy (Face embedding)"
	@echo "  - ggml-base.en.bin (Whisper fallback, optional)"

start:
	$(PYTHON) -m sara_voice

start-bg:
	nohup $(PYTHON) -m sara_voice > logs/sara-voice.log 2>&1 &

stop:
	@pkill -f "python -m sara_voice" || echo "Not running"

restart: stop start

logs:
	tail -f logs/sara-voice.log

test:
	$(PYTHON) scripts/test_audio.py

test-wake:
	$(PYTHON) -c "from sara_voice.audio.wake_word import WakeWordDetector; print('Wake word module OK')"

test-vision:
	$(PYTHON) -c "from sara_voice.vision.camera import CameraCapture; print('Vision module OK')"

status:
	@systemctl status $(SERVICE) 2>/dev/null || echo "systemd service not installed"
	@echo "---"
	@pgrep -fa "sara_voice" || echo "Process not running"

service-install:
	sudo cp systemd/sara-voice.service /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable $(SERVICE)
	@echo "Service installed. Start with: sudo systemctl start $(SERVICE)"

service-uninstall:
	sudo systemctl stop $(SERVICE) || true
	sudo systemctl disable $(SERVICE) || true
	sudo rm -f /etc/systemd/system/sara-voice.service
	sudo systemctl daemon-reload
