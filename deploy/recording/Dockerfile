FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# Enregistrement continu/planning/détection, rotation, quota, push vers MinIO/S3/NAS.
CMD ["python3", "recorder.py"]
