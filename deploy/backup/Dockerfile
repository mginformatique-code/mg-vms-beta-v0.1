FROM postgres:16-alpine
RUN apk add --no-cache python3 py3-pip mc aws-cli
WORKDIR /app
COPY backup.sh .
RUN chmod +x backup.sh
# Sauvegarde planifiée : pg_dump + config + enregistrements -> MinIO/S3, restauration.
CMD ["sh", "-c", "while true; do ./backup.sh; sleep 86400; done"]
