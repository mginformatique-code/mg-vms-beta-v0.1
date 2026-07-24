# Chapitre 5 — Contrats d'interface

> **Version** : v1.0 · **Date** : 2026-07-24 · **Statut** : brouillon en cours de validation
> **Auteur** : équipe MG-VMS · **Reviewers** : *à compléter*
> **Chapitres liés** : `04-architecture-cible` (topologie) · `22-administration-rbac` (auth) · `23-api-publique` (SDK) · `24-plugins-marketplace` (intégrations)

Ce chapitre fige les **contrats de communication** exposés par MG-VMS Next Generation. Il est la référence unique pour tout intégrateur (SDK Python, SDK JS, plugin tiers, VMS partenaire, script d'automatisation, agent IA externe). Un dev qui n'a que ce chapitre doit pouvoir écrire une intégration fonctionnelle sans lire le code source du backend.

Les cinq surfaces d'interface décrites ici sont :

1. **REST HTTP** — CRUD, actions synchrones, configuration.
2. **WebSocket** — flux temps-réel entrant (événements, métriques).
3. **MQTT** — publish/subscribe pour intégrations IoT.
4. **Webhooks sortants** — notification vers systèmes tiers.
5. **SDK officiels** — Python et JavaScript, wrappers idiomatiques.

---

## 5.1 Principes généraux

### 5.1.1 Versioning

**URL versioning** — toutes les URLs d'API sont préfixées par une version majeure : `/api/v1/...` en v3.0, `/api/v2/...` en cas de breaking change. La version courante en v3.0 = **v1**.

**Politique de dépréciation** :
- Une version majeure est supportée **24 mois minimum** après la sortie de sa successeur.
- Les endpoints dépréciés retournent l'en-tête `Deprecation: true` + `Sunset: <date ISO>` + `Link: </api/v2/...>; rel="successor-version"`.
- Le changelog documente chaque breaking change avec la migration path.

**Compatibilité rétrograde** : ajouts de champs OK (les clients ignorent les inconnus). Retraits ou renommages ⇒ nouvelle version majeure obligatoire.

**Écart avec v2.22.0** — les URLs actuelles sont `/api/...` sans versioning. Le préfixe `/v1` sera introduit en v3.0. Le backend maintiendra les 2 pendant la période de migration (règle R08).

### 5.1.2 Formats

- **Encodage** : UTF-8 partout.
- **Content-Type** : `application/json` pour REST par défaut. `multipart/form-data` pour uploads (photos, imports CSV). `text/event-stream` pour SSE optionnel.
- **Dates** : ISO 8601 UTC systématique (`2026-07-24T14:32:11.845000+00:00`). Pas de timezone locale, pas de timestamp epoch (sauf explicite dans un endpoint metrics).
- **IDs** : UUIDv4 en `str` (`"a7f8b3c1-...")`, jamais d'ObjectId Mongo exposé au client.
- **Noms de champs** : `snake_case` dans les payloads JSON. `kebab-case` dans les URLs (`/api/v1/anpr-benchmark`).
- **Booléens** : `true` / `false`, jamais `1/0` ni `"yes"/"no"`.
- **Nombres décimaux** : point (`0.85`), jamais virgule.

### 5.1.3 Authentification

**Toutes les surfaces (REST, WS, MQTT, webhooks entrants) utilisent le même token JWT.**

- **REST** — header `Authorization: Bearer <access_token>`.
- **WebSocket** — query param `?token=<access_token>` (les navigateurs ne peuvent pas injecter d'en-tête sur `new WebSocket()`).
- **Téléchargements HTML `<a href>`** — query param `?token=<access_token>` accepté en fallback (idem raison).
- **MQTT** — username = `mgvms`, password = `<access_token>` (au boot du client MQTT).
- **Webhooks entrants (venant du VMS)** — signés HMAC SHA-256 avec secret partagé (cf. §5.5.3).

**Cycle de vie des tokens** :
- `access_token` — 15 min de validité, JWT signé HS256 avec `MGVMS_JWT_SECRET`.
- `refresh_token` — 7 jours, échangeable contre un nouveau `access_token` via `POST /api/v1/auth/refresh`.
- **Rotation** — chaque refresh invalide le refresh_token précédent (single-use).

### 5.1.4 Erreurs standardisées

Toute erreur HTTP retourne un JSON de forme fixe :

```json
{
  "error": {
    "code": "camera_not_found",
    "message": "La caméra spécifiée n'existe pas ou a été supprimée.",
    "details": {
      "camera_id": "abc-123"
    },
    "trace_id": "01HXYZ..."
  }
}
```

Champs :
- `code` — identifiant machine stable (snake_case), utilisé pour logique client. **Contract stable** : ne change jamais entre versions mineures.
- `message` — texte français destiné à l'utilisateur final. Peut évoluer.
- `details` — objet contextuel (optionnel) avec les données utiles au debug côté client.
- `trace_id` — ID de corrélation pour retrouver l'appel côté logs backend.

**Table des codes HTTP** :

| HTTP | Sens | Exemples de `code` |
|---|---|---|
| 400 | Requête malformée | `validation_error`, `invalid_rtsp_url` |
| 401 | Non authentifié | `token_missing`, `token_expired`, `token_invalid` |
| 403 | Non autorisé | `permission_denied`, `role_insufficient` |
| 404 | Ressource introuvable | `camera_not_found`, `user_not_found` |
| 409 | Conflit d'état | `camera_already_exists`, `stream_locked` |
| 422 | Validation métier | `resolution_below_minimum`, `plate_too_short` |
| 429 | Rate limit dépassé | `rate_limit_exceeded` |
| 500 | Erreur serveur | `internal_error` (jamais de stack trace au client) |
| 503 | Dépendance externe KO | `go2rtc_unreachable`, `mongo_unreachable` |

### 5.1.5 Rate limiting

Défauts (surchargable en env `MGVMS_RATE_LIMIT_*`) :

| Endpoint / catégorie | Limite | Fenêtre |
|---|---|---|
| `/api/v1/auth/login` | 5 requêtes | 60 s (par IP) |
| `/api/v1/auth/refresh` | 20 requêtes | 60 s (par user) |
| Endpoints mutant (POST/PUT/DELETE) | 60 req | 60 s (par user) |
| Endpoints lecture | 300 req | 60 s (par user) |
| WebSocket connect | 10 conn | 60 s (par IP) |
| Webhooks sortants | 100/s max | global backend |

Dépassement ⇒ HTTP 429 + en-tête `Retry-After: <seconds>`.

### 5.1.6 Pagination et filtres

**Pagination** — pour toute liste retournant potentiellement > 100 éléments :

```
GET /api/v1/events?offset=0&limit=50&sort=timestamp:desc
```

- `offset` (int ≥ 0) — défaut 0.
- `limit` (int, 1 ≤ N ≤ 500) — défaut 50.
- `sort` — `<field>:<asc|desc>`, plusieurs valeurs séparées par virgule.

Réponse enveloppée :
```json
{
  "items": [...],
  "pagination": {
    "offset": 0,
    "limit": 50,
    "total": 1247,
    "has_more": true
  }
}
```

**Filtres** — champs de la ressource utilisables en query param (`?camera_id=X&severity=critical`). Opérateurs supportés : `=` (défaut), `!=`, `<`, `>`, `<=`, `>=` via suffixe `?created_at__gte=2026-07-01`.

### 5.1.7 Content negotiation

**Export** — les endpoints qui retournent des collections supportent 4 formats via query `?format=`:
- `json` (défaut)
- `csv` (BOM UTF-8, séparateur `,`, quote `"`, dates ISO, LibreOffice + Excel compatibles — cf. AP-08)
- `xlsx` (via `openpyxl`, formatage cellules dates)
- `pdf` (via rapports générés — cf. chapitre 21)

Exemple : `GET /api/v1/plates?format=csv&format__country=fr`.

---

## 5.2 REST API — panorama

Cette section donne le panorama complet des ressources exposées. Chaque module fonctionnel a son chapitre dédié qui détaille son schéma métier ; ici on donne la **forme** de l'interface.

### 5.2.1 Authentification (`/api/v1/auth`)

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| POST | `/login` | public | `{email, password}` → `{access_token, refresh_token, user}` |
| POST | `/refresh` | public | `{refresh_token}` → `{access_token, refresh_token}` |
| POST | `/logout` | auth | Invalide le refresh_token courant |
| POST | `/2fa/enable` | auth | Active TOTP, retourne QR code |
| POST | `/2fa/verify` | auth | Valide code TOTP |
| POST | `/password-reset/request` | public | `{email}` → email avec token à usage unique |
| POST | `/password-reset/confirm` | public | `{token, new_password}` |

### 5.2.2 Sites & Utilisateurs

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| GET | `/sites` | auth | Liste des sites autorisés pour l'user |
| POST | `/sites` | admin | Créer un site |
| PUT | `/sites/{id}` | admin | Modifier |
| DELETE | `/sites/{id}` | admin | Supprimer (soft-delete + confirmation) |
| GET | `/users` | admin | Liste users |
| POST | `/users` | admin | Créer user |
| PUT | `/users/{id}` | admin | Modifier |
| DELETE | `/users/{id}` | admin | Supprimer |
| GET | `/users/me` | auth | Profil courant + permissions effectives |

### 5.2.3 Caméras (`/api/v1/cameras`)

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| GET | `/cameras` | view_live | Liste (paginée, filtrable par site, status, tag) |
| GET | `/cameras/{id}` | view_live | Détail |
| POST | `/cameras` | technician | Créer (modes : `manual`, `rtsp`, `onvif`) |
| PUT | `/cameras/{id}` | technician | Modifier |
| DELETE | `/cameras/{id}` | admin | Supprimer (soft-delete, confirm) |
| POST | `/cameras/discover` | technician | Découverte ONVIF WS-Discovery (multicast LAN) |
| POST | `/cameras/test-connectivity` | technician | Test ONVIF + ffprobe RTSP sans persistence |
| POST | `/cameras/{id}/refresh-stream` | technician | Force re-registration go2rtc (bouton "Réparer") |
| POST | `/cameras/{id}/snapshot` | view_live | Prend un snapshot ponctuel (retourne JPEG) |
| GET | `/cameras/{id}/diagnostic` | view_live | État complet caméra (cause probable, flux OK/KO, résumé 30j) |

**Schéma `Camera`** (extrait — détail au chapitre 10) :
```json
{
  "id": "uuid",
  "name": "Entrée principale",
  "site_id": "uuid", "site_name": "Site A",
  "rtsp_url_masked": "rtsp://user:******@192.168.1.42/live",
  "onvif": {"host": "192.168.1.42", "port": 80, "profile_token": "profile_1"},
  "codec": "h264", "resolution": "1920x1080", "fps": 15,
  "rtsp_transport": "tcp",
  "status": "online",
  "detect_enabled": true,
  "ai_modules": {"yolo": {"enabled": true}, "anpr": {"enabled": false}, "face": {"enabled": false}},
  "record_enabled": true, "storage_pool_id": "uuid",
  "ptz_enabled": false,
  "created_at": "2026-07-01T12:00:00+00:00",
  "updated_at": "2026-07-24T14:32:11+00:00",
  "last_seen": "2026-07-24T14:32:01+00:00"
}
```

### 5.2.4 Streams (`/api/v1/stream`)

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| GET | `/stream/{id}/live.mjpeg?hd=1` | view_live | Flux MJPEG multipart (fallback WebRTC) |
| GET | `/stream/{id}/frame.jpeg?hd=1` | view_live | Snapshot ponctuel (démo uniquement en prod — ADR-04) |
| POST | `/pipeline/webrtc/{id}` | view_live | Signalisation SDP (offer → answer) |
| GET | `/stream/{id}/hls/master.m3u8` | view_recordings | HLS playlist (mobile, mode enregistrement) |
| GET | `/stream/{id}/recordings?from=&to=` | view_recordings | Segments MP4 dans une fenêtre temporelle |

### 5.2.5 Événements, alertes, plaques

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| GET | `/events` | view_live | Liste événements IA (filtres : camera_id, category, from, to, format) |
| GET | `/events/{id}` | view_live | Détail événement (miniature HD + crop + timings IA) |
| GET | `/alerts` | view_live | Alertes actives + historique |
| POST | `/alerts/{id}/acknowledge` | view_live | ACK avec commentaire |
| GET | `/plates` | read_plates | Historique ANPR (filtres plate, camera, from, to) |
| GET | `/plates/{id}` | read_plates | Détail plaque (scène HD + inset véhicule + inset OCR) |
| GET | `/plates/search?q=` | read_plates | Recherche fuzzy plaque (autocomplete) |
| GET | `/plates/watchlist` | technician | Liste watchlist globale |
| POST | `/plates/watchlist` | technician | Ajouter plaque (`{plate, list_type, reason}`) |
| POST | `/plates/watchlist/import` | technician | Import CSV bulk |
| GET | `/plates/watchlist/export` | technician | Export CSV |

### 5.2.6 Configuration IA (`/api/v1/ai`)

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| GET | `/ai/config` | technician | Config runtime globale (device, confidence, interval) |
| PUT | `/ai/config` | admin | Modifier |
| GET | `/ai/scenarios` | technician | Scénarios (crossline, zone, loitering, counting…) |
| PUT | `/ai/scenarios` | admin | Modifier |
| GET | `/ai/arming` | technician | Armements (calendrier par caméra) |
| PUT | `/ai/arming` | admin | Modifier |
| POST | `/ai/benchmark?camera_id=&iterations=` | admin | Benchmark cycle IA complet (retourne timings avg + FPS + backend GPU/CPU) |

### 5.2.7 Diagnostics (`/api/v1/diagnostics`)

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| GET | `/diagnostics/ai-health` | view_live | Santé pipeline IA (yolo/alpr loaded, torch, cuda, cycles, erreurs) |
| GET | `/diagnostics/frame-source` | view_live | Workers ffmpeg-GPU persistants |
| GET | `/diagnostics/streams-sync` | technician | Réconciliation DB ↔ go2rtc |
| POST | `/diagnostics/streams-sync/repair` | technician | Force sync_all_streams() |
| GET | `/diagnostics/stream-lifecycle` | technician | Journal des transitions stream (résumé toutes caméras) |
| GET | `/diagnostics/stream-lifecycle/{camera_id}` | technician | Journal détaillé + compteur d'échecs consécutifs |
| GET | `/diagnostics/journal` | technician | Journal global filtrable (camera, cause, event_type) |
| GET | `/diagnostics/camera/{id}/summary` | view_live | Résumé 30j (MTBF, top causes, dernier incident) |
| GET | `/diagnostics/camera/{id}/report` | technician | Rapport JSON téléchargeable (config + summary + 200 incidents + 200 lignes logs) |
| GET | `/diagnostics/camera/{id}/logs?lines=` | technician | Tail logs backend + go2rtc filtrés |
| POST | `/diagnostics/camera/{id}/test-cause` | admin | Test heuristique CAUSE_RULES sur texte |

### 5.2.8 Système et santé

| Verbe | URL | Rôle | Description |
|---|---|---|---|
| GET | `/health` | public | Liveness (backend répond) |
| GET | `/health/ready` | public | Readiness (Mongo + go2rtc joignables) |
| GET | `/system/gpu/summary` | view_live | Snapshot GPU compact (poll header) |
| GET | `/system/gpu` | technician | Rapport GPU détaillé (NVML, runtimes) |
| GET | `/system/storage` | technician | Pools de stockage (SMART, occupation) |
| GET | `/pipeline/config` | technician | Config pipeline vidéo (GPU/CPU, preview mode) |
| PUT | `/pipeline/config` | admin | Modifier |
| GET | `/pipeline/status` | technician | État pipeline effectif par caméra |
| GET | `/dashboard/stats` | view_live | Métriques temps réel (CPU, RAM, GPU, événements 24h, alertes actives, plaques) |
| GET | `/audit-logs` | admin | Journal actions admin (paginé, filtrable) |

---

## 5.3 WebSocket — flux temps-réel

**Endpoint unique** : `wss://<host>/api/v1/ws?token=<access_token>`.

**Format enveloppe** — chaque message JSON encapsulé :
```json
{
  "channel": "event",
  "timestamp": "2026-07-24T14:32:11+00:00",
  "payload": { ... }
}
```

**Canaux logiques** (server → client) :

| Canal | Fréquence | Payload | Consommateurs cibles |
|---|---|---|---|
| `event` | Push | Événement IA complet (miniature HD, bbox, catégorie, cam) | UI /live, /événements-IA |
| `alert` | Push | Alerte (severity, cam, message, thumbnail, ack requis) | UI /alertes, notif desktop |
| `metric` | Broadcast 5 s | `{cpu, ram, sto, gpu:{util,vram,temp}, bandwidth}` | UI header, dashboard |
| `camera_status` | Push (sur transition) | `{camera_id, status: online\|offline, reason}` | UI /cameras, /live overlays |
| `stream_lifecycle` | Push (technicien uniquement) | Entrée lifecycle (action, reason, caller, ts) | UI /diagnostics |
| `plate` | Push | Plaque détectée (plate, cam, confidence, thumbnail, list_status) | UI /anpr, alertes blacklist |
| `notification` | Push | Confirmation d'envoi notif externe (SMTP OK/KO, Discord OK/KO) | UI settings notifs |
| `presence` | Push | Utilisateur connecté/déconnecté (admin uniquement) | UI /administration |

**Filtrage par abonnement** (message client → server) :
```json
{
  "action": "subscribe",
  "channels": ["event", "alert"],
  "filters": {
    "event": {"camera_ids": ["uuid1", "uuid2"], "categories": ["Personne", "Voiture"]},
    "alert": {"severities": ["critical", "warning"]}
  }
}
```

Le serveur ne pousse au client que les messages qui matchent son filtre. Un client sans souscription ne reçoit **aucun** message.

**Heartbeat** — le serveur envoie `{channel: "ping", timestamp: ..., payload: {}}` toutes les 30 s. Le client doit répondre `{action: "pong"}`. Absence de pong 90 s ⇒ déconnexion propre.

**Reconnexion** — le client doit implémenter un backoff exponentiel (1s, 2, 4, 8, 16, 32, plafond 60 s) + re-subscribe automatique après reconnect.

**Codes de fermeture** :
- 1000 — fermeture normale
- 4001 — token invalide ou expiré
- 4003 — trop de connexions simultanées pour ce user (défaut = 5)
- 4008 — rate limit dépassé

---

## 5.4 MQTT — publish/subscribe IoT

**Broker** — MG-VMS peut publier sur un broker MQTT tiers (Mosquitto, HiveMQ, EMQX…) configuré par l'admin. Le VMS n'héberge **pas** de broker.

**Auth** — TLS + `username: mgvms` + `password: <MGVMS_MQTT_TOKEN>` (token permanent généré en UI settings).

**Topics** — nomenclature hiérarchique stable :

```
mgvms/{site_id}/camera/{camera_id}/status         → online | offline
mgvms/{site_id}/camera/{camera_id}/event          → événement JSON complet
mgvms/{site_id}/camera/{camera_id}/plate          → plaque JSON
mgvms/{site_id}/alert                              → alerte JSON
mgvms/{site_id}/parking/{parking_id}/occupation   → {available, total, occupied}
mgvms/{site_id}/parking/{parking_id}/spot/{spot_id}/state  → free | occupied | reserved
mgvms/system/health                                → JSON santé backend/go2rtc/GPU
```

**QoS** :
- Événements et alertes : QoS 1 (at-least-once) — le broker gère la déduplication client.
- Métriques et status : QoS 0 (fire-and-forget) — perte tolérable.
- `retained: true` sur les topics status et occupation — un client qui souscrit reçoit immédiatement le dernier état.

**Last Will Testament (LWT)** — MG-VMS déclare au broker sur connexion :
```
Topic: mgvms/system/health
Payload: {"status": "offline", "reason": "connection lost"}
```
Un client MQTT peut ainsi détecter la panne du VMS via absence de heartbeat + LWT retained.

**Heartbeat** — MG-VMS publie sur `mgvms/system/health` toutes les 30 s :
```json
{"status": "online", "uptime_seconds": 12345, "cameras_online": 42, "ai_healthy": true}
```

**Subscribe entrant (contrôle du VMS via MQTT)** — v3.5+ optionnel :
```
mgvms/{site_id}/camera/{camera_id}/ptz/command     ← preset:N | move:up|down|... | stop
mgvms/{site_id}/camera/{camera_id}/record/command  ← start | stop
```
Chaque commande est auditée (R09).

---

## 5.5 Webhooks sortants

**Objectif** — notifier un système tiers (n8n, Node-RED, endpoint custom) d'un événement MG-VMS.

**Configuration** — un admin crée un webhook via `POST /api/v1/webhooks` :
```json
{
  "name": "n8n incident alert",
  "url": "https://n8n.example.com/webhook/xyz",
  "event_types": ["alert.critical", "plate.blacklist", "camera.offline"],
  "filters": {"site_ids": ["uuid1"]},
  "secret": "generated_hmac_secret_32_chars",
  "enabled": true,
  "retry_policy": "default"
}
```

### 5.5.1 Format payload

Toute requête webhook est un `POST application/json` avec le corps :

```json
{
  "event": "alert.critical",
  "event_id": "uuid-of-delivery-attempt",
  "occurred_at": "2026-07-24T14:32:11+00:00",
  "site": {"id": "uuid", "name": "Site A"},
  "data": {
    "alert_id": "uuid",
    "severity": "critical",
    "type": "anpr",
    "message": "Plaque en liste noire : AB-123-CD",
    "camera": {"id": "uuid", "name": "Entrée"},
    "plate": "AB-123-CD",
    "thumbnail_url": "https://<host>/api/v1/alerts/uuid/thumbnail?token=temporary"
  },
  "delivery": {
    "attempt": 1,
    "max_attempts": 6
  }
}
```

### 5.5.2 Retry policy

- Défaut : 1s, 4s, 16s, 64s, 256s, 1024s (6 tentatives, ~ 24 min total).
- Statuts déclencheurs de retry : 5xx, timeout > 15s, erreur réseau.
- Statuts terminaux : 2xx (succès), 4xx (erreur client — pas de retry).
- Après 6 échecs : passage en dead-letter (`db.failed_operations`) avec possibilité de retraitement manuel via UI settings webhooks.

### 5.5.3 Signature HMAC

Chaque requête est signée pour permettre au receveur de vérifier l'authenticité. En-tête :

```
X-MGVMS-Signature: sha256=<hex_digest>
X-MGVMS-Event-ID: <uuid>
X-MGVMS-Timestamp: <unix_epoch_seconds>
```

Calcul (côté MG-VMS) :
```python
message = f"{timestamp}.{raw_body}"
signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
```

Vérification (côté receveur) — recalculer avec le même secret, comparer en constant-time. Refuser si `abs(now - timestamp) > 300s` (protection replay).

### 5.5.4 Événements disponibles

Nomenclature `<domaine>.<type>` :

- `camera.created` · `camera.updated` · `camera.deleted` · `camera.online` · `camera.offline`
- `event.detected` (événement IA générique)
- `plate.detected` · `plate.blacklist` · `plate.whitelist`
- `alert.warning` · `alert.critical`
- `alert.acknowledged`
- `recording.started` · `recording.stopped`
- `user.login` · `user.logout` · `user.password_reset`
- `system.gpu_saturated` · `system.storage_almost_full` · `system.dependency_down`

Un webhook peut souscrire à un pattern glob : `plate.*` reçoit toutes les sous-catégories.

---

## 5.6 SDK officiels

MG-VMS fournit deux SDK officiels versionnés indépendamment du backend. Ils encapsulent les 5 surfaces (REST + WS + MQTT + webhooks + upload) avec des ergonomies natives.

### 5.6.1 SDK Python (`mgvms-sdk`)

```python
from mgvms import Client, EventFilter

# Auth
client = Client("https://vms.example.com", api_key="...")
# OU : client.login(email, password)

# REST idiomatique
cameras = client.cameras.list(site_id="uuid", status="online")
cam = client.cameras.get("uuid")
snapshot_bytes = cam.snapshot(hd=True)

# WebSocket async
async for event in client.stream.events(EventFilter(categories=["Personne"])):
    print(f"{event.timestamp} · {event.camera.name} · {event.label}")

# Upload photo (face recognition)
face = client.faces.create(name="John Doe", watchlist=True)
face.upload_photo(open("john.jpg", "rb"))
```

**Distribution** : `pip install mgvms-sdk`. Support Python 3.10+. Type hints complets (`py.typed`). Async natif via `asyncio`.

### 5.6.2 SDK JavaScript (`@mgvms/client`)

```javascript
import { MGVMSClient } from '@mgvms/client';

const client = new MGVMSClient({ baseUrl: 'https://vms.example.com', accessToken: '...' });

// REST
const cameras = await client.cameras.list({ site_id: 'uuid' });

// WebSocket avec React hook (package `@mgvms/react`)
const { events, connectionState } = useMGVMSEvents({ camera_ids: ['uuid'] });
```

**Distribution** : `npm install @mgvms/client @mgvms/react`. Compatible Node 18+ et navigateurs modernes. Types TypeScript complets.

### 5.6.3 Contrat de compat SDK

Les SDK v1.x supportent l'API `/api/v1/`. Un SDK v2.x sera livré au moment du passage à `/api/v2/` avec migration guide.

---

## 5.7 Spécification OpenAPI

Le backend expose sa spec OpenAPI 3.1 auto-générée :

- **HTML interactive** — `https://<host>/api/docs` (Swagger UI).
- **JSON brut** — `https://<host>/api/openapi.json`.
- **ReDoc alternative** — `https://<host>/api/redoc`.

Cette spec est **la source technique de vérité** pour les codes/messages/schémas. En cas de divergence entre ce chapitre et OpenAPI, **OpenAPI fait foi** (ce chapitre décrit les invariants, OpenAPI décrit les détails à jour).

Chaque ressource est décrite avec :
- Schémas Pydantic exposés (inputs + outputs).
- Codes d'erreur possibles avec `code` et exemple.
- Exemples de payloads.
- Description Markdown des sémantiques.

---

## 5.8 Sécurité de l'API

### 5.8.1 CORS

Origine autorisée exclusivement via env `CORS_ORIGINS` (liste séparée par virgules). Aucun `*` en production. Headers autorisés : `Authorization, Content-Type, X-Request-Id`.

### 5.8.2 CSRF

Non applicable : API stateless JWT en header. Pas de cookie de session côté navigateur.

### 5.8.3 Content Security Policy

Défini côté frontend (voir chapitre 4 §4.8). La CSP autorise `wss://<self>` pour WebSocket, `blob:` + `mediastream:` pour vidéo.

### 5.8.4 Anti-scraping

Détection basique : > 500 req/min sur endpoints lecture par un même user ⇒ log + notification admin. Blocage automatique désactivé par défaut (faux positifs).

### 5.8.5 Chiffrement au repos

Champs sensibles (mots de passe caméras, secrets MQTT, secrets webhooks, tokens 2FA) chiffrés Fernet avant persistence Mongo (R05).

---

## 5.9 ADR spécifiques aux interfaces

### ADR-08 — URL versioning `/api/v1` au lieu de header `Accept: version=1`

**Contexte** : deux stratégies possibles pour le versioning API.
**Décision** : URL preffix `/api/v1/*`. Explicite, cache-friendly, débuggable avec `curl` sans header, testable sans outils spéciaux.
**Conséquences** : les URLs changent à chaque version majeure. Migration ⇒ mise à jour clients. Overhead léger : coexistence de `/v1` et `/v2` pendant 24 mois.
**Alternatives rejetées** : header (opaque, invisible dans les logs), query param (traité comme feature flag, pas comme version), sous-domaine (complique le DNS/TLS).

### ADR-09 — Erreurs enveloppe `{error: {code, message, details, trace_id}}`

**Contexte** : v2.22.0 utilise FastAPI `HTTPException` qui produit `{detail: "..."}` — non structuré.
**Décision** : enveloppe fixe pour permettre aux clients d'implémenter du switch sur `code` machine-readable.
**Conséquences** : middleware d'erreur uniformisé + refacto des `raise HTTPException(...)` existants. Impact : ~200 lignes de code touchées.
**Alternatives rejetées** : RFC 7807 Problem Details (verbeux, pas plus lisible en pratique).

### ADR-10 — WebSocket single endpoint avec canaux logiques

**Contexte** : possibilité d'endpoints multiples (`/ws/events`, `/ws/alerts`…) ou un seul endpoint multiplexé.
**Décision** : un seul endpoint `/api/v1/ws` avec canaux + filtres côté client. Simplicité de connexion (1 socket, 1 auth), économie de handshakes TLS.
**Conséquences** : la logique de routage est côté serveur. Un client qui ne s'abonne à rien reste connecté mais ne reçoit rien (heartbeat uniquement).
**Alternatives rejetées** : SSE (pas de subscribe côté client), un endpoint par canal (surcharge auth + connexions).

### ADR-11 — Webhooks avec HMAC SHA-256, pas mTLS

**Contexte** : sécurité des webhooks sortants.
**Décision** : HMAC SHA-256 sur `{timestamp}.{body}` + horodatage anti-replay. Simple à vérifier côté receveur (10 lignes Python/JS).
**Conséquences** : chaque receveur doit implémenter la vérification. Doc explicite dans SDK.
**Alternatives rejetées** : mTLS (complexité de gestion des certificats côté intégrateur, blocant pour beaucoup de plateformes SaaS).

---

## 5.10 Écarts avec la v2.22.0

- ⚠ **URL versioning** — actuellement `/api/*`, cible `/api/v1/*` (transition douce).
- ⚠ **Erreurs uniformisées** — actuellement `{detail: str}`, cible `{error: {code, message, details, trace_id}}`.
- ⚠ **WebSocket** — actuellement `/api/ws` sans canaux/filtres, cible avec subscribe + filters + heartbeat structuré.
- ⚠ **MQTT** — non implémenté en v2.22.0, planifié v3.0.
- ⚠ **Webhooks** — non implémenté en v2.22.0, planifié v3.0.
- ⚠ **SDK Python/JS** — non implémenté, planifié v3.1.
- ✅ **JWT + refresh** — en place depuis v2.9.
- ✅ **OpenAPI auto-généré** — en place depuis v1.0 (FastAPI).
- ✅ **Pagination `offset/limit`** — partiellement en place.
- ✅ **CORS whitelist** — en place.

Le rattrapage est planifié dans le chapitre `26-roadmap.md`.

---

## 5.11 Tests d'acceptation

Ces tests, à écrire dans `/app/backend/tests/`, vérifient les invariants de ce chapitre. Ils sont **bloquants CI** pour toute PR.

**Given** un token JWT valide, **When** j'appelle `GET /api/v1/cameras` sans Authorization, **Then** je reçois HTTP 401 avec `{error: {code: "token_missing", ...}}`.

**Given** un endpoint avec `require_permission("admin")`, **When** un user role `view_live` appelle, **Then** HTTP 403 avec `{error: {code: "permission_denied", ...}}`.

**Given** une connexion WebSocket authentifiée, **When** je souscris `{channels: ["event"], filters: {event: {camera_ids: ["X"]}}}`, **Then** je reçois uniquement les événements de la caméra X.

**Given** un webhook configuré avec secret, **When** un événement est déclenché, **Then** le receveur reçoit un POST avec en-tête `X-MGVMS-Signature: sha256=<valid>` vérifiable.

**Given** un client qui envoie 6 POST /auth/login échoués en 60 s, **When** le 7e arrive, **Then** HTTP 429 + en-tête `Retry-After: N`.

**Given** un ObjectId Mongo dans un document interne, **When** ce document est exposé via l'API, **Then** aucun champ `_id` n'apparaît (jamais).

**Given** un endpoint qui retourne 200 éléments, **When** appelé avec `?limit=50`, **Then** la réponse contient `{items: [50], pagination: {total: 200, has_more: true}}`.

**Given** un export CSV, **When** ouvert dans Excel FR, **Then** les caractères accentués sont lisibles (BOM UTF-8 présent).

---

## Annexes

### A. Table complète des codes HTTP par endpoint (extrait)

| Endpoint | 200 | 201 | 400 | 401 | 403 | 404 | 409 | 422 | 429 | 500 | 503 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| POST /auth/login | ✓ | | ✓ | | | | | | ✓ | ✓ | |
| POST /cameras | | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ (go2rtc) |
| GET /cameras/{id} | ✓ | | | ✓ | ✓ | ✓ | | | ✓ | ✓ | |
| DELETE /cameras/{id} | ✓ | | | ✓ | ✓ | ✓ | ✓ (in use) | | ✓ | ✓ | |
| POST /pipeline/webrtc/{id} | ✓ | | ✓ | ✓ | ✓ | ✓ | | | ✓ | ✓ | ✓ |

(Table complète dans OpenAPI.)

### B. Exemple d'intégration curl end-to-end

```bash
# 1. Login
TOKEN=$(curl -s -X POST https://vms.example.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"...."}' \
  | jq -r '.access_token')

# 2. Liste des caméras online
curl -s "https://vms.example.com/api/v1/cameras?status=online&limit=100" \
  -H "Authorization: Bearer $TOKEN" | jq '.items[] | {id, name}'

# 3. Snapshot d'une caméra
curl -s "https://vms.example.com/api/v1/cameras/uuid/snapshot?hd=true" \
  -H "Authorization: Bearer $TOKEN" -o snapshot.jpg

# 4. Événements 24h en CSV
curl -s "https://vms.example.com/api/v1/events?from=2026-07-23&to=2026-07-24&format=csv" \
  -H "Authorization: Bearer $TOKEN" -o events.csv
```

### C. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : 5 surfaces (REST + WS + MQTT + Webhooks + SDK) · versioning · erreurs · rate limit · pagination · CSP · 4 ADR (08→11) · tests d'acceptation |
