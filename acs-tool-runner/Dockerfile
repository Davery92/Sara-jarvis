FROM python:3.11-slim

RUN useradd -r -u 65532 -g nogroup -s /usr/sbin/nologin sandbox

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Drop privileges. The subprocess inherits this UID, so user code can't
# touch root-owned files even if it escapes the rlimit fence.
USER sandbox

EXPOSE 8001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
