FROM python:3.11-slim

WORKDIR /app

# Outils de build pour certaines roues Python (psutil, reportlab, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# emergentintegrations provient d'un index supplémentaire
RUN pip install --no-cache-dir \
    --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ \
    -r requirements.txt

COPY . .

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
    CMD curl -fsS http://localhost:8001/api/ || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
