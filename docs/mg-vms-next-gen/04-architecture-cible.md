# Chapitre 4 — Architecture cible

> **Version** : v1.0 · **Date** : 2026-07-24 · **Statut** : brouillon en cours de validation
> **Auteur** : équipe MG-VMS · **Reviewers** : *à compléter*
> **Chapitres liés** : `02-philosophie-principes` (invariants) · `05-contrats-interfaces` (détails REST/WS) · `20-diagnostics-intelligents` (observabilité)

Ce chapitre définit l'architecture cible de MG-VMS Next Generation (v3.0). Il fige les **frontières de composants**, les **contrats de communication**, les **modes dégradés** et les **décisions d'architecture (ADR)** qui gouverneront toutes les évolutions ultérieures.

**Note sur la version** : la v1.0 décrivait un backend FastAPI monolithique. La v1.1 (2026-07-24) intègre le pivot architectural fondateur documenté au chapitre 11 : **MG-VMS devient une plateforme dont tout est plugin sauf le noyau** (ADR-15, R16). Les composants « backend » de ce chapitre se lisent maintenant comme « Core + Plugin Manager + plugins officiels ». Voir §4.14 Amendement Plateforme de plugins.

---

## 4.1 Vue macro

MG-VMS NG est un système **distribué à responsabilités séparées**, orchestré par Docker Compose (single-node) ou Kubernetes (multi-node, optionnel v3.5+). Aucun composant n'est bloquant pour un autre : la panne d'un composant est **isolée**, jamais propagée.

```
                     ┌─────────────────────────────────────────────┐
                     │              Navigateur (client)             │
                     │  React SPA · WebRTC · MJPEG · WebSocket · HLS │
                     └──────────────┬──────────────────────────────┘
                                    │ HTTPS + WSS
                                    ▼
┌───────────────────────────────────────────────────────────────────────┐
│                     Reverse-proxy (Traefik / nginx)                    │
│              TLS termination · rate limiting · auth headers            │
└──────┬──────────────────┬──────────────────────┬────────────────────┘
       │ /api             │ /webrtc              │ /media (HLS/MP4)
       ▼                  ▼                      ▼
┌──────────────┐   ┌──────────────┐      ┌──────────────────┐
│   Backend    │   │   go2rtc     │      │  Media Server    │
│   FastAPI    │◄──┤ 1.9.9+       │      │  (HLS · MP4 DL)  │
│   Python 3.11│   │              │      │                  │
└──┬────┬──┬──┘   └──────┬───────┘      └──────────────────┘
   │    │  │              │
   │    │  │              │ RTSP TCP (session unique par caméra)
   │    │  │              ▼
   │    │  │       ┌──────────────────────────────────────┐
   │    │  │       │           Caméras IP                  │
   │    │  │       │  ONVIF · RTSP H.264 · H.265 · MJPEG   │
   │    │  │       └──────────────────────────────────────┘
   │    │  │
   │    │  └──► ┌──────────────────────┐
   │    │      │  Services asynchrones │
   │    │      │  • ai_loop (IA/ANPR)  │
   │    │      │  • recorder (MP4)     │
   │    │      │  • frame_source (GPU) │
   │    │      │  • notifications      │
   │    │      │  • diagnostics loops  │
   │    │      └──────┬───────────────┘
   │    │             │
   │    ▼             ▼
   │  ┌──────────┐  ┌─────────────┐  ┌─────────────┐
   │  │ MongoDB  │  │  Stockage   │  │  GPU (host) │
   │  │ 7.x      │  │  Manager    │  │  NVIDIA     │
   │  │ (state)  │  │  (SSD/NAS)  │  │  NVDEC/CUDA │
   │  └──────────┘  └─────────────┘  └─────────────┘
   │
   ▼ (outbound)
┌──────────────────────────────────────────────────────┐
│  Notifications & intégrations tierces                 │
│  SMTP · Discord · Telegram · MQTT · Webhook · Slack   │
└──────────────────────────────────────────────────────┘
```

**Principes gouvernants** :

1. **Un seul flux RTSP par caméra physique**. `go2rtc` est l'unique consommateur upstream. Viewer, recorder et IA se branchent sur `rtsp://go2rtc:8554/cam_XXX` (session partagée).
2. **La DB MongoDB est source de vérité**. Aucun composant ne stocke d'état persistant en fichier local sauf : segments vidéo (Storage Manager), modèles IA (téléchargés au boot), configuration go2rtc (fichier yaml pour caméras statiques uniquement).
3. **Le backend FastAPI est stateless** entre requêtes HTTP. L'état vit en DB ou en RAM avec reconstruction possible depuis la DB.
4. **Toute panne composant** doit être **détectée < 30 s**, **explicable** en langage humain, **réparable** en 1 clic UI ou 1 commande CLI.

---

## 4.2 Composants et responsabilités

### 4.2.1 Frontend React

**Responsabilité** : rendu de l'interface, aucune logique métier persistante côté client.

**Technos** : React 18 · Vite · TailwindCSS · Shadcn/UI · lucide-react · sonner (toasts).
**Sources vidéo** :
- **WebRTC** (défaut) — H.264 pass-through direct depuis go2rtc, latence 200-500 ms.
- **MJPEG multipart** (fallback) — via proxy backend `/api/stream/{id}/live.mjpeg`, latence 1-2 s.
- **HLS** (mode enregistrement / mobile) — playlist `.m3u8` générée par media server, latence 6-10 s.

**État client** :
- **Session utilisateur** (JWT en `localStorage`).
- **Layouts mur vidéo** (persistés côté serveur, cache localStorage pour offline).
- **Préférences UI** (langue, thème, filtres) — persistés serveur, sync sur login.

**Écart avec la v2.22.0** : le layout du mur vidéo est déjà en RAM client sans persistance serveur systématique — à corriger v3.0.

### 4.2.2 Backend FastAPI

**Responsabilité** : logique métier, API HTTP, orchestration des services asynchrones, autorité sur la DB.

**Technos** : Python 3.11 · FastAPI 0.115+ · Motor (Mongo async) · httpx · asyncio · uvicorn.
**Structure attendue v3.0** :
```
/app/backend/
├── main.py                # entrypoint uvicorn
├── config.py              # settings depuis env
├── database.py            # motor client Mongo
├── auth.py                # JWT + RBAC + audit
├── routes/                # ← modularisation ADR-01
│   ├── cameras.py
│   ├── streams.py
│   ├── events.py
│   ├── ai_config.py
│   ├── diagnostics.py
│   ├── users.py
│   └── ...
├── services/
│   ├── streaming.py       # provisionnement go2rtc
│   ├── frame_source.py    # workers ffmpeg GPU
│   ├── ai_engine.py       # boucle IA (YOLO + ANPR)
│   ├── recorder.py        # subprocess ffmpeg -c copy
│   ├── notifications.py
│   ├── lifecycle.py       # journal transitions
│   └── diagnostics.py
├── models/                # Pydantic + BaseDocument
└── tests/
```

**Boucles asynchrones long-running** :
- `ai_loop` (IA principale, 2 s de période, résilient — cf. v2.21.0).
- `camera_status_loop` (probe non-invasif, 30 s).
- `recorder_supervisor` (surveille les subprocess ffmpeg).
- `notifications_queue` (retry avec backoff).
- `diagnostics_snapshot` (métriques 5 s pour dashboard).

Chaque boucle tourne dans une task asyncio indépendante avec **catch global** — le crash d'une boucle ne tue pas les autres.

### 4.2.3 go2rtc — Unique gateway vidéo

**Responsabilité** : gestion unique du protocole RTSP côté caméra, transcodage MJPEG/HLS, signalisation WebRTC.

**Version cible** : ≥ 1.9.9 (fix crash H.265 `pkg/h265/rtp.go`).
**Configuration** :
- Le fichier `go2rtc.yaml` contient **uniquement** les flux démo statiques et la config transport globale.
- Les caméras utilisateur sont provisionnées **dynamiquement** par le backend via `PUT /api/streams` de l'API go2rtc.
- Aucun credential caméra n'est stocké sur disque go2rtc de façon persistante — ils vivent en RAM go2rtc, re-poussés depuis MongoDB au boot backend.

**Rôle exclusif** : moteur vidéo. **Pas** de logique métier, **pas** de gestion utilisateur, **pas** de stockage d'événements.

**Ports** :
- `1984` — API HTTP (contrôle + signalisation WebRTC).
- `8554` — RTSP (consommateurs internes uniquement : recorder, frame_source).
- `8555 TCP+UDP` — ICE WebRTC (exposé au LAN pour les navigateurs).

### 4.2.4 MongoDB — Source de vérité

**Responsabilité** : stockage persistant de tout l'état applicatif.

**Version** : 7.x. Collections principales :
```
users                 sites                cameras
events                alerts               plates
watchlist_global      camera_diagnostics   audit_logs
settings              storage_pools        recordings_index
faces                 layouts              plugin_configs
stream_lifecycle_journal (rotation 20k docs)
```

**Index critiques** :
- `cameras.id` unique
- `events.{camera_id, timestamp DESC}` composite
- `plates.{plate, timestamp DESC}` composite
- `stream_lifecycle_journal.{camera_id, ts DESC}` + `ts` TTL

**Backup** : dump quotidien automatique par le backend via `mongodump` piped vers Storage Manager (cf. chapitre 22).

### 4.2.5 GPU host

**Responsabilité** : accélération matérielle NVDEC/NVENC (vidéo) + CUDA (inférence IA).

**Requis production** :
- Driver NVIDIA ≥ 550 (CUDA 12.4).
- `nvidia-container-toolkit` installé sur l'hôte.
- Container backend lancé avec `runtime: nvidia` + `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video`.

**Fallback obligatoire** : chaque usage GPU est protégé par un `try/except` + chemin CPU équivalent. Le système fonctionne **entièrement en CPU** si GPU absent (perf dégradée mais fonctionnel).

**Var d'env** :
- `MGVMS_AI_HW_ACCEL=auto|cuda|none` — mode ffmpeg NVDEC.
- `MGVMS_AI_FORCE_CPU=1` — bypass GPU IA (troubleshooting rapide).

### 4.2.6 Storage Manager

**Responsabilité** : abstraction des supports de stockage (local, NAS, iSCSI, cloud) pour l'enregistrement vidéo et les archives.

**Type de pools** : SSD/HDD/NVMe local · NFS · SMB/CIFS · iSCSI · S3 (v3.5+).
**Politiques** : rotation, compression, migration chaud→froid, benchmark SMART.

**Détail** : chapitre `16-storage-manager.md`.

### 4.2.7 Reverse-proxy

**Responsabilité** : terminaison TLS, routage `/api` → backend, `/webrtc` → go2rtc, `/media` → media server, rate limiting, headers auth.

**Techno cible** : Traefik 3 (recommandé) ou nginx.
**Certificats** : Let's Encrypt automatique (Traefik) ou pré-provisionnés.
**Sécurité** : HSTS, CSP stricte, refus HTTP 1.0, timeout 60 s en lecture upstream.

### 4.2.8 Services externes

Le backend est **cliente** de ces services, jamais serveur. Ils sont **optionnels** — leur absence ne bloque pas le VMS.

| Service | Usage | Panne = |
|---|---|---|
| SMTP | Notifications mail | Alertes conservées en DB, retry auto |
| Discord/Telegram/Slack | Push instantané | Idem |
| MQTT broker | Automatisation IoT | Actions locales OK, IoT désactivé |
| LDAP/AD | Authentification entreprise | Fallback compte local admin |
| OIDC | SSO | Fallback JWT local |

---

## 4.3 Contrats de communication

### 4.3.1 Frontend ↔ Backend

**REST** — préfixe `/api`, JSON, JWT Bearer.
Verbes standards, codes HTTP standards, pagination `?offset=&limit=`, filtres par query.
Documenté via OpenAPI 3 auto-généré (FastAPI `/api/docs`).

**WebSocket** — endpoint unique `/api/ws?token=<jwt>`, canaux logiques :
- `event` — événements IA temps-réel
- `alert` — alertes critiques
- `metric` — métriques CPU/RAM/GPU/STO (broadcast 5 s)
- `camera_status` — changements online/offline
- `stream_lifecycle` — journal transitions (technicien)

Format message : `{channel, timestamp, payload}`.

### 4.3.2 Backend ↔ go2rtc

**HTTP REST** — API go2rtc `http://go2rtc:1984/api/*`.
- `GET /streams` — liste des flux enregistrés
- `PUT /streams?name=X&src=rtsp://...` — provision
- `DELETE /streams?src=X` — retrait
- `POST /webrtc?src=X` — négociation SDP
- `GET /frame.jpeg?src=X` — snapshot (usage démo uniquement, jamais sur caméra réelle en production — cf. ADR-03)

**Signalisation WebRTC** — le backend proxifie l'offer/answer entre navigateur et go2rtc pour centraliser l'auth. Le média RTP passe **direct navigateur ↔ go2rtc** sur `:8555`.

### 4.3.3 Backend ↔ Caméras

**AUCUNE connexion RTSP directe** depuis le backend vers les caméras IP en production.
- La provision go2rtc est faite via `PUT /streams` — go2rtc ouvre ensuite la session RTSP.
- Le seul appel direct autorisé est `ffprobe` **ponctuel** lors du test-connectivity, jamais persistant.

**ONVIF** — SOAP via `onvif-zeep`, appels `GetDeviceInformation` / `GetProfiles` / `GetStreamUri` / `GetSnapshotUri`. Timeouts 25 s (v2.20.0 tuning). Optionnel : `GetSystemDateAndTime` pour vérifier la dérive d'horloge.

**PTZ** — chapitre `14-ptz.md`.

### 4.3.4 Backend ↔ MongoDB

**Motor async** exclusivement. Pas de driver synchrone. Toute méthode qui touche `db.*` est `async`.
Contrat `BaseDocument` avec `PyObjectId` (cf. règle MongoDB adherence transverse).

### 4.3.5 Backend ↔ Notifications externes

**Queue asyncio** avec retry backoff (1 s, 2, 4, 8, 16, 32, dead-letter). Journal en DB (`notification_logs`) pour audit.

---

## 4.4 Flux de données par cas d'usage

### 4.4.1 Provisionnement d'une caméra (création)

```
UI /cameras → POST /api/cameras
  ↓
Backend valide + ONVIF discover + ffprobe validation
  ↓
Insert Mongo db.cameras
  ↓
streaming.register_camera_stream(cam)
  ↓
PUT go2rtc /api/streams?name=cam_XXX + variants _hd/_sd
  ↓
Return HTTP 201 + camera document
  ↓
UI navigate to /cameras (liste)
  ↓
Async: probe status → lifecycle → online
  ↓
Async: si detect_enabled → ai_engine._sync_frame_source_workers start worker ffmpeg
```

### 4.4.2 Consommation live viewer (WebRTC)

```
UI /live → composant WebRTCPlayer monte
  ↓
new RTCPeerConnection + ICE gathering
  ↓
POST /api/pipeline/webrtc/{cam_id} avec SDP offer
  ↓
Backend proxifie → go2rtc /api/webrtc?src=cam_XXX
  ↓
go2rtc renvoie SDP answer
  ↓
Backend renvoie answer au navigateur
  ↓
ICE negotiation navigateur ↔ go2rtc:8555 (direct)
  ↓
Média RTP H.264 pass-through → <video>
```

**Fallback** — si ICE échoue en 5 s (typiquement infra sans UDP LAN) : bascule automatique sur MJPEG multipart via `/api/stream/{id}/live.mjpeg`.

### 4.4.3 Pipeline IA

```
ai_loop (period=2s) → refresh cameras + configs
  ↓
_sync_frame_source_workers(cams)
  → start ffmpeg workers manquants (URL = rtsp://go2rtc:8554/cam_XXX ← invariant Phase 1)
  → stop workers stales
  ↓
asyncio.gather([_process_camera(cam) for cam in cams])
  ↓ (par caméra, parallèle)
  _fetch_frame → frame_source.get_latest_frame (numpy BGR24, zéro-copie)
  ↓
_analyze_frame → motion + YOLO + (si véhicule) ALPR
  ↓
Si event → insert db.events + broadcast_event WS
Si scenario match → insert db.alerts + notification
Si plate → insert db.plates + éventuel blacklist alert
```

### 4.4.4 Enregistrement continu

```
recorder_supervisor (period=15s) → find cameras record_enabled=True
  ↓
Pour chaque cam : subprocess ffmpeg -i rtsp://go2rtc:8554/cam_XXX -c copy
  → segments MP4 de 120s dans le pool storage désigné
  ↓
Chaque segment fermé → insert db.recordings_index
  ↓
Rétention : cleanup job (period=1h) purge segments > retention_days
  ↓
Alerte "STO saturé" si free_gb < min_free_gb
```

### 4.4.5 Diagnostic « pourquoi cette caméra est rouge ? »

```
UI /cameras → clic caméra offline → dialog diagnostic
  ↓
GET /api/diagnostics/camera/{id}/summary
  ↓
Backend agrège :
  • dernier lifecycle log
  • dernier probe result + raison
  • dernier incident enregistré (30j)
  • MTBF calculé
  • cause probable via CAUSE_RULES (18 patterns regex)
  • extrait logs backend + go2rtc filtrés sur la caméra
  ↓
UI affiche : cause probable en français + timeline + action recommandée
```

**Aucun voyant rouge orphelin.** Toute LED rouge dans l'UI doit être cliquable et donner **la** raison en langage humain.

---

## 4.5 Principes de robustesse

### 4.5.1 Bulkheads (cloisonnement)

Chaque service asynchrone tourne dans une task asyncio indépendante avec `try/except` global. Le crash d'une boucle est logué, la boucle redémarre, les autres continuent.

### 4.5.2 Circuit breakers

Les appels vers services externes (SMTP, Discord, MQTT) utilisent un pattern circuit breaker :
- Après 5 échecs consécutifs → circuit ouvert 60 s (skip appel).
- Après ouverture → 1 tentative test toutes les 60 s → si OK, circuit fermé.

### 4.5.3 Retry avec backoff

Standard : `1s, 2s, 4s, 8s, 16s, 32s, dead-letter`. Après dead-letter, l'opération est enregistrée dans `db.failed_operations` pour retraitement manuel.

### 4.5.4 Timeouts explicites

**Aucun appel réseau sans timeout.** Défauts :
- HTTP client interne (go2rtc, backend) : 6 s
- ONVIF SOAP : 25 s
- ffprobe caméra : 12 s
- MongoDB motor : 10 s (server selection)
- Notification externe : 15 s

### 4.5.5 Idempotence

Toute action de provisionnement est idempotente :
- `register_camera_stream` compare l'état go2rtc actuel et skippe le DELETE+PUT si identique (cf. v2.17.0).
- `_ensure_variants` crée uniquement les variantes manquantes.
- `sync_all_streams` peut être appelé N fois sans effet de bord.

### 4.5.6 Health checks

Chaque service expose un endpoint de santé :
- `GET /api/health` — liveness (le backend répond).
- `GET /api/health/ready` — readiness (Mongo joignable, go2rtc joignable).
- `GET /api/diagnostics/ai-health` — état pipeline IA.
- `GET /api/diagnostics/streams-sync` — réconciliation DB ↔ go2rtc.
- `GET /api/diagnostics/frame-source` — workers ffmpeg GPU.

---

## 4.6 Modes dégradés par composant

| Composant | Panne | Comportement système |
|---|---|---|
| Une caméra | RTSP timeout / auth KO | Caméra passe offline (hystérésis 3 échecs), autres caméras intactes, IA saute cette caméra |
| go2rtc | Container down | Live viewer et recorder KO, backend continue à servir /api, alertes historiques consultables, `streams-sync` détecte, bouton "Resynchroniser" propose |
| MongoDB | Timeout | Backend renvoie 503 avec message clair, UI affiche bandeau "Base de données injoignable — reconnexion en cours", ai_loop pause avec retry |
| GPU | NVDEC indispo | frame_source fallback CPU auto, log warning, IA continue sans crash |
| GPU | CUDA indispo pour torch | YOLO tourne sur CPU (5-10× plus lent), badge orange dans UI |
| Module IA (YOLO) | crash chargement modèle | `_ai_health.yolo_loaded=false`, retry chaque cycle, ANPR/mouvement continuent |
| Module IA (ALPR) | crash | idem, YOLO continue |
| Recorder ffmpeg | subprocess mort | supervisor relance dans les 15 s, gap dans le segment MP4 (documenté) |
| SMTP/Discord | non joignable | Circuit breaker, alertes en queue, notification dashboard "N alertes non délivrées" |
| Reverse-proxy | crash | Système inaccessible depuis l'extérieur — restart auto Docker attendu < 30 s |

**Règle absolue** : **aucune de ces pannes ne doit propager un crash à un autre composant.**

---

## 4.7 Modèles de déploiement

### 4.7.1 Single-node (défaut v3.0)

Docker Compose sur une machine unique (Ubuntu 22.04+, ≥ 16 GB RAM, GPU NVIDIA optionnel).
Convient jusqu'à ~100 caméras 2 Mpx.

```
services:
  mongo, go2rtc, backend, frontend, traefik
```

### 4.7.2 Multi-node (v3.5+, optionnel)

Kubernetes ou Docker Swarm. Séparation :
- Nœud « ingest » (go2rtc + storage local NVMe) proche des caméras.
- Nœud « inference » (GPU + backend workers IA).
- Nœud « API » (backend REST + frontend).
- Nœud « data » (MongoDB replica set).

Non prioritaire pour v3.0.

---

## 4.8 Sécurité transverse

**Voir aussi** : chapitre `22-administration-rbac.md` pour le détail.

Invariants d'architecture :
- **TLS partout** en production (Let's Encrypt automatique).
- **JWT courts** (15 min access + 7 j refresh) avec rotation.
- **Mots de passe caméras** : chiffrés en DB (fernet key en env), jamais loggés en clair.
- **Audit log** : toute action admin loguée (`db.audit_logs`) avec user, IP, timestamp, résultat.
- **Rate limiting** : 60 req/min sur `/api/auth/login`, 300 req/min sur les autres endpoints.
- **CSP stricte** : `default-src 'self'; media-src 'self' blob: mediastream:`.
- **CORS** : whitelist explicite via `CORS_ORIGINS` env (jamais `*` en production).

---

## 4.9 Extensibilité

### 4.9.1 Ajouter un service backend

1. Créer un fichier dans `services/`.
2. Exposer une fonction async publique (ex. `async def start_service()`).
3. L'enregistrer dans `main.py::startup_event`.
4. Ajouter une entrée dans `/api/health/ready` si dépendance critique.
5. Documenter dans le chapitre correspondant du cahier.

### 4.9.2 Ajouter un module IA

1. Créer `services/ai_modules/{module_name}.py` avec :
   - `async def load()` — chargement modèle (résilient, log erreur).
   - `async def analyze(frame_bgr, cam) -> ModuleResult` — inférence pure.
2. Enregistrer dans `ai_engine._registered_modules`.
3. Ajouter le toggle par caméra dans le schéma `cameras.ai_modules[]`.
4. Ajouter la config UI dans `AjoutCamera` (checkbox).

Détail : chapitre `11-moteur-ia-modulaire.md`.

### 4.9.3 Ajouter une intégration tierce

1. Créer `services/integrations/{provider}.py` avec interface `Notifier` (send, test_connection).
2. Enregistrer dans `notifications.PROVIDERS`.
3. Ajouter les settings correspondants dans `db.settings`.
4. Documenter dans `25-integrations-tierces.md`.

---

## 4.10 Décisions d'architecture (ADR)

### ADR-01 — Modularisation `routers.py` en `routes/`

**Contexte** : `routers.py` dépasse 1600 lignes en v2.22.0, mélange 15+ domaines fonctionnels.
**Décision** : découpage en `routes/{cameras,streams,events,ai_config,diagnostics,users,plugins,...}.py`, chaque fichier < 300 lignes, `main.py` fait `include_router()` pour chacun.
**Conséquences** : ~ 1 semaine de refacto, tests de non-régression obligatoires (100% API contract).
**Alternatives rejetées** : garder monolithique (illisible), microservices (over-engineered pour la taille du projet).

### ADR-02 — go2rtc = unique gateway RTSP

**Contexte** : sans invariant, plusieurs composants (viewer, recorder, IA) risquent d'ouvrir chacun une session RTSP directe → limites de sessions caméra dépassées.
**Décision** : le backend n'ouvre **jamais** de connexion RTSP directe vers une caméra IP. Tout passe par `rtsp://go2rtc:8554/cam_XXX`. Enforcement via garde-fou dans `frame_source.start()` (cf. v2.21.0).
**Conséquences** : simplicité mentale, 1 seule session par caméra, meilleure compatibilité multi-consommateurs.
**Alternatives rejetées** : ffmpeg direct multiple (chaotique), reverse-proxy RTSP custom (réinventer go2rtc).

### ADR-03 — DB MongoDB = source de vérité unique

**Contexte** : 3 options envisagées pour la config caméra (DB seule, `go2rtc.yaml` généré, `go2rtc.yaml` manuel).
**Décision** : DB reste maître. `go2rtc.yaml` contient uniquement les flux démo statiques. Les caméras utilisateur sont poussées dynamiquement à go2rtc via `PUT /api/streams`. Réconciliation DB ↔ go2rtc via `/api/diagnostics/streams-sync` + bouton "Resynchroniser".
**Conséquences** : aucune duplication d'état, workflow ONVIF/test-connectivity/UI 100% intégré, un `docker restart go2rtc` déclenche une re-provision automatique au boot backend.
**Alternatives rejetées** : (b) yaml généré (rechargement go2rtc à chaque modif = coupure flux) · (c) yaml manuel (perte du workflow ONVIF intégré, 2 UIs à maintenir).

### ADR-04 — `frame.jpeg` interdit en production sur caméras réelles

**Contexte** : `GET /api/frame.jpeg?src=cam_XXX` sur go2rtc **force une session RTSP à la demande** vers la caméra + décodage H.265 CPU → churn de sessions + timeouts sous charge.
**Décision** : `frame.jpeg` est autorisé **uniquement** sur les caméras démo (générées localement par go2rtc). Pour les caméras réelles, l'IA lit depuis `frame_source.get_latest_frame` (numpy BGR, worker ffmpeg persistant partagé). Le probe de statut utilise `bytes_recv` delta (non invasif) ou TCP check en fallback (cf. v2.20.0).
**Conséquences** : suppression du churn de sessions caméra, IA à 5-15 fps stable.
**Alternatives rejetées** : `frame.jpeg` polling avec cache (patch superficiel, ne règle pas le fond).

### ADR-05 — `ai_loop` ne s'auto-désactive JAMAIS

**Contexte** : un crash de `_load_models` au boot suicidait la boucle IA définitivement (cf. régression v2.18 GPU).
**Décision** : `ai_loop` capture toute exception au boot, continue à tourner, retente le chargement des modèles à chaque cycle. YOLO et ALPR sont chargés indépendamment. `_ai_health` expose l'état exact via `/api/diagnostics/ai-health` (cf. v2.21.0).
**Conséquences** : plus aucune régression silencieuse post-rebuild. Diagnostic prod en 1 curl.
**Alternatives rejetées** : health check externe qui restart le backend (masque le problème, ne le résout pas).

### ADR-06 — Aucun secret en clair sur disque

**Contexte** : mots de passe caméras stockés en clair en DB v2.x.
**Décision** : chiffrement Fernet (clé en var d'env `MGVMS_ENCRYPTION_KEY`) pour tous les champs sensibles avant persistence Mongo. Clé rotable (rekey batch).
**Conséquences** : ~ 3 jours de refacto (migration data + tous les callers).
**Alternatives rejetées** : Vault (over-engineered v3.0, envisageable v3.5).

### ADR-07 — Contrat de test acceptation par module

**Contexte** : les tests actuels sont majoritairement des tests HTTP contre le backend en cours. Utiles mais insuffisants pour un cahier des charges prescriptif.
**Décision** : chaque module fonctionnel du cahier définit **ses** tests d'acceptation en Given/When/Then dans son chapitre. L'implémentation doit passer ces tests avant merge sur `main`.
**Conséquences** : dette de test à combler progressivement. Pas de code sans test spec.
**Alternatives rejetées** : « tests suffisants tant que ça marche » (dérive garantie).

---

## 4.11 Écarts avec la v2.22.0 (état actuel)

À date du 2026-07-24, la v2.22.0 respecte les principes suivants :
- ✅ go2rtc = unique gateway (ADR-02) — enforcement `frame_source.start()`
- ✅ DB source de vérité (ADR-03) — réconciliation en place
- ✅ `frame.jpeg` restreint aux démos (ADR-04) — probe non-invasif
- ✅ `ai_loop` résilient (ADR-05) — health endpoint en place
- ⚠ **Modularisation `routes/`** (ADR-01) — pas fait, `routers.py` = 1620 lignes
- ⚠ **Chiffrement des credentials caméra** (ADR-06) — stockage clair actuellement
- ⚠ **Bulkheads formalisés** — plusieurs boucles asyncio existent mais sans catch global systématique
- ⚠ **Circuit breakers** — absents (notifications font retry simple)
- ⚠ **Structure `services/` vs racine** — modules mixtes en racine, à réorganiser
- ⚠ **Multi-node** — non applicable, docker-compose single-node uniquement

Ces écarts constitueront le backlog de refacto **v3.0** décrit chapitre `26-roadmap.md`.

---

## 4.12 Métriques de succès de l'architecture

Une architecture est *bonne* quand elle satisfait les KPIs suivants :

**Fiabilité** :
- MTBF système ≥ 30 jours (temps entre incidents bloquants).
- 99.5% uptime backend (hors maintenance planifiée).
- 0 crash cascade en 12 mois de prod (une panne composant ne se propage pas).

**Performance** :
- Latence live WebRTC ≤ 500 ms P95.
- Latence détection IA (frame → alerte WS) ≤ 3 s P95.
- Ingestion RTSP jusqu'à 200 caméras 2 Mpx sur un serveur RTX A2000.

**Observabilité** :
- 100% des voyants rouges UI ont une explication humaine cliquable.
- Diagnostic caméra HS → cause probable en ≤ 3 clics.
- Journal lifecycle rétention 20 000 entrées (~ 15-30 jours en prod normale).

**Maintenabilité** :
- Aucun fichier Python > 500 lignes en `services/` v3.0.
- Coverage tests ≥ 70% sur `services/` et `routes/`.
- Delta build Docker < 30 s pour un changement backend hors deps.

---

## 4.13 Prochaines étapes de conception

- **Chapitre 5** — Contrats d'interface détaillés (schémas REST par ressource, formats WS, événements MQTT).
- **Chapitre 2** — Philosophie & principes (formaliser les invariants du § 4.5 en règles produit).
- **Chapitre 20** — Diagnostics intelligents (approfondir le principe « aucun voyant rouge orphelin » du § 4.4.5).

---

## Annexes

### A. Glossaire

- **NVR** — Network Video Recorder (usage grand public), synonyme de VMS ici.
- **NVDEC** — décodeur vidéo matériel NVIDIA (H.264/H.265 → RAM ou VRAM).
- **NVENC** — encodeur vidéo matériel NVIDIA.
- **RTSP** — Real Time Streaming Protocol (RFC 2326).
- **WebRTC** — Web Real-Time Communication (H.264/VP8/VP9 P2P bas-latence).
- **HLS** — HTTP Live Streaming (playlist .m3u8 + segments .ts).
- **ONVIF** — Open Network Video Interface Forum (standard SOAP caméras IP).
- **Bulkhead** — pattern d'isolation de pannes issu de l'architecture navale.
- **ADR** — Architecture Decision Record.
- **Core** — noyau MG-VMS, code obligatoire, minimal (v3.0 : ~5000 lignes).
- **Plugin** — module optionnel activable indépendamment, cf. chapitre 11.

## 4.14 Amendement Plateforme de plugins (v1.1 — 2026-07-24)

Après validation du chapitre 4 v1.0, le chapitre 11 (Plateforme de plugins) a introduit un pivot architectural fondateur qui **précise** ce chapitre sans le contredire. Les composants « backend » et « services asynchrones » du §4.2.2 se lisent désormais comme :

**Backend = Core + Plugin Manager**

Le **Core** (~5000 lignes Python cible) contient :
- Gestion utilisateurs & permissions (auth, RBAC, audit)
- Gestion caméras (CRUD, ONVIF, RTSP, PTZ base)
- Provisionnement go2rtc
- Recorder (subprocess ffmpeg)
- Player + timeline
- API HTTP + WebSocket
- Dashboard KPIs de base
- Plugin Manager (loader, sandbox, health)

Les **Plugins** officiels bundlés v3.0 :
- `yolo-detection` (remplace `ai_engine.py` YOLO)
- `fast-alpr` (remplace `ai_engine.py` ALPR)
- `smtp-notifier`, `discord-notifier`, `telegram-notifier`
- `zone-analytics` (crossline, zones, loitering — remplace scenarios v2.22)

Les **Plugins tiers** (Marketplace) : parking, heatmap, MQTT, Home Assistant, LDAP, OIDC, S3, PaddleOCR, OpenALPR, face recognition, smoke, fire, PPE, counting, weapon detection, animal detection, crowd, pose estimation, KNX, BACnet, Modbus…

Le §4.5 (Principes de robustesse) s'applique désormais **à chaque plugin** : un plugin qui crash ne fait jamais tomber le core (R01 + R16).

Le §4.6 (Modes dégradés) reçoit une ligne supplémentaire :

| Composant | Panne | Comportement système |
|---|---|---|
| Un plugin FrameAnalyzer | Crash chargement modèle / analyze() | Plugin en état `crashed`, restart auto (backoff), core inchangé, autres plugins de la caméra continuent |
| Un plugin EventConsumer | Timeout appel externe | Circuit breaker plugin, retry backoff, alertes accumulées dans plugin queue |
| Le Plugin Manager | Crash critique | Restart auto (superviseur), plugins in-process rechargés, sub-process/container plugins auto-reconnectés |
| Signature plugin invalide | Installation bloquée | Refus explicite avec message clair, plugin non installé, aucun impact système |

Le §4.9 (Extensibilité) est simplifié : **ajouter une fonctionnalité = écrire un plugin**. Les procédures actuelles (« ajouter un service backend », « ajouter un module IA », « ajouter une intégration tierce ») sont **fusionnées** en une seule procédure documentée au chapitre 11 (§11.8 SDK multi-langages + §11.7 Marketplace).

Le §4.10 (ADR) accueille ADR-15 → ADR-19 documentés au chapitre 11. Ces ADR ne remplacent pas ADR-01 → ADR-14 mais s'y ajoutent — la modularisation `routes/` (ADR-01) reste valable pour le core lui-même.

Le §4.11 (Écarts avec v2.22.0) reçoit une ligne majeure : **le Plugin Manager n'existe pas en v2.22.0**. Sa création est le chantier structurant v3.0 (cf. chapitre 26 Roadmap).

### C. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale |
| v1.1 | 2026-07-24 | équipe MG-VMS | Amendement Plateforme de plugins (§4.14) suite validation chapitre 11 : refonte Core + Plugin Manager, ADR-15→ADR-19 ajoutés, modes dégradés étendus aux plugins |
