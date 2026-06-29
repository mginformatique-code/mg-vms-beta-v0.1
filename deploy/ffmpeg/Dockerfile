FROM alpine:3.20
RUN apk add --no-cache ffmpeg python3 py3-pip
WORKDIR /app
COPY . .
# go2rtc/ffmpeg : connexion RTSP/ONVIF, transcodage WebRTC/HLS, snapshots.
CMD ["python3", "stream_manager.py"]
