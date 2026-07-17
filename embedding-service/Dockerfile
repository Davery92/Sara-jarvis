FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    sentence-transformers \
    fastapi \
    uvicorn[standard] \
    numpy

# Pre-download model at build time so startup is instant
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

COPY server.py .

EXPOSE 8100

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100"]
