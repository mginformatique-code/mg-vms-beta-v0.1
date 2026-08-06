# MG-VMS · ROADMAP versionnée (v0.5.1.b)

**Objectif final** : Release Candidate v1.0 · plateforme VMS professionnelle
comparable à Milestone XProtect / Nx Witness / Genetec / Synology.

**Maturité globale actuelle** : **68 % → RC v1.0** *(estimation à date v0.5.1.b)*

Décomposition (poids relatifs) :

| Domaine | Poids | Avancement | Contribution |
|---|---:|---:|---:|
| Pipeline IA (unique, déterministe) | 15 % | 95 % | 14.3 |
| Camera Device Layer | 10 % | 85 % | 8.5 |
| Latence acquisition | 10 % | 90 % | 9.0 |
| Sécurité + HTTPS prod | 10 % | 80 % | 8.0 |
| Camera Center UI | 8 % | 75 % | 6.0 |
| Pipeline Center UI | 8 % | 80 % | 6.4 |
| Docker / Déploiement | 7 % | 80 % | 5.6 |
| Drivers constructeurs | 8 % | 45 % | 3.6 |
| Plugin Manager UX | 6 % | 40 % | 2.4 |
| Welcome Center | 4 % | 0 % | 0.0 |
| Monitoring temps réel | 5 % | 30 % | 1.5 |
| Tests régression | 5 % | 60 % | 3.0 |
| Documentation | 4 % | 25 % | 1.0 |
| **TOTAL** | **100 %** | | **≈68 %** |

---

## ✅ Tranches livrées

### v0.4.3 · Fermeture stricte pipeline (fail-safe)
- 3 points de fail-open éliminés, 1406 lignes code mort supprimées, une seule architecture pipeline
- 12/12 tests d'isolation stricte, benchmarks CPU-only

### v0.4.4 · Requirements + Docker refonte
- 3 fichiers `requirements*.txt` séparés (runtime / IA / dev), ~50 packages supprimés
- Dockerfile 2 layers pip stables, docker-compose.yml sans volumes nommés, .env.example durci

### v0.4.5.a · Latence pipeline acquisition
- Métriques `frames_produced/dropped/fps_capture_1min/warmup_ms`
- `_fetch_frame` non-bloquant strict, double encode/decode supprimé, warm-start automatique
- `AI_INTERVAL` par défaut 2.0 → 0.15 s (~6-7 FPS/caméra), backoff max 30 → 5 s
- 9/9 tests latence + endpoint `/api/diagnostics/capture/stats`

### v0.4.6 · Camera Device Layer
- `CameraDeviceService` + `CameraDriver` abstrait + `ONVIFDriver`/`ReolinkDriver`/`DahuaDriver`/`HikvisionDriver`
- 14 endpoints `/api/devices/*` avec mapping erreur → HTTP propre (jamais 500)
- Gardes de capacités (`UnsupportedCapabilityError`), registry avec fallback ONVIF
- 22/22 tests drivers, documentation `drivers/README.md`

### v0.5.0.a · Pipeline Center + Camera Center UI
- `PipelineCenter` 10 onglets · `CameraCenter` 11 onglets par caméra
- Hook `useDeviceCapabilities` centralisé, widgets conditionnels stricts
- 42/42 tests structurels

### v0.5.0.b · UX Unification
- Menu principal nettoyé (retiré pipeline-video/monitor/designer/inspector)
- Alias `/pipeline/designer`, `/pipeline/inspector`
- Camera Center enrichi : HealthBanner + prev/next + WebRTC embed + Events tab + Capabilities catégorisées + AI latences
- Cameras.jsx ligne cliquable → Camera Center
- 22/22 tests UX unification

### v0.5.1.b · Sécurité + déploiement production ⬅ **cette session**
- `nginx.conf` : HTTPS TLS 1.2/1.3, HSTS + CSP + X-Frame + Permissions-Policy, rate limit login 5r/min + API 100r/s, OCSP stapling
- `docker-compose.prod.yml` : Nginx + Certbot auto-renew, backend/frontend/go2rtc non exposés en direct, secrets obligatoires (`?requis`), CORS restreint au domaine prod
- Backend : `TrustedHostMiddleware` conditionné à `MGVMS_TRUSTED_HOSTS`
- 29/29 tests sécurité production

**Total tests actifs : 149/149 verts.**

---

## 🚧 Tranches restantes vers v1.0

### v0.5.1.a · Welcome Center + Menu final 7 items *(prochaine session)*
**Dépend de** : rien
**Contenu** : Welcome intelligent (score santé, changelog auto, alertes, tips), menu final Dashboard/Cameras/Pipeline/AI & Plugins/Events/Recordings/Settings
**Estimation** : ~3 h

### v0.5.1.c · Camera Wizard
**Dépend de** : v0.4.6 (device layer)
**Contenu** : Assistant ajout caméra · découverte réseau → détection constructeur → auth → probe capacités → tests RTSP/PTZ/audio/light → save
**Estimation** : ~4 h

### v0.5.1.d · Plugin Manager unifié
**Dépend de** : rien
**Contenu** : Onglets Installed/Marketplace/Configuration/Runtime/Logs/SDK · éradiquer terme "Extension"
**Estimation** : ~4 h

### v0.5.1.e · Audit code mort + rapport dette technique
**Dépend de** : rien
**Contenu** : Grep exhaustif imports/composants/CSS/routes inutilisés, cleanup, rapport chiffré
**Estimation** : ~3 h

### v0.5.1.f · Monitoring temps réel
**Dépend de** : v0.4.5.a (métriques capture)
**Contenu** : Dashboard CPU/GPU/VRAM/RAM/Mongo/go2rtc/Pipeline/YOLO/Tracking/Plugins/Workflows/Disques/Réseau + alertes + historique 24h
**Estimation** : ~4 h

### v0.5.2 · Drivers constructeurs supplémentaires
**Dépend de** : v0.4.6
**Contenu** : Axis VAPIX, Hanwha Sunapi, Uniview LAPI + tests contre mocks + validation matérielle
**Estimation** : ~2 h/driver

### v0.5.3 · Workflow Center complet
**Dépend de** : rien
**Contenu** : Moteur graphique SI/ALORS complet (plaque → portail, bookmark, clip vidéo, spotlight)
**Estimation** : ~6 h

### v0.5.4 · Documentation
**Dépend de** : tout ce qui précède figé
**Contenu** : README + Installation + Docker + HTTPS + Drivers + Plugins + API + Architecture + Pipeline
**Estimation** : ~1 journée

### v0.5.5 · Tests stress 30/50 caméras
**Dépend de** : machine RTX A2000 avec matériel réel
**Contenu** : Harness synthétique + validation terrain
**Estimation** : ~6 h + accès matériel

### v1.0-RC · Release Candidate
**Dépend de** : v0.5.1.* + v0.5.2 + v0.5.3 + v0.5.4 + v0.5.5
**Contenu** : Audit sécurité complet (`security_audit_agent`), audit régression complet (`testing_agent_v3_fork`), release notes, migration guide

---

## 🐛 Dette technique restante (à vider avant v1.0)

| Item | Impact | Effort | Priorité |
|---|---|---|---|
| Rate-limit brute-force casse CI parallèle (recur. 4 forks) | 🔥 tests régression | ~1 h | P1 |
| Aucun test E2E upload → CameraWorker | 🟠 régression silencieuse possible | ~1 h | P2 |
| Benchmarks GPU/VRAM absents (pod cloud sans GPU) | 🟠 promesse scale non prouvée | machine A2000 | P1 (machine) |
| Refactor `routers.py` monolithique → `routes/*` par domaine | 🟡 maintenabilité | ~3 h | P2 |
| `analyze_image_local` hardcode `enabled_plugins=["fast-alpr"]` | 🟡 UX upload manuel limitée | ~30 min | P3 |
| Tests React Testing Library réels (rendu vs invariants) | 🟡 confiance rendu | ~2 h | P2 |
| Health banner backend : endpoints `mongo_ok`, `go2rtc_ok`, `pipeline_ok`, `gpu_percent`, `vram_percent` | 🟠 UI attend ces champs | ~1 h | P1 |
| Rolling window `pipeline_metrics` imprécise | 🟡 diagnostic UI | ~30 min | P3 |
| `enabled_plugins` non validé à l'insertion Mongo | 🟡 config invalide silencieuse | ~30 min | P2 |
| Migration menu vers 7 items finaux (Dashboard/Cameras/Pipeline/AI&Plugins/Events/Recordings/Settings) | 🟡 UX | v0.5.1.a | P1 |

---

## Contraintes absolues (v0.5.1 onwards)

- ❌ Ne pas casser pipeline IA (v0.4.3 · 12 tests iso)
- ❌ Ne pas casser drivers (v0.4.6 · 22 tests)
- ❌ Ne pas casser Camera/Pipeline Center (v0.5.0.a/b · 64 tests)
- ❌ Ne pas casser Docker / Mongo (v0.4.4)
- ✅ Rétrocompatibilité routes existantes
- ✅ Chaque tranche = audit non-régression + tests + rapport + doc + roadmap + score maturité

---

## Prochaine session (v0.5.1.a)

**Cible** : Welcome Center intelligent + menu final 7 items
**Prérequis** : cette tranche v0.5.1.b déployée et validée par l'utilisateur
**Estimation avancement post-v0.5.1.a** : ~72 %
