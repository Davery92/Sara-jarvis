PY=python3
BACKEND=backend
VENV=$(BACKEND)/venv

.PHONY: setup migrate serve stop

setup:
	cd $(BACKEND) && test -x "$(VENV)/bin/python" || $(PY) -m venv venv
	$(VENV)/bin/python -m pip install --upgrade pip setuptools wheel
	$(VENV)/bin/python -m pip install -r $(BACKEND)/requirements.txt

migrate:
	cd $(BACKEND) && DATABASE_URL=$$DATABASE_URL $(VENV)/bin/python -m alembic upgrade heads

serve:
	./scripts/full_api_boot.sh

stop:
	- pkill -f "uvicorn app.main:app"
	- pkill -f uvicorn

