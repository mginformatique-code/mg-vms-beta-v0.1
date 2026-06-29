# MG-VMS AI Engine — YOLOv11 + ByteTrack (GPU)
# Base CUDA pour inférence GPU en production.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# ultralytics (YOLOv11), supervision/bytetrack, opencv, redis, psycopg
RUN pip3 install -r requirements.txt

COPY . .
# Consomme les flux (via ffmpeg-service), infère, écrit events + déclenche alertes.
CMD ["python3", "worker.py"]
