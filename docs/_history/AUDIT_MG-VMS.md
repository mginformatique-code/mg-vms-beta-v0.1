# AUDIT LOGICIEL COMPLET — MG-VMS
### Rapport d'architecture avant industrialisation
**Auteur :** Architecte Logiciel Senior / CTO — Audit indépendant
**Date :** Juin 2026
**Version du rapport :** 1.0
**Périmètre :** Audit en lecture seule. Aucune ligne de code modifiée, supprimée ou refactorisée.

---

## 0. RÉSUMÉ EXÉCUTIF

MG-VMS est aujourd'hui un **MVP web fonctionnel et bien construit** couvrant la couche **gestion / supervision** d'un VMS : authentification robuste (JWT + RBAC 5 rôles + 2FA TOTP), multi-sites, inventaire caméras, mur vidéo, dashboard, ANPR (recherche + IA d'analyse d'image), recherche véhicule, alertes, audit, et notifications (SMTP/Discord/Telegram). La qualité de code est **élevée** (modulaire, testée, ~1180 lignes backend / ~1760 lignes frontend), avec **50 tests backend qui passent à 100%**.

**MAIS** il faut être transparent : MG-VMS n'est **pas encore un VMS au sens moteur vidéo**. Le cœur métier d'un VMS professionnel (ingestion RTSP réelle, décodage, enregistrement disque, relecture timeline, détection IA temps réel YOLO, tracking, découverte ONVIF) est **absent ou simulé**. Les flux vidéo, les tests caméra, les snapshots et les détections sont des **données de démonstration**.

### Écart structurel majeur (à acter avant toute roadmap)
Le cahier des charges initial demandait **Vue.js 3 / TypeScript / PostgreSQL / SQLAlchemy / Alembic / Docker Compose multi-conteneurs / Celery / FFmpeg / YOLOv11 / ONVIF / WebRTC / Prometheus-Grafana**.
La réalité technique livrée est **React (CRA) / FastAPI / MongoDB (Motor) / mono-service Kubernetes**.

Ce n'est pas un défaut de qualité — c'est une **contrainte de l'environnement d'exécution actuel** (sandbox Kubernetes mono-conteneur, pas de GPU, pas d'accès réseau caméras, pas de multi-conteneurs Docker). Mais cela implique que **la moitié « temps réel vidéo / IA » du produit ne peut pas être réalisée dans cet environnement** et nécessitera une **infrastructure de production dédiée** (serveurs GPU, workers FFmpeg/YOLO, stockage NVR).

### Verdict synthétique
| Couche | État | Note /10 |
|---|---|---|
| Gestion / supervision (CRUD, RBAC, dashboard, ANPR mgmt, notifications) | ✅ Solide | 8.5 |
| Qualité de code & tests | ✅ Solide | 8 |
| Moteur vidéo (RTSP/ONVIF/record/replay) | 🔴 Absent | 1 |
| IA temps réel (YOLO/tracking) | 🔴 Absent (ANPR sur upload uniquement) | 2 |
| Infra production (Docker Compose, monitoring, HA, SSL) | 🔴 Absent | 1 |
| Sécurité applicative | 🟡 Bon socle, durcissement requis | 6 |
| **Maturité commerciale globale** | 🟡 **MVP démo** | **~35–40 %** d'un VMS commercial |

---

## 1. ARCHITECTURE RÉELLE CONSTATÉE

### 1.1 Stack effective
- **Backend :** Python / FastAPI 0.110, Motor 3.3 (MongoDB async), PyJWT, bcrypt, PyOTP, aiosmtplib, httpx, cryptography, emergentintegrations (LLM).
- **Frontend :** React 19 (Create React App + CRACO), Tailwind, shadcn/ui (Radix), recharts, lucide-react, sonner, react-router 7. **Pas de TypeScript, pas de Vue, pas de Pinia, pas de Vite.**
- **Base de données :** **MongoDB** (NoSQL). **Pas de PostgreSQL, pas de SQL, pas de SQLAlchemy, pas d'Alembic, pas d'index SQL ni relations.**
- **Exécution :** mono-service backend (port 8001) + mono-service frontend (port 3000), routés par ingress Kubernetes via préfixe `/api`. Supervisor gère les process.

### 1.2 Découpage backend (modulaire, propre)
| Fichier | Lignes | Rôle |
|---|---|---|
| `server.py` | 45 | Bootstrap FastAPI, CORS, startup (index + seed), montage routers |
| `auth.py` | 242 | JWT (access+refresh), bcrypt, RBAC `require_role`, 2FA TOTP, audit helper |
| `routers.py` | 491 | Dashboard, sites, caméras, events, plates/ANPR, watchlist, alertes, audit, users, AI analyze-plate |
| `notifications.py` | 210 | SMTP/Discord/Telegram, chiffrement Fernet, settings, test, `send_notification` |
| `seed.py` | 175 | Données de démo (users, 5 sites, ~25 caméras, plaques, events, alertes, watchlist) |
| `database.py` | 15 | Client Motor + création d'index Mongo |

### 1.3 Découpage frontend (13 pages)
Login, Dashboard, LiveView, Cameras, Sites, MapView, Anpr, VehicleSearch, Alerts, Audit, Users, Settings, Notifications. Context global unique (`AppContext` : auth + thème + langue + i18n + RBAC `can()`).

---

## 2. TABLEAU DES FONCTIONNALITÉS (ÉTAPE 2)

Légende : ✅ Terminé · 🟡 Partiel · 🔴 Absent · ⚠ À revoir

### 2.1 Infrastructure & DevOps
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Docker (image app) | 🔴 | 0% | P1 | Aucun Dockerfile |
| Docker Compose multi-conteneurs | 🔴 | 0% | P1 | Demandé au CDC, non livrable dans la sandbox actuelle |
| Variables .env | ✅ | 100% | — | Présent, propre, secrets via env |
| Volumes / persistance | 🟡 | 50% | P1 | Mongo persistant local, pas de volumes vidéo/NVR |
| Sauvegardes / restauration | 🔴 | 0% | P2 | Aucune stratégie backup/restore |
| Logs | 🟡 | 40% | P2 | logging Python basique + supervisor ; pas de centralisation |
| Monitoring (Prometheus/Grafana/Loki) | 🔴 | 0% | P2 | Absent |
| Healthcheck | 🟡 | 30% | P2 | `/api/` ping ; pas de /health structuré ni readiness |
| Watchdog | 🔴 | 0% | P3 | Absent |
| Reverse proxy / SSL / IPv6 | 🟡 | n/a | P2 | Géré par ingress k8s (HTTPS) ; pas de Traefik/Nginx propre au produit |
| HA / Scalabilité | 🔴 | 0% | P3 | Mono-instance, pas de file d'attente |
| CI/CD | 🔴 | 0% | P2 | Aucun pipeline `.github` |

### 2.2 Backend
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| FastAPI / architecture | ✅ | 90% | — | Découpage clair par domaine |
| Routes REST | ✅ | 85% | — | ~40 endpoints cohérents, préfixe `/api` |
| Swagger / OpenAPI | ✅ | 80% | P3 | Auto-généré (`/docs`) ; descriptions à enrichir |
| JWT | ✅ | 85% | P1 | Access 8h + refresh 7j ; **refresh non câblé côté frontend** |
| RBAC | ✅ | 90% | — | `require_role` hiérarchique 5 rôles |
| Permissions fines (par site/ressource) | 🟡 | 30% | P1 | `site_ids` existe sur user mais **non appliqué** (tout user voit tous les sites) |
| Middlewares | 🟡 | 40% | P2 | CORS uniquement ; pas de middleware logs/erreurs/rate-limit |
| Gestion d'erreurs | 🟡 | 60% | P2 | HTTPException correct ; pas de handler global ni codes structurés |
| Tests | ✅ | 75% | — | 50 tests pytest (auth, RBAC, CRUD, notif, IA) — 100% pass |
| Documentation | 🟡 | 30% | P2 | README quasi vide ; docstrings rares |

### 2.3 Frontend
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Framework | ⚠ | n/a | — | **React** livré (CDC demandait Vue 3 + TS + Pinia) |
| TypeScript | 🔴 | 0% | P3 | JS pur |
| Responsive | 🟡 | 70% | P1 | Grilles responsives ; mur vidéo 64 et tableaux denses à valider sur mobile |
| Dark / Light mode | ✅ | 100% | — | Toggle fonctionnel, persistant |
| i18n FR/EN | ✅ | 95% | — | Dictionnaire complet ; quelques libellés en dur |
| Composants UI | ✅ | 90% | — | shadcn/ui, design « control room » cohérent |
| Performances | 🟡 | 60% | P2 | Polling stats 15s ; pas de react-query/cache ; pas de virtualisation des grandes listes |
| UX | ✅ | 80% | — | Bonne densité pro, animations sobres |
| Tests frontend | 🔴 | 0% | P3 | Aucun test unitaire (validé via agent e2e) |

### 2.4 Authentification & sessions
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Connexion sécurisée | ✅ | 90% | — | bcrypt, message d'erreur générique |
| 2FA TOTP | ✅ | 90% | — | setup/verify/disable + QR (service externe qrserver) |
| OTP / codes | ✅ | 90% | — | PyOTP, fenêtre ±1 |
| Sessions / expiration | 🟡 | 60% | P1 | Token 8h en localStorage ; **refresh jamais appelé** → déconnexion à expiration |
| Reset password | 🔴 | 0% | P1 | Endpoint absent (le playbook le prévoyait) |
| Anti brute-force / lockout | 🔴 | 0% | P1 | Aucun verrouillage après N échecs |
| Historique connexions | 🟡 | 70% | P2 | Loggé dans `audit_logs` mais pas d'écran dédié |

### 2.5 Caméras
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Ajout manuel | ✅ | 90% | — | Formulaire complet (IP, proto, codec, RTSP, PTZ) |
| Découverte ONVIF | 🔴 | 0% | P1 | Aucune lib ONVIF / scan réseau |
| RTSP / flux réel | 🔴 | 0% | P0 | **Aucune ingestion** ; placeholders images |
| H264/H265/MJPEG | 🟡 | 20% | P0 | Champ codec stocké ; pas de décodage |
| Audio | 🔴 | 0% | P2 | Absent |
| PTZ / Preset / Patrol / Zoom | 🟡 | 15% | P1 | Endpoint PTZ factice (no-op), pas de presets/patrol |
| Snapshot | 🟡 | 30% | P1 | Renvoie image de démo, pas de capture réelle |
| Test connexion | 🟡 | 30% | P1 | Résultat aléatoire simulé |
| Statut / FPS / résolution / débit / firmware | 🟡 | 20% | P1 | Valeurs simulées ; pas de sonde réelle |

### 2.6 Mur vidéo (Live View)
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Layouts 1/4/9/16/25/36/49/64 | ✅ | 90% | — | Grille CSS dynamique OK |
| Layout 6 | 🔴 | 0% | P3 | Non proposé (carrés parfaits uniquement) |
| Plein écran | ✅ | 80% | — | `requestFullscreen` |
| Flux vidéo live | 🔴 | 0% | P0 | Images statiques |
| Glisser-déposer | 🔴 | 0% | P2 | Non implémenté |
| Audio / Snapshot / Enreg. manuel depuis le mur | 🔴 | 0% | P2 | Boutons PTZ au survol seulement |

### 2.7 Enregistrements / Relecture
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Enregistrement continu / planning / sur détection | 🔴 | 0% | P0 | Aucun moteur d'enregistrement |
| Timeline / relecture / image par image | 🔴 | 0% | P0 | Absent |
| Export MP4/AVI/JPEG/ZIP | 🔴 | 0% | P1 | Seul export = CSV ANPR |
| Archivage / rotation / quota | 🔴 | 0% | P1 | Absent |

### 2.8 IA (détection / tracking)
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| YOLO (personne, véhicule, animal, incendie, fumée, intrusion) | 🔴 | 0% | P0 | Aucun modèle ; events = données seedées |
| Zones / lignes / direction / comptage / temps d'arrêt | 🔴 | 0% | P1 | Absent |
| Tracking ByteTrack / DeepSort | 🔴 | 0% | P1 | Absent |
| Analyse IA image (ANPR upload) | ✅ | 80% | — | LLM vision (gpt-5.4) sur image uploadée — réel |

### 2.9 ANPR
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Lecture plaques (sur upload) | 🟡 | 60% | P1 | Via LLM, pas un moteur ANPR temps réel (OpenALPR/Paddle) |
| Lecture temps réel sur flux | 🔴 | 0% | P0 | Absent |
| France / Europe / Monde | 🟡 | 50% | P2 | Dépend du LLM, non spécialisé |
| Historique / recherche instantanée | ✅ | 90% | — | Filtres Mongo + index sur `plate`/`timestamp` |
| Liste blanche / noire + alertes | ✅ | 85% | — | Watchlist + statut plaque ; alerte auto à implémenter sur détection |
| Export CSV / Photos / Confiance | ✅ | 80% | — | CSV OK ; crops = images démo |
| Export PDF | 🔴 | 0% | P2 | Absent |

### 2.10 Recherche véhicule
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Plaque/couleur/marque/modèle/type/direction/caméra/site/date | ✅ | 85% | — | Multi-filtres opérationnels |
| Silhouette / recherche par image | 🔴 | 0% | P2 | Absent |

### 2.11 Base de données
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Modèle de données | 🟡 | 70% | P1 | MongoDB (pas SQL comme demandé) ; collections cohérentes |
| Index | 🟡 | 60% | P1 | Index sur email/site_id/plate/timestamp ; pas de TTL, pas tous optimisés |
| Relations / intégrité | 🟡 | 40% | P2 | Pas de contraintes (NoSQL) ; suppression site→caméras OK mais pas events/plates |
| Archivage / miniatures / stats | 🟡 | 40% | P2 | Stats à la volée ; pas d'archivage |

### 2.12 Dashboard
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Caméras actives/hors-ligne, sites, events, alertes, plaques | ✅ | 95% | — | KPI réels (issus de Mongo) |
| CPU/RAM/Stockage/Température/Bande passante | 🟡 | 40% | P2 | **Valeurs générées aléatoirement** (pas psutil) |
| GPU | 🔴 | 0% | P2 | Absent |
| Graphiques | ✅ | 85% | — | recharts (24h + répartition) ; série horaire générée |

### 2.13 Cartographie / Plans
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| OpenStreetMap | 🟡 | 60% | P2 | iframe OSM + 1 marqueur ; pas de multi-marqueurs interactifs (Leaflet) |
| Google Maps / satellite | 🔴 | 0% | P3 | Absent |
| Plans (import PDF/PNG/DWG, positionnement) | 🔴 | 0% | P2 | Absent |

### 2.14 Notifications
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Email (SMTP) | ✅ | 90% | — | aiosmtplib, TLS/STARTTLS, test, chiffré |
| Discord | ✅ | 90% | — | Webhook httpx |
| Telegram | ✅ | 90% | — | Bot API |
| Webhook générique / MQTT / SMS / Push | 🔴 | 0% | P2 | Absent |
| Notification navigateur / mobile | 🔴 | 0% | P2 | Absent |
| Envoi auto sur alerte critique | ✅ | 80% | — | Via `POST /api/alerts` (BackgroundTasks) ; pas encore branché sur détections réelles |

### 2.15 API
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| REST / Swagger | ✅ | 85% | — | OK |
| WebSocket | 🔴 | 0% | P1 | Aucun temps réel (live, alertes push) |
| OAuth2 / API Keys / versioning | 🔴 | 0% | P2 | Absent (auth JWT custom uniquement) |

### 2.16 Monitoring / Sauvegardes / Sécurité / Perfs / Compat / Mobile
| Fonction | État | Complétude | Priorité | Commentaire |
|---|---|---|---|---|
| Prometheus/Grafana/Loki/Alertmanager | 🔴 | 0% | P2 | Absent |
| Sauvegardes (config/DB/images/IA) | 🔴 | 0% | P2 | Absent |
| OWASP / CSRF / XSS / injection | 🟡 | 60% | P1 | Mongo (peu d'injection SQL), React échappe XSS ; pas de CSP, pas de protection CSRF formelle |
| Rate limit / Fail2ban | 🔴 | 0% | P1 | Absent |
| Audit / journalisation | ✅ | 85% | — | `audit_logs` couvre login/CRUD/export/notif |
| Cache Redis / files d'attente / multi-thread | 🔴 | 0% | P2 | Absent |
| Compat GPU (CUDA/QuickSync/VAAPI/Coral) ARM64/AMD64 | 🔴 | 0% | P1 | Non applicable sans moteur vidéo |
| Mobile responsive / PWA / apps natives | 🟡 | 50% | P2 | Web responsive partiel ; pas de PWA ni apps |

---

## 3. COMPARAISON AVEC LES VMS PROFESSIONNELS (ÉTAPE 3)

| Capacité clé | Milestone / Genetec / Nx / Luxriot / Network Optix | UniFi Protect | Frigate / Shinobi / Blue Iris | **MG-VMS (actuel)** |
|---|---|---|---|---|
| Ingestion RTSP/ONVIF temps réel | ✅ | ✅ | ✅ | 🔴 |
| Découverte auto ONVIF | ✅ | ✅ | 🟡 | 🔴 |
| Enregistrement NVR + relecture timeline | ✅ | ✅ | ✅ | 🔴 |
| Détection IA (objets) temps réel | ✅ | ✅ | ✅ (cœur de Frigate) | 🔴 |
| ANPR/LPR temps réel | ✅ (module) | 🟡 | 🟡 | 🟡 (sur upload) |
| Mur vidéo multi-flux | ✅ | ✅ | ✅ | 🟡 (UI ok, flux non) |
| Gestion multi-sites / RBAC | ✅ | 🟡 | 🟡 | ✅ |
| Notifications multi-canal | ✅ | ✅ | ✅ | ✅ (3 canaux) |
| Dashboard supervision | ✅ | ✅ | 🟡 | ✅ (UI) |
| Plans / cartographie interactive | ✅ | 🟡 | 🟡 | 🟡 |
| API + WebSocket temps réel | ✅ | ✅ | ✅ | 🟡 (REST only) |
| Haute dispo / clustering | ✅ | 🟡 | 🔴 | 🔴 |

**Positionnement :** MG-VMS rivalise aujourd'hui sur la **couche gestion/UX/administration** (proche d'un UniFi Protect côté ergonomie), mais **ne rivalise pas encore** sur le **cœur VMS temps réel** (ingestion/enregistrement/IA), qui est précisément ce qui distingue Milestone/Genetec/Frigate.

---

## 4. BUGS, CODE MORT, DUPLICATIONS, FAILLES (ÉTAPE 6)

### 4.1 Bugs / incohérences fonctionnels
1. **Refresh token non utilisé (P1).** Le backend émet un refresh token mais le frontend (`AppContext`) stocke seulement l'access token et n'appelle jamais `/api/auth/refresh`. → déconnexion forcée à l'expiration (8h). `/refresh` lit en plus le cookie (jamais posé côté front).
2. **`site_ids` non appliqué (P1).** Le champ existe sur l'utilisateur mais aucune route ne filtre par site → un « client » voit toutes les données de tous les sites. Faille de cloisonnement multi-tenant.
3. **`/cameras/{id}/test` non déterministe (P2).** `random() > 0.15` fait « clignoter » le statut online/offline à chaque test, ce qui peut dérouter l'utilisateur.
4. **Métriques système fictives (P2).** Dashboard CPU/RAM/stockage/température générés aléatoirement (par fenêtre de 30s) — à signaler comme non réels en l'état.
5. **Suppression de site partielle (P2).** Supprime les caméras du site mais **pas** les `events`/`plates`/`alerts` rattachés → données orphelines.
6. **2FA QR via service tiers (P2).** `api.qrserver.com` — dépendance externe + fuite potentielle de l'URI otpauth (contient le secret) vers un tiers. Générer le QR localement.
7. **Import `X` inutilisé** dans `Cameras.jsx` (lucide `X`) depuis la migration du modal snapshot vers `Dialog` — code mort mineur.
8. **Avertissement hydration** `<span>` enfant de `<option>` (filtre site) signalé par l'agent de test — non bloquant mais pollue la console.

### 4.2 Failles / durcissement sécurité
- **CORS `allow_origins="*"` + `allow_credentials=True` (P1).** Combinaison invalide pour les cookies (le navigateur rejette). L'app fonctionne car elle utilise le header Bearer, mais c'est une **mauvaise configuration latente** à corriger (origine explicite).
- **Pas d'anti brute-force / rate limiting (P1).** Login et endpoints exposés sans limitation → vulnérable au bruteforce et au DoS applicatif.
- **Pas de reset password (P1).** Manque fonctionnel et opérationnel.
- **Secrets notifications chiffrés via clé dérivée de `JWT_SECRET` (P2).** Acceptable en MVP, mais idéalement KMS/clé dédiée séparée ; la rotation de `JWT_SECRET` casserait le déchiffrement.
- **Pas de CSP / en-têtes sécurité (P2)** (X-Frame-Options, HSTS applicatif, etc.).
- **`ADMIN_PASSWORD` en `.env`** : seedé en clair côté config — acceptable en dev, à externaliser (secret manager) en prod.

### 4.3 Performances / dette technique
- **Polling 15s** des stats dans `Layout` (pas d'annulation, pas de cache) → charge inutile. Migrer vers WebSocket ou react-query.
- **Pas de pagination** sur les listes (plates/events/audit limitées à N en dur) → ne tiendra pas à l'échelle « centaines de caméras / millions d'events ».
- **Pas de virtualisation** des tableaux denses ni du mur 64 caméras.
- **`routers.py` (491 lignes)** commence à concentrer trop de domaines — à scinder (cameras/anpr/users/alerts) quand le volume grandira.

### 4.4 Duplications mineures
- Composant « plaque stylisée » dupliqué entre `Anpr.jsx` et `VehicleSearch.jsx` → à extraire en composant partagé.
- Styles `.inp`/`.inp2` redéfinis localement dans plusieurs pages.

---

## 5. ROADMAP PRIORISÉE (ÉTAPE 4)

### P0 — Cœur VMS (bloquant pour être un « vrai » VMS)
- Ingestion **RTSP** réelle + transcodage **WebRTC/HLS** (FFmpeg) pour le live.
- **Découverte ONVIF** + PTZ/snapshot réels.
- Moteur d'**enregistrement** (continu/planning/sur détection) + **timeline / relecture**.
- **Détection IA temps réel** (YOLOv11) + **ANPR temps réel** sur flux + **tracking** (ByteTrack).

### P1 — Sécurité, robustesse, complétude gestion
- Reset password, anti brute-force/rate-limit, refresh token câblé, CORS durci.
- Cloisonnement par site (`site_ids` appliqué dans toutes les routes).
- WebSocket (live alertes/statuts), pagination + filtres serveur.
- Exports MP4/JPEG/ZIP, alerte auto sur plaque liste noire.

### P2 — Industrialisation & exploitation
- Docker Compose multi-conteneurs (api/worker/ffmpeg/ai/redis/mongo-ou-postgres/reverse-proxy/monitoring).
- Monitoring Prometheus/Grafana + healthchecks structurés + logs centralisés.
- Sauvegardes/restauration, archivage/rotation/quota stockage (NAS/SMB/NFS/S3/MinIO).
- Plans (import + positionnement caméras), cartographie Leaflet multi-marqueurs.
- Notifications : webhook générique, MQTT, SMS, push navigateur, WhatsApp.
- Rapports PDF/Excel.

### P3 — Confort & extensions
- TypeScript (si réécriture front), PWA, glisser-déposer mur vidéo, layouts custom (6, etc.).
- Versioning API, OAuth2, API Keys.
- Audit UI dédié (historique connexions).

### P4 — Vision long terme
- Reconnaissance faciale, thermique, radar, drone.
- Marketplace de plugins, HA/clustering, apps natives Android/iOS, support GPU/Coral/QuickSync.

---

## 6. FICHES DÉTAILLÉES DES FONCTIONNALITÉS MANQUANTES CLÉS (ÉTAPE 5)

### 6.1 Ingestion RTSP + Live WebRTC/HLS (P0)
- **Pourquoi :** sans flux live réel, ce n'est pas un VMS. C'est LA fonction socle.
- **Fonctionnement :** worker FFmpeg/GStreamer se connecte au RTSP caméra, transcode en WebRTC (faible latence) ou HLS/LL-HLS ; le front consomme le flux dans le mur vidéo.
- **Impact utilisateur :** visualisation temps réel multi-caméras — argument de vente n°1.
- **Complexité :** Élevée. **Estimation :** 3–5 semaines (1–2 ingénieurs).
- **Architecture :** conteneur `ffmpeg`/`mediamtx` (ex-rtsp-simple-server) ou `go2rtc` dédié + signalisation WebRTC ; le backend gère l'inventaire et les tokens d'accès flux. **Nécessite serveur dédié hors sandbox.**

### 6.2 Découverte ONVIF + PTZ réel (P0/P1)
- **Pourquoi :** ajout massif de caméras en quelques clics (attendu des intégrateurs).
- **Fonctionnement :** scan WS-Discovery sur le LAN, récupération profils ONVIF (RTSP URI, capacités PTZ), import en base ; commandes PTZ via ONVIF.
- **Complexité :** Moyenne. **Estimation :** 1–2 semaines.
- **Architecture :** lib `onvif-zeep`/`python-onvif` dans le worker (accès réseau caméras requis).

### 6.3 Enregistrement + Timeline (P0)
- **Pourquoi :** la relecture d'incidents est le second usage d'un VMS.
- **Fonctionnement :** enregistrement segmenté (ex. .mp4 par tranches) sur stockage, index temporel en base, timeline front avec scrubbing, image par image, export.
- **Complexité :** Élevée. **Estimation :** 3–4 semaines.
- **Architecture :** worker d'enregistrement + stockage objet (S3/MinIO) ou disque NVR + métadonnées Mongo/SQL ; politique de rotation/quota.

### 6.4 Détection IA temps réel YOLOv11 + Tracking (P0/P1)
- **Pourquoi :** détections (intrusion, incendie, comptage) = valeur « intelligente » du produit.
- **Fonctionnement :** worker GPU décode les flux, infère YOLOv11, applique zones/lignes/direction, suit les objets (ByteTrack), génère events + déclenche notifications.
- **Complexité :** Très élevée. **Estimation :** 4–8 semaines + matériel GPU.
- **Architecture :** conteneur `ai-engine` (CUDA), file Redis/Celery, écriture events ; **GPU indispensable, hors sandbox**.

### 6.5 Sécurité applicative (P1) — lot rapide à fort ROI
- Reset password (token à usage unique, TTL), rate-limit/lockout (5 essais/15 min), refresh token câblé, CORS origine explicite, CSP/HSTS.
- **Complexité :** Faible–Moyenne. **Estimation :** 1 semaine. **Réalisable dans l'environnement actuel.**

### 6.6 WebSocket temps réel (P1)
- **Pourquoi :** alertes/statuts caméras poussés instantanément (vs polling).
- **Complexité :** Moyenne. **Estimation :** 1 semaine. Réalisable côté backend FastAPI (`websocket`) + front.

---

## 7. CONCLUSION (ÉTAPE 7)

### ✅ Ce qui est TERMINÉ (production-ready à l'échelle MVP)
Auth JWT + RBAC + 2FA · multi-sites (CRUD) · inventaire caméras (CRUD + champs RTSP/ONVIF) · mur vidéo (UI/layouts) · dashboard (KPI réels) · ANPR (recherche, watchlist, export CSV, analyse IA d'image) · recherche véhicule · alertes + acquittement · audit · notifications SMTP/Discord/Telegram chiffrées · i18n FR/EN · dark/light · 50 tests backend OK.

### 🔴 Ce qui MANQUE (cœur VMS)
Flux RTSP live · découverte ONVIF · enregistrement + timeline/relecture · IA temps réel YOLO + tracking · ANPR temps réel sur flux · WebSocket · exports vidéo · plans · monitoring · sauvegardes · Docker Compose/CI-CD · rate-limit/reset password.

### ⚠ Ce qui doit être AMÉLIORÉ
Métriques système réelles (psutil) · refresh token câblé · cloisonnement par site · pagination/scalabilité · QR 2FA local · suppression en cascade · CORS durci · README/docs.

### ♻ Ce qui devra être RÉÉCRIT / RE-PLATEFORMÉ pour la prod
Passage à une **architecture multi-conteneurs** (api/worker/ffmpeg/ai/redis/reverse-proxy/monitoring) sur infrastructure dédiée **avec GPU et accès réseau caméras** — impossible dans la sandbox actuelle. Décision à prendre : conserver React+Mongo (pragmatique) **ou** s'aligner sur le CDC (Vue 3 + PostgreSQL) — un alignement total impliquerait une réécriture significative.

### 🎯 PRIORITÉ IMMÉDIATE recommandée (réalisable ici, fort ROI, sans infra GPU)
1. **Lot Sécurité (P1)** : reset password + rate-limit/lockout + refresh + CORS + cloisonnement par site.
2. **WebSocket alertes/statuts (P1)**.
3. **Métriques système réelles + pagination (P2)**.
4. **Alerte automatique sur plaque liste noire → notifications (P1)** : exploite l'existant (ANPR + notifications déjà en place) pour un scénario démo « vendeur ».

Le reste (RTSP/ONVIF/enregistrement/IA temps réel) doit être planifié sur une **infrastructure de production dédiée**, hors de l'environnement de développement actuel.

---
*Fin du rapport d'audit MG-VMS v1.0 — aucune modification de code effectuée.*
