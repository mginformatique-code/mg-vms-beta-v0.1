# MG-VMS API — image de production (Python 3.11, psycopg3 binaire : pas de compilation)
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:8001/api/ || exit 1
CMD ["./entrypoint.sh"]
