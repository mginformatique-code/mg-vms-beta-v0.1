## MG-VMS Preview NG (v2.30) — État actuel

### Original Problem Statement
Refonte de MG-VMS vers une **plateforme plugin-oriented** (style Home Assistant) où le noyau est minimal et toutes les fonctionnalités (YOLO, ANPR, notifications, parking...) deviennent des plugins isolés avec cycle de vie indépendant. Le core ne connaît jamais l'implémentation d'un plugin, uniquement son **interface** (`FrameAnalyzer`, `PlateRecognizer`, `EventConsumer`).

### Personas
- **Utilisateur final** : installe uniquement les plugins nécessaires (résidentiel = 2, industriel = 15).
- **Intégrateur** : écrit un plugin, le publie sur Marketplace, plus besoin de fork.
- **Équipe MG-VMS** : noyau petit et testable (~5000 lignes Python).

### Architecture ancrée
- **Backend** : FastAPI + MongoDB + go2rtc strict gateway
- **Frontend** : React + Vite
- **Plugin Manager NG** (`/app/backend/plugin_manager/`) :
  - `interfaces.py` — contrats Plugin/FrameAnalyzer/PlateRecognizer/EventConsumer
  - `bus.py` — PluginBus fan-out (isolation crash + timeout + métriques)
  - `fusion.py` — 4 politiques ANPR (cascade/highest/compare/vote)
  - `policy.py` — store de politique persistant (JSON)
  - `builtin/` — wrappers YOLO/ALPR + MockPlate pour tests
  - `bootstrap.py` — enregistrement des plugins bundle au startup
  - `registry.py` — catalogue déclaratif des plugins

### Endpoints clés
- `GET /api/plugins` — catalogue déclaratif (6 plugins bundle)
- `GET /api/v1/plugins/bus` — instances runtime sur le bus (avec métriques)
- `POST /api/v1/plugins/bus/{name}/{enable|disable}`
- `GET /api/v1/plugins/policy` — snapshot politique multi-plugin
- `PUT /api/v1/plugins/policy/anpr` — change mode/threshold ANPR
- `PUT /api/v1/plugins/policy/frame-analyzer`
- `POST /api/v1/plugins/test/multi-anpr` — endpoint QA avec injection de mocks
- `GET /api/v1/diagnostics/ai-health`
- `GET /api/v1/diagnostics/streams-sync`

### CHANGELOG (Feb 2026 — session courante)
- **[NEW]** PluginBus multi-plugin (dispatch parallèle, isolation crash, timeout, métriques)
- **[NEW]** 4 politiques de fusion ANPR (cascade/highest/compare/vote — ADR-16)
- **[NEW]** PolicyStore persistant `/app/backend/data/plugin_policy.json`
- **[NEW]** Wrappers builtin YOLO/ALPR conformes aux interfaces plugin
- **[NEW]** MockPlatePlugin pour tests unitaires multi-ANPR
- **[NEW]** Endpoints `/api/v1/plugins/bus/*` + `/policy/*` + `/test/multi-anpr`
- **[NEW]** Bootstrap plugin bundle au startup (yolo-detection + fast-alpr)
- **[NEW]** Suite pytest `tests/test_multi_plugin.py` — 11 tests OK

### CHANGELOG (session précédente)
- Fix régression IA (retry, découplage YOLO/ALPR, plus de suicide loop)
- go2rtc gateway strict (frame_source + recorder)
- Endpoints diagnostics `ai-health` + `streams-sync`
- Chiffrement Fernet mots de passe caméras (crypto_utils.py)
- 28 chapitres de doc architecturale `/app/docs/mg-vms-next-gen/`
- Plugin Manager PoC (interfaces + context + registry)
- URL versioning `/api/v1/` (middleware alias)

### ROADMAP prioritaire
- **P0** : ✅ Multi-plugin ANPR/Tracking (fait — cette session)
- **P1** : Modulariser `routers.py` (1700+ lignes) → `/app/backend/routes/*.py`
- **P1** : Extraire YOLO de `ai_engine.py` en plugin isolé `/data/plugins/yolo-detection/`
- **P1** : UI Plugin Manager (Frontend Next Gen — page `/plugins` avec bus status + policy)
- **P2** : Mode Installateur (wizard 10-15 min)
- **P2** : Marketplace ecosystem (site + review process)
- **P2** : SDK Python (`mgvms-plugin-sdk`) publiable pip
- **P2** : Sandboxing sub-process + container
- **P2** : Manifest YAML + loader dynamique
