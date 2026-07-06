# ML training worker (Desktop Jarvis Overhaul C2)
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    httpx==0.27.2 \
    psycopg2-binary==2.9.9 \
    numpy==1.26.4 \
    scikit-learn==1.4.2 \
    lightgbm==4.3.0 \
    minio==7.2.7

COPY ml_worker.py /app/

CMD ["python", "ml_worker.py"]
