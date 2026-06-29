FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
# Relaye les alertes vers Email/Discord/Telegram/Webhook/MQTT/SMS/Push.
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8080"]
