# Chapitre 16 — Storage Manager

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `11-plateforme-plugins`

Gestion des supports de stockage pour l'enregistrement vidéo. Base core (disques locaux) + plugins pour stockages non-locaux (NAS, S3, Azure, GCS, SFTP).

---

## 16.1 Modèle

**Pool** = unité logique de stockage.

```json
{
  "id": "uuid",
  "name": "Pool principal",
  "type": "local|nfs|smb|s3|azure|gcs|sftp",
  "path": "/data/recordings",           // local
  "endpoint": "...",                     // cloud
  "credentials_encrypted": "...",        // chiffrées Fernet
  "capacity_gb": 4000,
  "free_gb": 2300,
  "retention_days": 14,
  "policy": "rotation|alert_stop|compress_then_rotation",
  "priority": 1,                         // ordre d'usage
  "cameras_assigned": ["uuid", "uuid"]   // caméras qui écrivent ici
}
```

Une caméra peut écrire dans **un** pool primaire + **N** pools archive (pour rétention longue).

## 16.2 Types de pools

### 16.2.1 Local (core)
- SSD/NVMe/HDD sur système de fichiers ext4/xfs.
- Détection SMART via `smartctl`.
- Benchmark IOPS au provisioning.

### 16.2.2 NAS (core)
- NFS, SMB/CIFS montés dans le container backend.
- Warning perf (latence WAN > 10ms peut causer gap enregistrement).

### 16.2.3 Cloud (plugins)
- `s3-storage` (AWS S3 + compatibles Minio, Backblaze, Wasabi).
- `azure-storage` (Blob Storage).
- `gcs-storage` (Google Cloud Storage).
- `sftp-storage` (backup archive nightly).

Chaque plugin implémente l'interface `StorageBackend` (chapitre 11 §11.3.6).

## 16.3 Politique de rotation

- **rotation** — suppression LRU des segments plus vieux que `retention_days`.
- **alert_stop** — arrêt enregistrement + alerte critique quand plein.
- **compress_then_rotation** — segments > 7j compressés avec crf +5 (économie 30%), puis rotation.

## 16.4 Chiffrement (v3.1+)

Optionnel : chiffrement au repos des segments (AES-256). Clé stockée séparément (KMS externe, HSM, ou fichier chiffré passphrase).

## 16.5 Migration & archivage

- **Migration** — déplacer les segments d'un pool à un autre (interface UI).
- **Archivage** — tâche périodique nuit : segments > N jours → pool archive (cold storage).
- **Restore** — un segment archive peut être remonté à chaud à la demande (streaming direct depuis S3 par ex.).

## 16.6 Diagnostics

Voyants rouges standards (chapitre 20) :
- Pool > 90% → warning.
- SMART warning → critique.
- Perf IOPS dégradée → warning.
- Cloud unreachable → circuit breaker + alertes.

## 16.7 Tests

- TA-16.1 : Provisioning pool local + bench IOPS.
- TA-16.2 : Rotation auto : segment > retention → supprimé.
- TA-16.3 : Plugin `s3-storage` : écriture + relecture segment cloud OK.
- TA-16.4 : Alerte pool > 90% → notification proactive.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
