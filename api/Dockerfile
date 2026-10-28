FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Reseed on every boot so the demo data is always in its deterministic,
# hero-scenario-baked-in state -- see seed/generate.py.
# $PORT is honored for Cloud Run (which injects it); falls back to 8000
# for docker-compose, which maps a fixed host port.
CMD ["sh", "-c", "python -m seed.generate && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
