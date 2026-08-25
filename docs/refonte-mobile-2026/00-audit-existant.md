# MG-VMS — Audit de l'existant & architecture cible (refonte mobile / multi-sites / Cloud optionnel)

> **Statut** : Phase 1 (AUDIT) — aucun code modifié à ce stade.
> **Base auditée** : dépôt local `mg-vms-app`, branche `fix/video-ocr-recording-gros-fix`, HEAD `7e245be`, produit `v3.9.2-apercu-fiabilite`.
> **Date** : 2026-08-25.

---

## 1. Architecture actuelle

```
                         ┌──────────────────────────────┐
   Navigateur ──HTTP/S──►│ mgvms-frontend (nginx:80/443)│
                         │  React 19 build statique     │
                         │  proxy /api /ws → backend    │
                         └───────────┬──────────────────┘
                                     │ same-origin
                         ┌───────────▼──────────────────┐
                         │ mgvms-backend (FastAPI)      │
                         │ uvicorn --workers 1  ⚠       │
                         │  ├ API REST (356 routes)     │
                         │  ├ WebSocket /api/ws         │
                         │  ├ ai_loop (pipeline_v2)     │
                         │  ├ recorder_loop (ffmpeg)    │
                         │  ├ camera_status_loop        │
                         │  ├ qos_watcher / stability   │
                         │  └ webrtc_gateway (aiortc)   │
                         └──┬────────────┬──────────┬───┘
                            │            │          │
                  ┌─────────▼──┐  ┌──────▼─────┐  ┌─▼──────────────┐
                  │mgvms-mongo │  │mgvms-go2rtc│  │ GPU (NVDEC/    │
                  │  Mongo 7   │  │  1.9.9     │  │ NVENC + CUDA)  │
                  └────────────┘  └──────┬─────┘  └────────────────┘
                                         │ RTSP/ONVIF/HTTP(S)
                                  ┌──────▼──────┐
                                  │  Caméras    │
                                  └─────────────┘
```

**Constat majeur, et bonne nouvelle : la contrainte n°1 du cahier des charges est déjà respectée.**
Le serveur MG-VMS est **totalement autonome**. Recherche exhaustive : aucune référence à un
service cloud MG-VMS, aucun `tenant`, aucune `organization`, aucun appel sortant obligatoire.
Les seuls appels sortants existants sont **optionnels et déjà désactivables** : SMTP, Discord,
Telegram (notifications), Let's Encrypt (TLS), `EMERGENT_LLM_KEY` (Smart Search — renvoie
`503 SMART_SEARCH_LLM_NOT_CONFIGURED` si absent, sans casser la page Événements).
Il n'y a donc **rien à démolir** côté autonomie : il faut *ne pas la casser*.

**Constat bloquant : un seul process Python porte tout.**
`uvicorn --workers 1` (choix documenté dans le `Dockerfile` : « pipeline IA garde l'état en
mémoire »). L'API HTTP, les WebSockets, la boucle IA, l'enregistreur et la passerelle WebRTC
partagent le même GIL. Le `docker-compose.yml` en porte lui-même la trace :

> « `AI_INTERVAL_SECONDS` 0.15s (~6-7 fps/cam) sature le GIL du seul process Python qui sert
> aussi l'API HTTP, causant des latences aléatoires de plusieurs secondes sur **n'importe quel**
> endpoint pendant les cycles IA. »

C'est le point qui bloque simultanément l'objectif §36 (64 → 200 caméras) **et** l'expérience
mobile visée (une app mobile pardonne beaucoup moins une API qui gèle 3 s qu'un écran de bureau).

---

## 2. Arborescence du projet

```
mg-vms-app/
├── backend/                       34 806 LOC Python (hors tests)
│   ├── server.py                  bootstrap FastAPI, 36 routers, startup/shutdown
│   ├── routers.py         (2251)  ⚠ god-module : sites, caméras, events, plates, alerts,
│   │                              recordings, exports, pipeline, retention, MQTT…
│   ├── streaming.py       (2395)  ⚠ god-module : go2rtc, ffprobe, MJPEG, ONVIF, PTZ, probe
│   ├── auth.py             (735)  JWT, RBAC, 2FA, lockout, sessions
│   ├── database.py                Motor + create_indexes()
│   ├── ai_engine.py        (876)  acquisition + modèles + ai_loop
│   ├── frame_source.py     (509)  ffmpeg NVDEC → frames IA
│   ├── recorder.py         (608)  enregistrement ffmpeg -c copy
│   ├── realtime.py                WebSocket /api/ws + broadcast métriques
│   ├── pipeline_v2/        (16 f) CameraWorker, FrameContext, stages, tracking, ANPR
│   ├── plugin_manager/     (12 f) bus, loader, registry, policy, fusion, sandbox
│   ├── plugin_sdk/                scaffold + packaging de plugins
│   ├── video_core/                RTSP natif PyAV + runtime + manager
│   ├── webrtc_gateway/            aiortc WHEP
│   ├── drivers/            (8 f)  ONVIF, Reolink, Hikvision, Dahua
│   ├── camera_api/         (8 f)  couche HTTP/HTTPS constructeur
│   ├── routes/             (27 f) modularisation progressive de routers.py
│   ├── services/, smart_zones/, workflow_engine/, stress/, scripts/
│   └── tests/              (94 f) pytest
├── frontend/
│   └── src/
│       ├── App.js                 49 pages, 57 routes React
│       ├── components/            Layout, EventViewer, LivePlayer, ui/ (shadcn, 44 f)
│       ├── context/AppContext.jsx état global (user, thème, langue, alertPing)
│       ├── lib/api.js             axios + refresh token + ring buffer debug
│       ├── i18n.js         (970)  FR/EN
│       └── pages/          (49 f) dont 9 pages « pipeline* » de diagnostic
├── data/plugins/                  47 plugins (IA, OCR, tracking, notifiers, métier)
├── deploy-app/                    docker-compose.yml, install.sh (29 Ko), nginx.conf, go2rtc.yaml
├── docs/mg-vms-next-gen/          cahier des charges v3.0 antérieur (28 chapitres, partiel)
├── docker/, scripts/, bin/, media/, benchmarks/, test_reports/
└── CHANGELOG.md                   258 Ko, 91 versions
```

---

## 3. Technologies utilisées

| Couche | Stack | Remarque |
|---|---|---|
| Backend | FastAPI, Starlette, uvicorn, Pydantic v2 | mono-process |
| DB | MongoDB 7 via Motor (async) | 53 collections, aucun schéma formel |
| Auth | PyJWT HS256, bcrypt, pyotp | access 8 h / refresh 7 j |
| Vidéo | go2rtc 1.9.9, aiortc 1.9 + PyAV 12.3, ffmpeg statique | WHEP + MJPEG + `-c copy` |
| IA | torch 2.4.1+cu124, ultralytics, fast-alpr, easyocr, PaddleOCR, tesseract, ONNX | GPU NVIDIA |
| Caméras | onvif-zeep (WSDL embarqué), httpx, drivers Reolink/Hikvision/Dahua | |
| Frontend | React 19, **CRA + craco** (react-scripts 5), Tailwind 3, Radix/shadcn, react-router 7 | ⚠ CRA non maintenu |
| État client | axios + **swr** + **@tanstack/react-query** | ⚠ trois mécanismes concurrents |
| Divers front | recharts, konva, framer-motion, react-window, sonner, dayjs, zod | |
| Infra | Docker Compose, nginx, CUDA 12.4 runtime, NVIDIA Container Toolkit | 4 conteneurs |
| Deps | 234 paquets Python figés, ~70 paquets npm | |

---

## 4. Fonctionnalités existantes (à conserver intégralement)

**Vidéo & caméras** — ajout RTSP/ONVIF, découverte WS-Discovery, sonde ONVIF/ffprobe,
génération d'URL RTSP par constructeur, bascule H.264/H.265, sous-flux, PTZ (move/zoom/presets),
IR/projecteur/sirène, mur vidéo 1/4/9/16 + focus clavier, plein écran, snapshot, HD/SD, Centre
caméras par appareil, benchmark caméra, advisor.

**Enregistrement** — enregistrement continu ffmpeg `-c copy` (qualité native, jamais réencodée),
timeline, lecture avec Range/206, transcodage HEVC→H264 **à la demande** pour la lecture
navigateur, exports, rétention configurable, pools de stockage + affectation par caméra.

**IA** — YOLO (personne/véhicule/animal), ANPR multi-moteurs avec vote/fusion, reconnaissance
faciale, ByteTrack/BoTSORT/DeepSORT/OCSort/StrongSort, zones intelligentes, franchissement de
ligne, intrusion, comptage, dwell time, heatmap, détections métier (feu, fumée, arme, chute,
EPI, retail…), 47 plugins avec bus, policy, sandbox, quarantaine, hot-reload, SDK et packaging.

**Événements & alertes** — événements IA, plaques, alertes avec acquittement, feedback,
watchlist, règles d'alerte, armement, recherche véhicule, recherche sémantique (LLM optionnel),
EventViewer avec ré-analyse OCR sur zone tracée manuellement.

**Administration** — utilisateurs, RBAC (rôles + permissions + overrides), MFA, sessions actives
révocables, journal d'audit, TLS/HTTPS (Let's Encrypt + self-signed + upload), licence, base de
données, sauvegardes, matériel, réseau (ping/poll), GPU, diagnostics multi-étages, health
dashboard, Ops/QoS, stability watcher, chaos testing, rapports, workflows, MQTT, webhooks,
notifications (SMTP/Discord/Telegram), Welcome Center, cartes et plans de site.

**Total : 356 routes API, 49 pages, 47 plugins, 94 fichiers de tests.**

---

## 5. API existante

36 routeurs, tous sous `/api`. **Un middleware ASGI accepte déjà `/api/v1/*` en alias**
(`ApiVersionAliasMiddleware` dans `server.py`, header `X-API-Version-Alias: v1`) — la cible §31
du cahier des charges est donc à moitié atteinte, sans casser la compatibilité.

| Préfixe | Rôle | Routes |
|---|---|---|
| `/api/auth/*` | login, refresh, logout, me, register, forgot/reset, 2FA | 11 |
| `/api` (core, `routers.py`) | sites, caméras, events, plates, alerts, recordings, exports, pipeline, IA, diagnostics | 73 |
| `/api` (`health_dashboard`) | santé services, caméras, workers | 39 |
| `/api/plugins/*` | config plugins globale + par caméra | 48 |
| `/api/devices/*` | contrôles physiques (IR, lumière, sirène, PTZ, encodage) | 25 |
| `/api/vehicles/*` | ANPR, identités, recherche, validations, vignettes | 21 |
| `/api/camera-devices/*` | couche HTTP/HTTPS constructeur | 16 |
| `/api/welcome/*` | Welcome Center, news, prefs, tutoriels, widgets | 13 |
| `/api/site-manager/*` | bâtiments, plans, positions | 12 |
| `/api/security/*` + `/api/security/tls/*` | RBAC, timeout, TLS | 18 |
| `/api/live/*` | status / start / stop / **WHEP** | 4 |
| `/api/stream/*` | `live.mjpeg`, `frame.jpeg`, marques, auto-détection | 9 |
| `/api/discovery`, `/storage`, `/network`, `/reports`, `/hardware`, `/users`, `/workflows`, `/smart-zones`, `/timeline`, `/smart-search`, `/notifications`, `/audit`… | | ~55 |
| `/api/system/public-status` | **non authentifié**, agrégats seulement | 1 |
| `/api/ws` | WebSocket unique | 1 |

`GET /api/system/public-status` est déjà exactement le « handshake serveur » dont une app mobile
a besoin avant login : il expose des compteurs agrégés, jamais de noms de caméras ou de sites.

---

## 6. Modèle de données

MongoDB, sans schéma déclaré. Identifiants `uuid4` en `str` dans un champ `id` (le `_id` Mongo
est systématiquement projeté hors des réponses). 53 collections, dont les principales :

| Collection | Rôle | Champs structurants |
|---|---|---|
| `users` | comptes locaux | `id`, `email` (unique), `password_hash`, `role`, `site_ids[]`, `permissions{}`, `twofa_*`, `locked`, `failed_login_count` |
| `sessions` | sessions JWT | `jti`, `user_id`, `revoked`, `last_seen_at` |
| `refresh_blacklist` | rotation à usage unique des refresh tokens | |
| `role_permissions` | overrides RBAC par rôle | doc unique `_id: "default"` |
| `sites` | sites | `id`, `name`, `type`, `address`, `lat/lng`, `client_name`, `contact_name` |
| `buildings`, `site_plans` | Site Manager (plans, positions) | `site_id` |
| `cameras` | caméras | `id`, `site_id`, `rtsp_url`, `ai_rtsp_url`, `webrtc_rtsp_url`, `enabled_plugins[]`, `ai_resolution`, `stream_mode`, `api_*`, `status` |
| `camera_runtime`, `camera_diagnostics`, `camera_benchmarks` | état / observabilité | |
| `events` | événements IA | `camera_id`, `timestamp`, `type`, `kind` |
| `plates` | plaques ANPR | `plate`, `camera_id`, `timestamp`, `track_id`, `engine` |
| `alerts` | alertes acquittables | `camera_id`, `timestamp` |
| `recordings` | segments | `camera_id`, `start_ts`, `end_ts` |
| `exports` | exports vidéo | |
| `settings`, `system_config`, `notification_settings` | configuration | |
| `plugins` + config store | plugins + secrets Fernet | |
| `audit_logs`, `stream_lifecycle_journal`, `diagnostics_events` | traçabilité | |
| `welcome_prefs`, `welcome_widgets`, `welcome_news`, `welcome_tutorials` | Welcome Center | `user_id` |
| `tls_certificates`, `license`, `backups`, `hardware`, `equipment` | infra | |
| `watchlist`, `vehicle_identities`, `plate_validations`, `faces`, `smart_zones`, `workflows`, `parking_zones`, `access_controllers` | métier | |

**Ce qui manque au regard du §26** : `Organization`, `Membership`, `MGVMSServer` /
`ServerRegistration`, `Layout`, `Favorite`, `UserPreference` généralisée, `CameraPreference`,
`Device` (appareil connu).
**Ce qui existe déjà et ne doit surtout pas être dupliqué** : `Site`, `Camera`, `Recording`,
`Event`, `Notification`, `Session`, `RefreshToken` (via blacklist), `AuditLog`, `License`.

---

## 7. Système d'authentification actuel

| Élément | État |
|---|---|
| Identifiant | e-mail + mot de passe (bcrypt) |
| Access token | JWT HS256, `sub`/`email`/`role`/`jti`, durée configurable (8 h par défaut) |
| Refresh token | JWT 7 j, **rotation à usage unique** + blacklist ; réutilisation détectée ⇒ révocation de toutes les sessions |
| Transport | `Authorization: Bearer`, cookie `access_token`, **et fallback `?token=` en query** pour les `<a href>` (export CSV, MJPEG) |
| Session | collection `sessions` par `jti`, révocable individuellement, `last_seen_at` |
| 2FA | TOTP (pyotp) + codes de récupération + désactivation admin |
| Anti-brute-force | double : par `IP:email` (5/15 min) **et** par compte (`locked`, persistant, déverrouillage admin, compte `ADMIN_EMAIL` non verrouillable) |
| Reset | `forgot-password` / `reset-password` avec token en collection dédiée |
| RBAC | 5 rôles hiérarchisés `guest < readonly < client < technician < admin`, 14 permissions granulaires, overrides par rôle (DB) puis par utilisateur, admin = bypass total |
| Scoping site | `user.site_ids[]` + helper `site_scope()` appliqué aux requêtes Mongo |
| Audit | `log_audit()` sur les actions sensibles |

C'est **déjà proche** de ce que demande §13. Les écarts réels sont :

1. aucune notion d'**appareil** — impossible de dire « déconnecter mon ancien téléphone » (§5) ;
2. le scoping site est **binaire** (`site_ids`), pas de rôle *par* site ⇒ `SITE_ADMIN` (§25) n'est pas exprimable ;
3. pas d'`Organization`, donc ni `ORG_ADMIN` ni `SUPER_ADMIN` distincts ;
4. `require_permission()` est mal appelé 35 fois (voir P4).

---

## 8. Architecture vidéo

```
Caméra ──RTSP──► go2rtc (relais unique, 1 seule session caméra)
                    │
       ┌────────────┼──────────────────────────────┐
       │            │                              │
  frame.jpeg    rtsp://go2rtc:8554            (WHEP fallback)
       │            │                              │
       ▼            ├──► recorder.py  ffmpeg -c copy ──► /app/recordings/*.mp4
  aperçu MJPEG      └──► frame_source.py ffmpeg NVDEC ──► YOLO / ANPR
       │
       ▼
  LivePlayer.jsx : WHEP (aiortc, H264 passthrough) d'abord,
                   bascule MJPEG **explicite** (bouton) si échec — jamais silencieuse
```

Conforme au cahier des charges :

- **Le client ne reçoit jamais d'URL RTSP** (§19) — respecté sans exception.
- **Aucun réencodage inutile** — WHEP en passthrough, enregistrement en `-c copy`, transcodage
  HEVC→H264 uniquement à la lecture, borné par le nombre de lectures simultanées.
- **Mutualisation** — recorder et IA lisent le relais go2rtc, pas la caméra (corrige la limite
  de sessions RTSP concurrentes des Reolink).

À traiter pour le mobile :

- WHEP/aiortc suppose un chemin ICE utilisable ; derrière NPM en 443 uniquement, il faut valider
  le mode « ICE sur TCP / relayé », ou prévoir un transport HTTP-only.
- Pas de LL-HLS : sur réseau mobile dégradé, MJPEG est le seul repli, et il est coûteux.

---

## 9. Architecture IA

```
ai_loop (server.py startup)
   └─► pipeline_v2.PipelineRuntime
         └─► CameraWorker (1 par caméra activée)
               └─► FrameContext (frame + métadonnées + trace)
                     └─► stages : detection → tracking → ANPR → downstream
                           └─► plugin_manager.bus  (47 plugins)
                                 ├─ FrameAnalyzer      (YOLO, RT-DETR, ONNX, OpenVINO…)
                                 ├─ PlateRecognizer    (fast-alpr, easyocr, paddle, tesseract…)
                                 ├─ Tracker            (ByteTrack, BoTSORT, DeepSORT…)
                                 └─ Notifier           (SMTP, Discord, Telegram)
                                       └─► events / plates / alerts (Mongo) + crops (/crops)
```

Le découplage demandé au §30 (« ne pas coupler les modèles IA au système de notification ») est
**déjà en place** : les notifiers sont des plugins du bus, jamais appelés par les modèles.
La structure `AIEvent` du §29 existe de fait, éclatée entre `events` et `plates` — une
normalisation est souhaitable mais ne nécessite **pas** de nouvelle collection.

---

## 10. Docker

4 services, ordre `mongo (healthy) → go2rtc (healthy) → backend (healthy) → frontend`.

| Service | Image | Ports | Points d'attention |
|---|---|---|---|
| `mgvms-mongo` | mongo:7.0 | interne | cache WiredTiger 2 Go |
| `mgvms-go2rtc` | alexxit/go2rtc:1.9.9 | 1984, 8554, 8555 tcp+udp | `go2rtc.yaml` monté **en écriture** (obligatoire) |
| `mgvms-backend` | build local, CUDA 12.4 | 8001 | `runtime: nvidia`, **`--workers 1`** |
| `mgvms-frontend` | build local, nginx | 3000, 3443 | build durci : URLs relatives obligatoires |

Bind mounts de **données uniquement** (`/mnt/storage/...`), aucun bind mount de code : l'image
est immuable, ce qui est correct. Déploiement exclusivement via `deploy-app/install.sh`.

Manque au regard du §37 : **aucun service `worker`**. Les rôles `video`, `ai` et `worker` du
cahier des charges vivent tous dans `backend`.

---

## 11. Points problématiques

Classés par impact sur la refonte demandée.

**P1 — Un seul process Python pour tout.** `--workers 1` ; IA, enregistrement, WebRTC, API et
WebSocket partagent le GIL. Gèle l'API pendant les cycles IA (documenté dans le compose).
Bloque §36 (200 caméras) et rend l'UX mobile aléatoire. *C'est le chantier structurant.*

**P2 — L'application n'est pas responsive du tout.** `Layout.jsx` : `h-screen flex overflow-hidden`
avec une sidebar `w-60` fixe, aucun breakpoint (`sm:`/`md:`/`lg:` absents du Layout), pas de
drawer, pas de barre d'onglets. Sur les 49 pages, la médiane est de **2 classes responsive par
page**. Pas de `manifest.json` (l'`index.html` y fait référence en commentaire, le fichier
n'existe pas dans `frontend/public/`). Aucune icône PWA, pas d'`apple-mobile-web-app-*`.
**Aujourd'hui, MG-VMS est inutilisable sur un téléphone.**

**P3 — Pas de contexte « site actif ».** `sites` est un CRUD isolé (84 lignes) ; aucun sélecteur
global, aucun `site_id` dans `AppContext`, aucune page filtrée par site. Le multi-sites du §15
n'existe qu'au niveau du scoping RBAC backend.

**P4 — RBAC : `require_permission()` mal appelé 35 fois.** `require_permission("admin")` (11×) et
`require_permission("technician")` (24×) passent un **nom de rôle** là où la fonction attend une
**permission** — or ni `"admin"` ni `"technician"` ne figurent dans `PERMISSIONS`. Conséquence :
`admin` ne passe que grâce au bypass admin, et **un `technician` est refusé sur toutes ces
routes** : TLS (9), plugins bus (12), smart zones (4), workflows (4), health dashboard (3),
camera_control (1), core (2). L'échec est « en fermé » — ce n'est donc pas une faille — mais le
rôle technicien est cassé sur une partie du produit, et le §25 exige un RBAC propre.

**P5 — Données de démonstration seedées automatiquement — violation directe de la règle §40.**

- `streaming.py::_ensure_demo_camera()` crée `demo-cam-001` / `demo-cam-002` (« Caméra Démo »,
  « Caméra Démo Trafic ») dès qu'il n'y a aucune caméra réelle, avec `status: "online"` forcé.
- `seed.py` crée 3 comptes en dur à chaque démarrage : `tech@mg-vms.com` / `Tech@2026`,
  `client@mg-vms.com` / `Client@2026`, `viewer@mg-vms.com` / `Viewer@2026`.

**P6 — Le mot de passe admin est réécrit à chaque démarrage.** `seed.py` : si le hash en base ne
correspond pas à `ADMIN_PASSWORD`, il **remet le hash de l'`.env`**. Un changement de mot de passe
admin fait depuis l'interface est donc annulé au prochain `install.sh`. Valeur par défaut dans le
compose : `Admin@2026`.

**P7 — Navigation héritée, très loin des 5 onglets visés.** 6 groupes, 49 pages, dont 9 pages
`pipeline*` de diagnostic et de nombreux « centres » (Camera Center, Pipeline Center, Security
Center, Map Center, Welcome Center) mélangés avec l'opérationnel. Le §24 (séparer l'administration
système) n'est pas appliqué : un `client` voit une nav réduite, mais toujours structurée comme un
outil d'installateur.

**P8 — Préférences non synchronisables.** Thème, langue, overlay IA, historique de recherche :
`localStorage` uniquement. `welcome_prefs` (serveur) ne couvre que le Welcome Center. Aucun layout
de mur vidéo persisté (`LiveView.jsx` : `useState(4)`, perdu au rechargement), aucun favori. Le §5
(changement de téléphone) n'a donc aujourd'hui **rien à restaurer**.

**P9 — WebSocket unique et global.** `/api/ws` diffuse les métriques système toutes les 5 s à tout
le monde ; pas d'abonnement par caméra ni par site, pas de heartbeat serveur (seul un
`receive_text()` keepalive côté client), pas de backpressure. Sur mobile (réseau qui coupe, app en
arrière-plan), c'est le premier point à durcir (§32).

**P10 — Deux god-modules.** `streaming.py` (2 395 l.) et `routers.py` (2 251 l.) concentrent sites,
caméras, événements, plaques, enregistrements, exports, go2rtc, ONVIF, PTZ et ffprobe. Toute
refonte d'API les traversera.

**P11 — Trois couches d'état client concurrentes** : `axios` (avec interceptors et cache
implicite), `swr` et `@tanstack/react-query` cohabitent dans `package.json`.

**P12 — CRA / react-scripts 5.** Non maintenu, build lent, `DISABLE_ESLINT_PLUGIN=true` requis
pour compiler (16 warnings `react-hooks/exhaustive-deps` pré-existants). Un client mobile-first
avec code-splitting agressif est difficile à obtenir sur cette base.

**P13 — Intégrité des données faible.** `cameras.id` n'a qu'un index **non unique** ; aucune
contrainte référentielle `camera.site_id → sites.id` ; `delete_site` supprime les caméras en
cascade sans confirmation d'impact ni archivage.

**P14 — Secrets.** `MGVMS_ENCRYPTION_KEY` retombe sur `JWT_SECRET` si vide (comportement
documenté) : une rotation du secret JWT rendrait illisibles tous les mots de passe caméra chiffrés.

**P15 — Cahier des charges antérieur divergent.** `docs/mg-vms-next-gen/` (28 chapitres, ~330 Ko)
décrit une cible v3.0 « plateforme de plugins », rédigée en juillet 2026, partiellement obsolète
(elle acte par exemple Traefik 3 alors que la cible actuelle est Nginx Proxy Manager) et sans un
mot sur le mobile, le multi-tenant ou un Cloud optionnel. Il faut décider explicitement de son
statut pour éviter deux références contradictoires.

---

## 12. Architecture cible proposée

### 12.1 Le Cloud est un satellite, jamais un intermédiaire

```
                    ╔═══════════════════════════════════╗
                    ║   MG-VMS CLOUD  (OPTIONNEL)       ║
                    ║   dépôt SÉPARÉ · déployable seul  ║
                    ║   ├ comptes & organisations       ║
                    ║   ├ annuaire de serveurs          ║
                    ║   ├ sync préférences / layouts    ║
                    ║   ├ licences                      ║
                    ║   └ (plus tard) relais sortant    ║
                    ╚═════════════▲═════════════════════╝
                                  │  control plane
                    ┌─────────────┴──────────┐  (facultatif, jamais requis)
                    │                        │
              ┌─────┴──────┐          ┌──────┴───────────────┐
              │ App mobile │          │  MG-VMS SERVER       │
              │ / web      │          │  (enrôlement sortant)│
              └─────┬──────┘          └──────────────────────┘
                    │
                    │  ═══ DATA PLANE — chemin normal et par défaut ═══
                    │  HTTPS 443 direct, LAN ou WAN
                    ▼
            ┌───────────────────────────────────────┐
            │            MG-VMS SERVER              │
            │  API · WS · Vidéo · Events · Records  │
            │  PTZ · IA · Stockage · Auth locale    │
            └───────────────────────────────────────┘
```

**Règle d'implémentation opposable** : le Cloud vit dans un **dépôt distinct**
(`mg-vms-cloud`). Aucune ligne de `mg-vms-app` ne doit importer, appeler ou dépendre de
`mg-vms.com`. La seule adhérence autorisée dans le serveur est un module d'enrôlement
**sortant, désactivé par défaut**, dont l'échec est silencieux et sans effet sur le
fonctionnement local. Un test d'intégration doit vérifier que le serveur démarre et sert le live
avec le DNS coupé.

### 12.2 Découpage des process (résout P1, débloque §36)

```
mgvms-backend    uvicorn --workers N   API REST + WebSocket + WHEP   (sans état IA)
mgvms-worker     process dédié         ai_loop + pipeline_v2 + frame_source
mgvms-recorder   process dédié         recorder_loop + rétention + sweep
mgvms-mongo / mgvms-go2rtc / mgvms-frontend    inchangés
```

Communication inter-process via MongoDB (déjà source de vérité) plus un canal léger
(Redis pub/sub ou collection *capped*) pour les signaux temps réel. Cela **n'ajoute qu'un seul
composant d'infrastructure** et respecte §37 (« ne pas multiplier les conteneurs inutilement »).
Ce découpage est le préalable technique à tout le reste : il rend l'API prévisible — donc
compatible avec un usage mobile — et fait du passage à 200 caméras une question de
dimensionnement plutôt que d'architecture.

### 12.3 Modèle de données cible (extension, pas remplacement)

| Nouveau | Motif | Impact sur l'existant |
|---|---|---|
| `organizations` | §35, `ORG_ADMIN` | nouveau |
| `memberships` (`user_id`, `org_id`, `site_id?`, `role`) | rôle **par site** (§25) | `users.site_ids` conservé et **dérivé** pendant la transition |
| `devices` | appareils connus, révocation par appareil (§5) | lié à `sessions.jti` |
| `user_preferences` (`user_id`, `scope`, `key`, `value`, `version`, `updated_at`, `source`) | §27 | absorbe `welcome_prefs` |
| `layouts`, `favorites` | murs vidéo et favoris (§27) | nouveau |
| `server_registrations` | enrôlement Cloud (§33) | nouveau, **côté serveur uniquement** |
| champ `org_id` sur `sites` | isolation multi-tenant | migration additive, défaut = organisation locale |

Aucune collection existante n'est supprimée ni renommée. Toutes les migrations sont additives et
idempotentes, dans la lignée de `create_indexes()` / `_safe_index()` déjà en place.

### 12.4 API cible

- `/api/v1/*` devient le préfixe **documenté**, `/api/*` reste servi (le middleware existe déjà) ;
- namespace `/api/v1/mobile/*` **agrégateur** : un écran mobile = un appel
  (`/mobile/bootstrap` = sites + caméras + statuts + préférences + capacités serveur), pour
  limiter les allers-retours sur réseau mobile ;
- `/api/v1/preferences/*` pour la synchronisation §27 (`version` + `updated_at` + résolution de
  conflit « dernier écrivain gagne, sauf conflit détecté ⇒ remonté au client ») ;
- `/api/v1/server/info` : version, capacités, modes vidéo supportés, exigences d'authentification —
  le handshake que l'app fait **avant** d'afficher le formulaire de login (extension de
  `/api/system/public-status`, qui reste non authentifié et agrégé) ;
- WebSocket `/api/v1/ws` avec `subscribe`/`unsubscribe` par site et par caméra, heartbeat serveur,
  `resume` après coupure.

### 12.5 Client

Un **client responsive unique** (web + mobile via PWA installable), construit sur les composants
existants, avec :

- navigation 5 onglets en bas sur mobile (`Accueil · Direct · Événements · Explorer · Moi`) et
  sidebar sur desktop ;
- sélecteur de site en en-tête, persistant et synchronisable ;
- écran de connexion en deux temps — **adresse du serveur** puis **identifiants locaux** — le
  bouton « Compte MG-VMS » restant clairement optionnel, et absent tant que le Cloud n'existe pas ;
- administration système reléguée derrière un rôle et un écran distinct (§24).

> La question « PWA responsive unique » vs « application native séparée » change massivement le
> périmètre et doit être tranchée avant la Phase 6. Recommandation : **PWA d'abord** — elle
> réutilise l'intégralité de l'existant, se déploie par le même conteneur nginx, et n'interdit pas
> une app native ultérieure sur la même API `/api/v1/mobile/*`. Limite connue : la notification
> push sur iOS (possible depuis iOS 16.4 en PWA installée, mais moins fiable qu'en natif).

---

## 13. Plan de migration

| Phase | Contenu | Livrable vérifiable | Dépend de |
|---|---|---|---|
| **0 — Assainissement** | supprimer le seeding démo (P5), corriger la réécriture du mot de passe admin (P6), corriger les 35 `require_permission()` (P4), index unique `cameras.id` (P13) | aucune donnée fictive en base ; un technicien accède à TLS/plugins/workflows ; le mot de passe admin change et persiste | — |
| **1 — Découplage des process** | extraire `ai_loop` et `recorder_loop` en conteneurs dédiés ; `backend` passe à `--workers N` | `nvidia-smi` + `docker stats` : API < 200 ms pendant un cycle IA plein | 0 |
| **2 — Modèle de données** | migrations additives : `organizations`, `memberships`, `devices`, `user_preferences`, `layouts`, `favorites`, `org_id` sur `sites` | migration rejouable ; base v3.9.2 existante intacte | 0 |
| **3 — Auth & RBAC** | rôles par site (`SUPER_ADMIN`/`ORG_ADMIN`/`SITE_ADMIN`/`OPERATOR`/`VIEWER`) mappés sur les rôles existants ; `devices` liés aux sessions ; révocation par appareil | matrice de tests RBAC : chaque route refuse ce qu'elle doit refuser **côté serveur** | 2 |
| **4 — API v1 & mobile** | `/api/v1` documenté, `/api/v1/mobile/bootstrap`, `/api/v1/preferences`, `/api/v1/server/info`, WebSocket v1 avec abonnements | OpenAPI publié ; un écran = un appel | 3 |
| **5 — Préférences & layouts** | persistance serveur du thème, de la langue, des filtres, favoris et layouts de mur vidéo | déconnexion / reconnexion sur un autre navigateur ⇒ environnement restauré | 4 |
| **6 — UX responsive** | Layout adaptatif + 5 onglets, sélecteur de site, connexion en deux temps, dashboard type Reolink, Direct 1/4/9/16 + layouts, Événements, Explorer, paramètres caméra regroupés, administration séparée | parcours complet sur un téléphone réel, portrait et paysage | 5 |
| **7 — Cloud (dépôt séparé)** | comptes, organisations, annuaire de serveurs, enrôlement par code à usage limité et révocable, sync | **test obligatoire §34** : DNS coupé ⇒ live, enregistrements, événements, IA et login local intacts | 6 |
| **8 — Accès distant** | NPM / TLS / WebSocket validés, puis éventuel tunnel sortant | accès WAN sans port forwarding, en option | 7 |

Aucune phase ne supprime de fonctionnalité. Les phases 0 à 5 sont invisibles pour l'utilisateur
final et testables une par une sur le serveur de production existant, selon la méthode habituelle :
`install.sh`, mesure réelle, aucune supposition.

---

## 14. Fichiers concernés

### Phase 0 — Assainissement (en premier, risque faible)

```
FILE           backend/streaming.py  (l. 49-56, 628, 747-778)
ROLE           Enregistrement des flux go2rtc + seeding
CURRENT STATE  DEMO_CAMERAS/DEMO_IDS + _ensure_demo_camera() créent 2 caméras fictives
               "online" quand la base ne contient aucune caméra réelle
CHANGE         Supprimer DEMO_CAMERAS, DEMO_IDS, _ensure_demo_camera() et son appel ;
               nettoyer les 3 branches `if cam.id in DEMO_IDS`
REASON         Règle §40 : aucune fausse caméra, jamais
RISK           Faible. Les entrées de démo de go2rtc.yaml restent inertes. Vérifier
               qu'aucun test ne s'appuie sur demo-cam-001 avant suppression
```

```
FILE           backend/seed.py
ROLE           Bootstrap des comptes au démarrage
CURRENT STATE  Crée 3 comptes de démo en dur ; réécrit le hash admin si ≠ ADMIN_PASSWORD
CHANGE         Supprimer `demo_users` ; ne (re)définir le mot de passe admin qu'à la
               création du compte, ou sur variable explicite MGVMS_FORCE_ADMIN_PASSWORD=1
REASON         Règles §40 et §13 — un mot de passe changé doit persister
RISK           Moyen : l'ancien comportement servait de filet de secours en cas d'oubli.
               Documenter backend/scripts/mgvms_admin.py (déjà présent) comme procédure
               de récupération avant de changer quoi que ce soit
```

```
FILE           backend/routes/tls.py · plugins_bus.py · smart_zones.py · workflows.py
               · health_dashboard.py · camera_control.py · routers.py
ROLE           Routes protégées
CURRENT STATE  35 appels `require_permission("admin"|"technician")` — des noms de RÔLE
               passés à une fonction qui attend une PERMISSION
CHANGE         Remplacer par `require_role("admin"|"technician")`, ou par la permission
               réelle (`manage_settings`, `manage_plugins`, `manage_workflows`…)
REASON         §25 — aujourd'hui le rôle technicien est refusé sur tout ce périmètre
RISK           Faible, mais élargit l'accès : à traiter route par route, avec la matrice
               RBAC en tests
```

```
FILE           backend/database.py
ROLE           Index Mongo
CURRENT STATE  `cameras.id` indexé mais NON unique ; rien pour devices/preferences
CHANGE         `unique=True` sur `cameras.id` (après contrôle de doublons) ; index des
               nouvelles collections en Phase 2
REASON         §26 — intégrité
RISK           Faible ; `_safe_index` absorbe déjà les conflits, mais un doublon existant
               ferait échouer la création : contrôler avant
```

### Phase 1 — Découplage des process

```
FILE           backend/server.py  (on_startup, l. 196-230)
ROLE           Démarrage de toutes les boucles de fond
CURRENT STATE  ai_loop, recorder_loop, camera_status_loop, qos_watcher, stability_watcher
               et les broadcasters sont tous des asyncio.create_task du process API
CHANGE         Conditionner par rôle de process (MGVMS_ROLE=api|worker|recorder) et
               ajouter des points d'entrée dédiés
REASON         P1 · §36 · latence API
RISK           ÉLEVÉ — c'est le cœur du démarrage. Branche dédiée, retour arrière par
               variable d'environnement (MGVMS_ROLE=all restaure le comportement actuel
               à l'identique)
```

```
FILE           deploy-app/docker-compose.yml · backend/Dockerfile
ROLE           Orchestration
CURRENT STATE  4 services ; backend en --workers 1 avec GPU
CHANGE         Ajouter `worker` et `recorder` (même image, commande différente) ;
               backend passe à --workers N, sans GPU si l'IA en sort
REASON         §37 — services identifiés, sans multiplication inutile
RISK           ÉLEVÉ : allocation GPU, ordre de démarrage et healthchecks à revoir.
               Déploiement exclusivement par install.sh, une étape à la fois
```

```
FILE           backend/ai_engine.py · pipeline_v2/* · frame_source.py · recorder.py
ROLE           IA et enregistrement
CURRENT STATE  État en mémoire du process (modèles, workers, caches, singletons + locks)
CHANGE         Aucune réécriture métier : déplacer le point d'entrée et remplacer les
               signaux in-process (`_config_dirty`, `_camera_dirty_set`) par un canal
               partagé
REASON         P1
RISK           ÉLEVÉ sur le hot-reload de configuration — c'est exactement ce que les
               flags en mémoire assurent aujourd'hui. À couvrir par des tests avant bascule
```

### Phases 2-3 — Données, auth, RBAC

```
FILE           backend/database.py (create_indexes) + backend/migrations/ (à créer)
CHANGE         Migrations additives idempotentes : organizations, memberships, devices,
               user_preferences, layouts, favorites, org_id sur sites
REASON         §26 — étendre proprement, ne rien détruire
RISK           Faible si strictement additif ; interdiction de toucher aux collections
               existantes en Phase 2
```

```
FILE           backend/auth.py
ROLE           Auth + RBAC (735 l.)
CURRENT STATE  5 rôles globaux, 14 permissions, scoping site binaire via user.site_ids
CHANGE         Résolution des permissions par (user, org, site) via `memberships`, en
               conservant `site_ids` comme valeur dérivée ; lier `sessions` à `devices`
REASON         §25 · §15 · §5
RISK           ÉLEVÉ — toute erreur ici est une faille. `effective_permissions*()` est
               appelé à chaque requête : ne pas dégrader la latence. Tests RBAC
               exhaustifs obligatoires avant fusion
```

```
FILE           backend/routes/users.py · routes/security.py · frontend RbacCenter.jsx
CHANGE         Exposer et éditer les memberships (rôle par site)
REASON         §23 · §25
RISK           Moyen
```

### Phases 4-5 — API v1, mobile, préférences

```
FILE           backend/routes/mobile.py (à créer)
CHANGE         /api/v1/mobile/bootstrap (agrégateur), /api/v1/server/info
REASON         §31 — un écran mobile = un appel réseau
RISK           Faible (additif). Ne pas fuiter d'information avant login sur
               /server/info : même discipline que public-status
```

```
FILE           backend/routes/preferences.py (à créer) · routes/welcome.py
CHANGE         Préférences génériques versionnées ; welcome_prefs devient un scope
REASON         §27
RISK           Faible ; migration des prefs Welcome à faire en lecture compatible
```

```
FILE           backend/realtime.py
ROLE           WebSocket unique
CURRENT STATE  Broadcast global des métriques toutes les 5 s, aucun abonnement
CHANGE         subscribe/unsubscribe par site et caméra, heartbeat serveur, resume
REASON         §32 · mobile
RISK           Moyen — le front actuel consomme ce canal (AppContext, alertPing) :
               conserver le comportement legacy sur /api/ws pendant la transition
```

```
FILE           frontend/src/lib/api.js
CURRENT STATE  baseURL = "" + "/api", token en localStorage
CHANGE         Base URL configurable au runtime (serveur choisi par l'utilisateur) et
               stockage de la liste de serveurs
REASON         §3 · §14
RISK           Moyen — le Dockerfile interdit délibérément les URLs absolues au build.
               La sélection de serveur doit être un état d'exécution, jamais une
               variable de build : ne pas contourner cette protection
```

### Phase 6 — UX (à ne PAS commencer avant validation des phases 0-5)

```
FILE           frontend/src/components/Layout.jsx
CURRENT STATE  h-screen flex, sidebar w-60 fixe, zéro breakpoint
CHANGE         Layout adaptatif : sidebar ≥ lg, barre de 5 onglets < lg, en-tête avec
               sélecteur de site
REASON         §16 · §17
RISK           Moyen — fichier traversé par toutes les pages
```

```
FILE           frontend/src/pages/Login.jsx
CURRENT STATE  Formulaire email/mot de passe + 2FA, serveur implicite (same-origin)
CHANGE         Deux temps : adresse du serveur (via /server/info) puis identifiants ;
               bloc « Compte MG-VMS » masqué tant que le Cloud n'existe pas
REASON         §12 — et §40 : ne pas afficher un bouton Cloud non fonctionnel
RISK           Faible
```

```
FILE           frontend/src/App.js · pages/*.jsx (49 fichiers)
CHANGE         Regroupement sous 5 sections, pages d'administration derrière un garde de
               rôle, responsive page par page
REASON         §17 · §24
RISK           ÉLEVÉ en volume. Aucune page ne doit être supprimée : elles sont déplacées
               ou fusionnées. Un tableau de correspondance « page actuelle → nouvel
               emplacement » sera produit (§41 PHASE 2) avant toute modification
```

```
FILE           frontend/public/index.html + manifest.json (à créer) + icônes
CHANGE         Manifeste PWA, icônes, apple-mobile-web-app-*, theme-color
REASON         §11 — application installable
RISK           Faible
```

### Hors dépôt

```
FILE           dépôt mg-vms-cloud (à créer, Phase 7)
ROLE           Control plane optionnel : comptes, organisations, annuaire, sync, licences
CHANGE         Nouveau projet, déployé séparément
REASON         §1 · §2 · §45 — garantie structurelle que le serveur ne peut pas dépendre
               du Cloud : ce qui n'est pas dans le dépôt ne peut pas être importé
RISK           Aucun pour l'existant tant que la Phase 7 n'est pas atteinte
```

---

## Points à trancher avant de coder

1. **Statut de `docs/mg-vms-next-gen/`** — référence conservée, archivée, ou fusionnée avec ce
   document ? Deux cahiers des charges actifs et divergents produiront des arbitrages
   contradictoires.
2. **Client mobile** — PWA responsive unique (recommandé) ou application native distincte ?
3. **Ordre de démarrage** — Phase 0 (assainissement : risque faible, gains immédiats, met le
   produit en conformité avec la règle §40) ou Phase 1 (découplage des process : risque élevé,
   déblocage structurel) ?
