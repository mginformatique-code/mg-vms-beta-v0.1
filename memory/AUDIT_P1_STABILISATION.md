## MG-VMS · Audit de stabilisation (P1) — Feb 2026

**Objectif** : identifier les faiblesses concrètes du core avant toute nouvelle feature. Basé sur relecture des fichiers `ai_engine`, `streaming`, `recorder`, `diagnostics`, `frame_source`, `plugin_manager/`.

### ✅ Points forts observés
1. **AI health resilient loop** (`ai_engine.ai_loop`, `_ai_health` state) — retry silencieux si modèles KO, plus de suicide loop. ✅
2. **Diagnostics API existante** (`diagnostics.py`) — record_disconnect, record_reconnect, camera_recent_errors, camera_diagnostic_summary. Bonne fondation. ✅
3. **go2rtc gateway strict** dans `frame_source` et `recorder` — plus de RTSP direct. ✅
4. **Plugin Manager NG** — pipeline chaîné wired dans `ai_engine.ai_loop` sans double inférence. ✅
5. **Fernet encryption** sur les mots de passe caméras. ✅

### ⚠️ Faiblesses / risques identifiés
| # | Sujet | Fichier | Constat | Priorité |
|---|-------|---------|---------|----------|
| 1 | Pas de FPS/débit temps-réel | `streaming.camera_status_loop` | `_probe_status_once` retourne juste (status, message, ok). Aucune métrique FPS/bitrate agrégée par caméra. | HAUTE |
| 2 | Pas de historique de coupures affiché | `diagnostics.record_disconnect` | Les événements sont écrits en DB (`diagnostics_events`) mais aucun endpoint ne les liste par caméra pour la UI. | HAUTE |
| 3 | `recorder.recorder_loop` | `recorder.py:335` | Pas d'exposition d'un `recorder_health` par caméra (segments manquants, gap, ffmpeg PID vivant). | MOYENNE |
| 4 | Consommation CPU/GPU par caméra | inexistant | Pas d'agrégation par cam de la conso réelle (ffmpeg PID → psutil). | MOYENNE |
| 5 | PTZ WebRTC | `routers.py` | Pas de test automatisé. Bug historique mentionné, statut inconnu. | HAUTE (à reproduire) |
| 6 | ONVIF | `streaming.py` + `routers.py` | Bugs mentionnés dans historique, pas de test. | HAUTE (à reproduire) |
| 7 | Enregistrements incomplets | `recorder._index_segments` | Pas d'alerte si un segment attendu manque. Pas de validation post-hoc de continuité. | HAUTE |
| 8 | Watchdog FFmpeg | `recorder._start_ffmpeg` | Pas de supervision explicite du PID ni de restart si crash silencieux. | HAUTE |

### 📋 Actions concrètes recommandées
1. Créer `GET /api/diagnostics/health-dashboard` qui agrège **tout** :
   - Par caméra : status live, FPS (via go2rtc api/streams), débit (bitrate), erreurs FFmpeg récentes, coupures 24h, temps de reconnexion moyen, CPU/RAM du PID FFmpeg
   - Système : CPU global, RAM, GPU (via `_ai_health`), disque, uptime backend, connexions MongoDB, plugins bus status
   - Historique 24h : timeline des déconnexions par caméra
2. Créer `GET /api/diagnostics/camera/{id}/events` — historique des events diagnostic pour la caméra (pagination)
3. Créer `GET /api/diagnostics/recorder-health` — par cam : ffmpeg vivant ? dernier segment ? gap détecté ?
4. Ajouter un **watchdog FFmpeg** dans `recorder.recorder_loop` : si PID mort et cam active → restart auto + log dans diagnostics
5. Créer une page `/diagnostics/dashboard` (frontend) qui appelle l'endpoint agrégé, refresh 5s

### ✅ Fixes P1 appliqués (Feb 2026, session actuelle)
| # | Fix | Fichier | Détail |
|---|-----|---------|--------|
| A | **PTZ ONVIF réel** | `routers.py` + `streaming.py` | Endpoint `/api/cameras/{id}/ptz` ne renvoyait qu'un no-op `{"ok": true}`. Réécriture complète : `ContinuousMove` + `Stop` via `onvif_zeep`. 8 commandes supportées (pan/tilt/zoom + home + stop). Nouveaux endpoints `GET /ptz/presets` et `POST /ptz/preset/{token}`. |
| B | **UI PTZ 8-directions** | `LiveView.jsx` | Ancien : 3 boutons (zoom in/home/zoom out). Nouveau : croix directionnelle complète + colonne zoom + testids `ptz-up/down/left/right/home/zoom-in/zoom-out`. |
| C | **Recorder health endpoint** | `recorder.py` + `routes/health_dashboard.py` | Nouvelle fonction `get_recorder_health()` : ffmpeg alive, PID OS vivant, dernier segment, âge, gap détecté, continuité 24h (couverture % + trous listés). Exposé via `GET /api/diagnostics/recorder-health` et intégré dans le dashboard agrégé. |
| D | **Health dashboard UI** | `HealthDashboard.jsx` | Section Recorder refaite : indicateur FFmpeg alive (couleur rouge si mort), PID, âge du dernier segment, couverture 24h en %, count des gaps. |
| E | **Logo dark/light** | `Logo.jsx` + assets | Chargement des vrais assets `mg-vms-logo-light.png` / `mg-vms-logo-dark.png`. Retire le hack "backdrop blanc" du fallback. |
| F | **Tests régression** | `tests/test_ptz_and_recorder_health.py` | 7 tests couvrant PTZ (validation, rejets 400/404) et Recorder Health (shape endpoint, filtre par caméra, inclusion dans dashboard). 12/12 tests passent (avec pipeline + health existants). |

### ⏭️ Restant P1
- ONVIF audit : ok déjà robuste (`_onvif_probe` + probe séquentielle profils, gestion timeouts, `allow_rtsp_override`). Pas de bug reproductible identifié dans le code.
- Watchdog FFmpeg : ✅ déjà en place (`recorder.recorder_loop` + `record_disconnect` sur restart).
- Modularisation `routers.py` : reste 1810 lignes → à faire quand P1 stable.

