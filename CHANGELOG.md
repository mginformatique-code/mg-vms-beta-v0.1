# CHANGELOG — MG-VMS

Format inspiré de Keep a Changelog. Dates au format AAAA-MM.

> Depuis Feb 2026, MG-VMS bascule sur un cycle interne de versions « pipeline »
> (v0.3 → v0.4 → v0.4.1 → v0.4.2 → v0.4.3) qui reflète la refonte vers une architecture
> modulaire Plugin Manager NG + Pipeline Engine v2 (style DeepStream/Frigate).
> L'ancien cycle produit (1.x/2.x) reste préservé en bas de fichier.

## [v0.5.2] — 2026-02 — Map Center · Phase 1 · Site Designer (Session 43)

### Contexte
Le menu "Carte" devient un vrai **Map Center**, chaînon manquant pour la
préparation d'installation, la documentation et l'audit d'un système. Phase 1
livrée avec l'architecture évolutive convenue (Client → Site → Bâtiment →
Niveau → Plan → Caméras → Zones), moteur **Konva.js / react-konva**.

### Added (backend)
- Nouveau module `backend/routes/site_manager.py` (préfixe `/api/site-manager/`).
- Nouvelle collection Mongo **`buildings`** : `{id, site_id, name, order, notes}`.
- Nouvelle collection Mongo **`site_plans`** : `{id, site_id, building_id?,
  level_name?, name, type, image_data_uri, scale_m_per_px?,
  orientation_deg?, unit, order, width, height}` — types :
  `satellite|rdc|etage|parking|entrepot|exterieur|drone|autre`.
- Extension champ **`map_position`** sur `cameras` (merge partiel) :
  `{plan_id, x, y, rotation, height_m, angle_h, angle_v, range_m,
    color, fixture, lens_mm, install_notes, technician, serial,
    install_date, real_height_m, real_angle, install_direction}`.
- Extension `SiteInput` : `client_name`, `phone`, `contact_name`, `notes`.
- Endpoints :
  * `GET/POST/PUT/DELETE /api/site-manager/buildings`
  * `GET/POST/PUT/DELETE /api/site-manager/plans` (list sans image par défaut,
    GET single avec image, validation `data:image/*` + limite 22 MB)
  * `GET /api/site-manager/cameras` (filtre `plan_id` ou `site_id`)
  * `PUT /api/site-manager/cameras/{id}/position` (merge partiel)
  * `DELETE /api/site-manager/cameras/{id}/position` (clear)
- Sécurité : scope `allowed_sites(user)` respecté à chaque route, écriture
  = rôle `technician`.
- Cascade : delete plan ⇒ désassocie automatiquement les caméras positionnées ;
  delete bâtiment ⇒ détache ses plans (garde-fou).

### Added (frontend)
- **Nouvelle page `MapCenter.jsx`** (route `/map`, ancien MapView reste
  disponible sur `/map-legacy`).
- Dépendances : `konva@10.3.0`, `react-konva@19.2.5`, `use-image@1.1.4`.
- Composants :
  * `SiteTree` — arbre Sites > Bâtiments > Plans, avec recherche, boutons
    "+ Bâtiment" et "+ Plan", compteurs de caméras par plan.
  * `PlanBackground` (`react-konva Image`) — précharge async.
  * `CameraNode` (`Konva Group`) — icône caméra + wedge FOV coloré (angle
    horizontal + portée), poignée drag&drop, statut visuel (dot vert/
    jaune/rouge), halo si sélectionné, double-clic → `/cameras?focus=id`.
  * `CameraPanel` (droite) — infos identité + position/FOV (rotation,
    portée, angle H/V, hauteur, objectif, fixation) + installation
    (technicien, N° série, date, notes) + badges plugins actifs +
    bouton "Voir dans Camera Center".
  * Toolbar canvas : Zoom in/out (molette centrée curseur), pan glisser,
    recentrer. Bornes `[0.15, 5]`.
  * Barre "Caméras à placer" (bas gauche) — placer une caméra du site
    au centre du plan en 1 clic. Auto-save de position (debounced 400 ms).

### Tests
- `tests/test_v052_site_manager.py` — **7 tests** :
  * CRUD bâtiments (create/list/patch/delete).
  * Lifecycle plans + projection MongoDB (list sans `image_data_uri`, GET
    single avec image).
  * Rejet image invalide (400).
  * Merge partiel `map_position` (patch `x` conserve `height_m`).
  * Delete plan cascade → caméras désassociées.
  * `SiteInput` accepte les nouveaux champs enrichis.
  * Authentification requise sur toutes les routes.
- 87/87 tests critiques v0.4.x/v0.5.x verts, zéro régression.

### Vision Phase 2+ (documentée dans MapCenter.jsx header)
Cônes FOV colorés (vert/jaune/rouge selon angle+portée), overlays câbles /
switches / NVR / baies / Wi-Fi / portes / zones intrusion / trajets, outils
de mesure (distance/surface/rayon), mode audit, export PDF/PNG, layers
on/off, overlay temps réel FPS/latence.


## [v0.5.1.d] — 2026-02 — Réorganisation menu + unification Plugin Manager (Session 42)

### Contexte
Demande utilisateur d'unification finale de la navigation :
1. Plugins + Modules doivent tous vivre dans `PluginManagerNG` (fin du split).
2. `Benchmark ANPR` accessible depuis le menu ANPR **du plugin** (plus en sidebar).
3. Rapports / Audit / Diagnostic / Notifications = **sous-menu** de Paramètres.
4. Ressources matérielles + Accélération GPU accessibles **uniquement** depuis
   le Pipeline Center (retirés de la sidebar).

### Changed
- **Route `/plugins`** pointe directement sur `PluginManagerNG` (l'ancien
  wrapper `Plugins.jsx` cardé n'est plus utilisé — l'UI unique est le
  Plugin Manager NG avec ses groupes ANPR/Detection/Tracking/etc.).
- **PluginManagerNG** : ajout d'un bouton **Benchmark** (icône Gauge) sur
  chaque plugin d'interface `PlateRecognizer` → navigation vers
  `/anpr-benchmark`.
- **Sidebar (`Layout.jsx`)** — nouvelle structure à 4 groupes :
  * **Opérations** — Accueil, Tableau de bord, Mur vidéo, Enregistrements,
    Caméras, Supervision réseau, Sites, Carte.
  * **Intelligence** — Événements IA, Recherche véhicule, Alertes,
    Zones intelligentes, Workflows.
  * **Administration** — Pipeline Center, Plugins, Utilisateurs.
  * **Journaux & Rapports** — Rapports, Journal d'audit, Journal de diagnostic.
  * **Paramètres** — Paramètres, Notifications.
  Retirés de la sidebar : Ressources matérielles, Accélération GPU,
  Benchmark ANPR (accessibles via Pipeline Center + Plugin Manager).
- **PipelineCenter** — deux nouveaux onglets : **Hardware** (Ressources
  matérielles) et **GPU** (Accélération GPU). Portes d'entrée uniques
  vers ces vues.
- **i18n** : nouvelle clé `nav.settings_group` (FR : "PARAMÈTRES" / EN :
  "SETTINGS").

### Removed
- Section dynamique "Extensions" (déjà retirée en v0.5.1.c).
- Loader `loadPluginMenus` / state `pluginPages` dans Layout (nettoyage).

### Tests
- 80/80 tests critiques v0.4.x + v0.5.1.x verts (isolation stricte,
  latence, drivers, Welcome, TESTING bypass, multi-plugin events).
- Vérification E2E via Playwright : sidebar sans les 4 entrées retirées,
  groupe PARAMÈTRES présent, `/plugins` = Plugin Manager NG, onglets
  Hardware + GPU visibles dans Pipeline Center.


## [v0.5.1.c] — 2026-02 — Multi-plugin events + Recherche véhicule enrichie (Session 41)

### Contexte
Retour utilisateur post v0.5.1.a : (1) bug TypeError dans Pipeline Center /
onglet Tracking, (2) demande de suppression du menu "Extensions" (tout via
`/plugins`), (3) besoin de visualiser la scène complète + crop OCR dans la
Recherche véhicule, (4) les événements et les plaques doivent refléter
**tous les plugins** ayant contribué (pas uniquement fast-alpr et yolo
hardcodés).

### Fixed
- **PipelineCenter · TrackingPanel** : le backend renvoie `runtime.trackers`
  comme dict `{camera_id: {...}}` mais le frontend attendait un array
  (`trackers.map`). Fix défensif : normalisation dict → array côté client.

### Changed
- **Menu latéral** : suppression complète de la section dynamique
  "Extensions" (`Layout.jsx`). Tous les plugins sont accessibles depuis
  l'entrée statique `/plugins` (Plugin Center). Le sous-lien
  `/anpr-benchmark` (technicien) migre dans le groupe Administration.
- **VehicleSearch** (Recherche véhicule) : cartes cliquables ouvrant un
  **modal détail** avec :
  - Scène complète (`frame_thumb`)
  - Crop véhicule (YOLO)
  - Crop OCR (plaque)
  - Badges plugins utilisés + table des lectures multi-moteurs
    (`engine` + plaque lue + confiance %)
- **EventViewer** : priorité au champ unifié `plugins_used` pour afficher
  la liste multi-plugins (au lieu des champs séparés detectors/trackers/
  segmenters/engine).

### Added (backend)
- `pipeline_v2/downstream.py` :
  - Helper `_compute_plugins_used(cam)` → liste ordonnée sans doublons
    (CORE `yolov11`+`bytetrack`+`fast-alpr` + whitelist caméra).
  - Fonction extraite `_prerun_multi_anpr()` : dispatch multi-moteurs
    ANPR **AVANT** l'écriture des events YOLO, permettant la corrélation
    par `track_id`.
  - Index `result["_anpr_by_track"]` : par track véhicule, la liste de
    toutes les lectures ANPR (moteur, plaque, confiance, crop).
  - Chaque **event** (Mouvement / Visage / YOLO) reçoit désormais :
    * `plugins_used: [...]`
  - Chaque event YOLO reçoit en plus :
    * `plate` (consensus, plus confiante)
    * `plate_confidence`
    * `anpr_readings: [{engine, plate, confidence, plate_crop}, ...]`
    * `track_id`
  - Chaque **plaque** persistée reçoit :
    * `plugins_used`
    * `anpr_readings` (toutes les lectures multi-moteurs pour ce track)
    * `track_id`
- La règle de fermeture stricte v0.4.3 est **conservée** dans le nouveau
  helper `_prerun_multi_anpr` (whitelist vide ⇒ zéro dispatch, zéro plugin).

### Tests
- `tests/test_v051c_multi_plugin_events.py` — **10 tests** :
  * `_compute_plugins_used` : CORE toujours présent, whitelist ajoutée,
    pas de doublons, `enabled_plugins=None` supporté.
  * `run_downstream` annote events + plaques avec `plugins_used`.
  * Events YOLO embarquent `anpr_readings` + `plate` best-of.
  * `_prerun_multi_anpr` existe et ferme strictement.
  * Ordre : dispatch multi-ANPR AVANT écriture events YOLO.
- `tests/test_v043_strict_isolation.py` : test source path mis à jour
  (logique déplacée de `run_downstream` vers `_prerun_multi_anpr`).
- 94/94 tests critiques v0.4.x/v0.5.1.x verts.


## [v0.5.1.a] — 2026-02 — Welcome Center + TESTING=1 bypass (Session 40)

### Contexte
Après la Sécurité/Prod (v0.5.1.b) et l'alignement produit sur les 8 Centers,
cette tranche livre l'écran d'accueil officiel de MG-VMS et purge la dette
technique du rate-limit qui cassait la CI pytest depuis 5 forks consécutifs.

### Added
- **Welcome Center** (`/app/frontend/src/pages/WelcomeCenter.jsx`) : nouvelle
  route `/` remplaçant le Dashboard historique (accessible désormais à
  `/dashboard`). Composé de :
  - Health score global 0-100 avec ring animé + statut par composant (GPU,
    Mongo, Pipeline, go2rtc, Disque, CPU, RAM, Caméras, Plugins).
  - Version installée + build date + bandeau "nouveautés disponibles" +
    bouton `Voir le changelog`.
  - 4 stats express (Caméras en ligne, Événements 24h, Plaques 24h, Alertes
    actives) auto-scoped aux sites de l'utilisateur.
  - Alertes système auto-déduites (disque critique/faible, MongoDB KO, GPU
    absent, go2rtc HS, plugins en erreur, caméras offline).
  - Actualités administrateur (nouvelle collection `welcome_news`, publication
    admin only via UI `welcome-news-create-btn`, épinglage + sévérité info /
    warning / critical).
  - Conseils contextuels (5 tips dépendant de l'état système).
  - Accès rapide aux 8 Centers (Live, Camera, Pipeline, Plugin, Event,
    Recording, Dashboard, Settings) sous forme de tuiles cliquables.
  - Section changelog (parsing de `CHANGELOG.md`) affichant les nouveautés
    depuis la dernière version consultée par l'utilisateur.
  - Documentation & liens externes (Doc, GitHub, Changelog, Support).
  - Préférences per-user (`welcome_prefs`) : `hide_until_next_version`,
    `always_show`, `important_only`, `last_seen_version` + bouton "Marquer
    comme lu".
- **Route module** `backend/routes/welcome.py` exposant :
  - `GET /api/welcome/summary` — payload agrégé unique < 200 ms.
  - `GET /api/welcome/changelog?since_version=X&limit=N` — parseur CHANGELOG.
  - `GET|PUT /api/welcome/preferences` — persistance des prefs.
  - `GET /api/welcome/news` (auth) + `POST|DELETE /api/welcome/news` (admin).
- **Menu latéral** (`components/Layout.jsx`) : `nav.welcome` (Accueil, "/")
  et `nav.dashboard` (Tableau de bord, "/dashboard") séparés.

### Fixed
- **Rate-limit brute-force casse la CI (dette récurrente 5 forks · P1)** :
  ajout d'un bypass complet lorsque l'env `TESTING=1` est actif, dans
  `security.py` (`SecurityMiddleware.dispatch`) et `auth.py`
  (`_check_lockout` / `_register_failure`). `conftest.py` force ce flag pour
  toute campagne pytest. Résultat : plus de 429/423 durant les tests
  parallèles.

### Tests
- **Backend** : `tests/test_welcome_center.py` (8 tests HTTP live) +
  `tests/test_testing_bypass.py` (5 tests unitaires du bypass). 13/13 verts.
  84 tests critiques `v0.4.x` (isolation stricte, latence, drivers, ANPR
  qualité, pipeline per-camera) toujours verts — zéro régression.
- **Frontend** : validé par testing_agent (100 % succès, aucune anomalie
  UI/UX, tous les data-testid présents, prefs persistent après reload).

### Statistiques diff
+960 / -3 lignes (essentiellement WelcomeCenter.jsx + routes/welcome.py).


## [v0.4.3-stable] — 2026-02 — Stabilisation stricte (audit critique · 10 priorités)

### Contexte
Après un audit technique critique de la refonte v0.4.3, dix défauts structurels
ont été identifiés (fail-open sur `enabled_plugins=[]`, double encode/decode
RTSP, ~980 lignes de scaffold parallèle mort, fusion ANPR dupliquée, champs
morts dans `FrameContext`, deux `Frame` coexistantes, upload manuel hors
pipeline, absence de benchmarks réels, absence de test d'isolation, règle
d'auto-déclenchement non explicite). Cette version corrige les 10 points.

### Fixed
- **P1 · Fermeture stricte fail-safe** — `enabled_plugins` null/vide/absent ⇒
  0 plugin dispatché (jamais fail-open). Modifié : `plugin_manager/bus.py`
  (`dispatch_pipeline._filter`, `dispatch_frame`, `dispatch_plate`),
  `pipeline_v2/camera_worker.py::_stage_anpr`,
  `pipeline_v2/downstream.py` (multi-ANPR). Preuve : `consumer_calls=0` sur
  10 consumers avec whitelist vide (bench + test).
- **P2 · Double encode/decode supprimé** — `_fetch_frame` retourne un
  `ndarray` directement (frame_source RTSP direct), `_stage_decode` accepte
  `ndarray | bytes`. Économie mesurée : ~6-10 ms/frame/caméra CPU.
- **P4 · Fusion ANPR unique** — `pipeline_v2/fusion.py::FusionEngine`
  supprimé, `anpr_tracker.record_reading` = seule source de vérité.
- **P5 · FrameContext nettoyé** — champ mort `plate_rois` supprimé.
- **P6 · Frames unifiés** — `FrameContext.as_plugin_frame()` construit un
  `plugin_manager.Frame` partageant buffer numpy + cache JPEG (memoization).
- **P7 · Upload manuel unifié** — `analyze_image_local` réécrit en wrapper
  thin `CameraWorker("__upload__").analyze(bytes, ["fast-alpr"])`.
  Suppression de la seconde implémentation YOLO+ALPR de `ai_engine.py`.

### Removed
- **P3 · 1 406 lignes de code mort supprimées** (7 fichiers dans
  `pipeline_v2/` + 2 fichiers de tests morts) :
  `engine.py`, `stages.py`, `interfaces.py`, `adapter.py`, `scheduler.py`,
  `fusion.py`, `providers/*`, `tests/test_pipeline_v2.py`,
  `tests/test_yolo_provider_and_ui.py`. Une seule architecture pipeline
  en vie : `CameraWorker + Downstream + PluginBus`.

### Added
- **P8 · Benchmarks réels enregistrés** — `/app/benchmarks/results_v043.md`
  (+ `.json`). Mesures CPU/timings sur 1/5/10/20/**30/50** plugins.
  GPU/VRAM marqués explicitement "non mesurés (pod cloud)" — jamais
  fabriqués. Résultat clef : encodes ROI 80→4 pour 20 moteurs ANPR
  (×20 en encodes économisés), dispatch bus scale linéairement à 50 plugins.
- **P9 · Tests non-régression isolation** —
  `backend/tests/test_v043_strict_isolation.py` (11 tests) :
  fail-safe list vide/null/absente, `dispatch_plate` exige `only`,
  isolation caméra-caméra, aucune fuite téléobjectif→grand-angle,
  aucun partage de `_plate_cache` entre workers.

### Règle absolue (v0.4.3-stable)
Aucun plugin ne peut s'auto-déclencher. Le **CameraWorker est l'unique
autorité** qui décide des plugins dispatchés. Aucun fallback, aucun
auto-dispatch, aucune découverte implicite. Cette règle est encodée dans le
docstring de `pipeline_v2/__init__.py`.

### Statistiques diff
+275 / -1666 lignes = **-1 391 lignes nettes**.


## [v0.4.3] — 2026-06 — Refonte finale « Architecture First » : Pipeline Engine v2 en production
### Changé — Runtime pipeline-driven (remplace le monolithe)
- **`ai_engine.py` : 1557 → ~500 lignes.** Ne fait plus QUE : acquisition RTSP
  (`_fetch_frame`, `_sync_frame_source_workers`), chargement modèles (YOLO/ALPR),
  config runtime, et boucle `ai_loop` qui démarre les CameraWorker. Toute la
  logique métier est sortie du fichier (wrappers de compat conservés :
  `_analyze_frame`, `_do_downstream_work`, re-exports scénarios).
- **Nouveau runtime** : `PipelineRuntime → CameraWorker → FrameContext → Stages → PluginBus`.
  - `pipeline_v2/camera_worker.py` — un worker PAR caméra (état strictement isolé :
    motion, tracker, cache plaques). Stages : decode → motion → yolo → tracking → roi → anpr.
  - `pipeline_v2/frame_context.py` — **FrameContext unique** (frame, timestamp, camera_id,
    fps, detections, tracks, vehicle_rois, cache, metadata) passé par référence à tous
    les stages/plugins. JPEG data-URI memoizé par (taille, qualité).
  - `pipeline_v2/downstream.py` — travail métier hors chemin critique (events, faces,
    bus, smart zones, workflows, multi-ANPR, persistance plaques).
  - `pipeline_v2/scenarios.py` — scénarios IA + armement sortis d'ai_engine.
### Ajouté — Tracking UNIQUE (fin du double tracking)
- **`pipeline_v2/tracking.py` · TrackerPool** — UN tracker par caméra, instances jamais
  partagées. Les plugins tracker (bytetrack/botsort/deepsort/ocsort/strongsort) sont
  **convertis en choix d'algorithme du TrackingStage** (bytetrack=sv.ByteTrack core,
  botsort=ultralytics BOTSORT ; autres → fallback bytetrack tracé).
- **`bus.dispatch_pipeline(precomputed_tracks=...)`** — les plugins Tracker ne sont
  **JAMAIS dispatchés** quand le core fournit les tracks (`plugins_used.trackers =
  ["core-tracking-stage"]`). Test de preuve : un SpyTracker enregistré n'est jamais appelé.
### Ajouté — Cache ROI + JPEG partagés (fin des encodes redondants)
- **`VehicleROI`** — crop véhicule extrait UNE fois (vue numpy zéro-copie), JPEG et
  data-URI memoizés. fast-alpr ET tous les moteurs cloud lisent les mêmes pixels.
- **`Frame.jpeg(quality)`** (plugin_manager) — encodage JPEG partagé memoizé. Les 5
  plugins ANPR cloud (plate-recognizer, openalpr, google-vision, azure-vision,
  codeproject-ai) n'appellent plus `cv2.imencode` en chemin partagé.
- **Thumbnails YOLO lazy** — le crop d'une détection n'est encodé QUE si un événement
  est réellement inséré (cooldown-gated), plus à chaque frame.
- **`bus.dispatch_plate(only=whitelist)`** — les moteurs hors whitelist caméra ne sont
  jamais appelés (avant : dispatch à tous puis filtrage des résultats = appels API gaspillés).
### Ajouté — Pipeline Inspector (diagnostic complet)
- **`pipeline_v2/inspector.py`** + `GET /api/diagnostics/pipeline-inspector` (+ `/reset`) —
  par caméra × stage (fetch/decode/motion/yolo/tracking/roi/anpr/dispatch/multi_anpr/
  scenarios/persist/websocket/downstream) : avg/max/last ms, fenêtre 60s, appels, erreurs,
  timeouts, FPS effectif. Système : CPU, RAM, GPU, VRAM. Workers + trackers actifs.
- **Page React `/pipeline-inspector`** (menu technicien) — tableau temps réel par caméra,
  badge « tracker unique : bytetrack », cartes CPU/RAM/GPU/uptime, refresh 5s.
### Ajouté — Benchmarks obligatoires (mesures réelles avant/après)
- **`scripts/benchmark_pipeline.py`** → `/app/benchmarks/pipeline_v2_benchmark.{json,md}` :
  - Tracking : 0.715 ms (2 trackers) → **0.367 ms (1 tracker)** = 2×
  - Crops+JPEG ANPR (4 véhicules) : 20 moteurs = 14.65 ms / **80 encodes** → **0.75 ms / 4 encodes** (20×)
  - Dispatch bus 20 plugins : 1.42 ms broadcast → 1.11 ms per-camera (+ zéro travail plugin hors whitelist)
  - YOLO : 263 ms avg CPU 1080p (une seule inférence, inchangé)
### Préservé (aucune régression)
- Whitelist ANPR per-camera (fix critique v0.4.1), auto-suspension qualité nocturne,
  caméras ANPR spécialisées (Dahua ITC / Hikvision DeepInView), graph registry per-camera,
  stats plugins per-camera, MongoDB SSD / recordings HDD / CUDA / Docker bind mounts.
### Tests
- 25 nouveaux (`test_v043_pipeline_engine.py` + `test_v042_pipeline_inspector_api.py` du
  testing agent) + périmètre complet : **73/73 OK** (testing agent iteration_39, 0 bug critique).
- Échecs préexistants hors périmètre (inchangés) : test_iter30 (guard go2rtc ère v0.2),
  test_iter32 ×4 (forme catalogue plugins).

## [v0.4.2] — 2026-02 — Pipeline per-camera + ANPR Qualité intelligente (P0 · P1 · P2)
### Ajouté — P0 · Fondation architecturale
- **`pipeline_v2/registry.py`** — `CameraGraphRegistry` : compile un **graphe d'exécution unique par caméra** basé sur sa whitelist `enabled_plugins`. Précalcule quelles étapes (`detection`, `tracking`, `segmentation`, `business`, `anpr`) doivent tourner et la liste exacte des plugin names dispatchables par étape.
  - Cache invalidé au hash (whitelist qui change → rebuild)
  - Rebuild automatique sur `register` / `unregister` / `set_enabled` du bus (via `bump_bus_version()`)
  - Résultat : **si une caméra n'a que fast-alpr et bytetrack activés, les 8 PipelineConsumers globalement actifs (person-counting, vehicle-counting, smoke-detection, etc.) ne sont JAMAIS dispatchés pour elle** → zéro CPU/VRAM, zéro compteur incrémenté.
- **Stats plugins per-camera** (`plugin_manager/bus.py`) — le `PluginBus` maintient désormais `_per_camera_stats[camera_id][plugin_name] = {calls, errors, timeouts, last_ms, last_error}` réellement mesurés. `_call_one()` accepte un paramètre `camera_id` et incrémente les deux compteurs (global + per-camera). Preuve visuelle dans l'UI que les plugins désactivés pour une caméra ne s'exécutent effectivement pas pour elle.
- **Skip early dans `_do_downstream_work`** : le check `_pipeline_plugins_active = graph.needs_tracking or graph.needs_segmentation or graph.needs_business` court-circuite complètement l'import du bus, la reconstruction des Detection() et le dispatch quand aucun plugin pipeline n'est activé pour la caméra.
- **Whitelist per-camera aussi sur multi-moteur ANPR** : le fan-out `dispatch_plate` respecte désormais `cam.enabled_plugins` (filtrage sur les entries AVANT et APRÈS dispatch — double sécurité).

### Ajouté — P1 · ANPR Auto-suspension qualité
- **`pipeline_v2/anpr_quality.py`** — `AnprQualityController` : évalue chaque frame véhicule sur 3 axes (luminosité, netteté via Laplacian, contraste) + détection heure de nuit. Score composite 0.0-1.0.
- **Machine à états ACTIVE ↔ SUSPENDED** avec hystérésis N/M cycles configurable (défaut : 5 bad → suspend, 3 good → resume). Anti-blip.
- **Message UI clair** : `"ANPR suspendu automatiquement — sharpness=42 < 100 (flou)"`, `"ANPR repris — conditions redevenues favorables (score=0.68)"`.
- **Principe métier** : "pas de plaque > fausse plaque" — mieux vaut suspendre que générer des lectures erronées.

### Ajouté — P2 · Caméras ANPR spécialisées
- **`SPECIALIZED_ANPR_MODELS`** : détection par `camera.model` de Dahua ITC (413/237/215/352), Hikvision DeepInView (iDS-2CD7A / iDS-2TD81), Axis P1465-LE, Bosch AutoDome IP starlight. Ces caméras **bypass complètement l'auto-suspension** → OCR 24/7 même en nuit noire.
- État exposé : `is_specialized: true, specialized_model: "Dahua ITC413 · ANPR 24/7 dédié"`.

### Ajouté — Endpoints (6 au total)
- `GET  /api/diagnostics/pipeline-v2` → graphes per-camera + stats registry
- `GET  /api/diagnostics/pipeline-v2/stats` → `per_camera` × `per_plugin` (compteurs runtime)
- `POST /api/diagnostics/pipeline-v2/invalidate?camera_id=…` → force rebuild
- `GET  /api/diagnostics/anpr-quality` → états auto-suspension par caméra
- `PUT  /api/diagnostics/anpr-quality/config` → reconfigure à chaud (min_score, seuils, hystérésis)
- `POST /api/diagnostics/anpr-quality/reset` → force reprise immédiate

### Vérifié
- **28 nouveaux tests** : 14 P0 (`test_v041_pipeline_per_camera.py`) + 14 P1/P2 (`test_v042_anpr_quality.py`)
- **76/76 tests** pipeline v0.4.x + v0.3 = **verte totale**
- **Preuve runtime P0** : sur `demo-cam-002` avec whitelist `["yolo-detection", "bytetrack", "fast-alpr"]`, seul `bytetrack` apparaît dans `per_camera_stats` (4 calls, 1.18ms) — les 8 PipelineConsumers globaux ne sont jamais appelés pour cette caméra.
- **Preuve runtime P1** : sur `demo-cam-002` (mire testsrc2 = score qualité 0.30-0.33), `consecutive_bad` progresse cycle par cycle → auto-suspension après 5 cycles.

### Backlog restant v0.4.1
- P1 · Zero-copy dispatch (Issue #3) — non traité cette session (refacto large des paths mémoire)

## [v0.4.1] — 2026-02 — Fix critique ANPR whitelist (Session 16)
### Corrigé (🔴 P0 critical)
- **Bug MongoDB pollution** : le pipeline OCR (`_alpr.predict` dans `ai_engine._analyze_frame`) tournait **hors du Plugin Manager** et ignorait `enabled_plugins`. Résultat : FastALPR désactivé sur une caméra → des plaques étaient malgré tout écrites en Mongo.
- **Fix appliqué** : signature `_analyze_frame(camera_id, frame_bytes, enabled_plugins=None)` + guard `_anpr_skipped = bool(enabled_plugins) and "fast-alpr" not in enabled_plugins`. Le bloc OCR est court-circuité (aucun `_alpr.predict`, aucune écriture Mongo, aucun événement). `_process_camera` passe `cam.get("enabled_plugins")`. Comportement legacy (whitelist vide) préservé.
- **Correctif intermédiaire** : premier fix causait `UnboundLocalError` (`timings["alpr_ms"]=0.0` avant que le dict soit créé). Corrigé avec variable locale `t_alpr = 0.0` initialisée avant le bloc.
### Vérifié
- `bug_testing_agent` verdict **fixed** : sur 35s + 60s de fenêtre "disabled", 0 nouvelle plaque écrite en Mongo (700 → 700), logs confirment `alpr_ms=0ms` frame par frame. Réactivation fast-alpr → 75 ms sur une frame véhicule. Regression endpoints frame-source/bus/catalog OK.
- Tests : 5 nouveaux `test_v041_anpr_whitelist.py` + 71 régression = **76/76 OK**.
### Backlog (points reportés du prompt v0.4.1)
- Pipeline IA par caméra (graphe distinct par cam)
- Statistiques plugins fidèles (calls/errors/timeout/fps)
- Optimisation zero-copy dispatch
- Qualité ANPR intelligente + auto-désactivation OCR (jour/nuit)
- Détection caméras spécialisées (Dahua ITC / Hikvision DeepInView)

## [v0.4 · Pipeline v2] — 2026-02 — Refonte architecture IA (Sessions 14 & 15)
### Ajouté — Session 14 · Pipeline Engine v2 (fondations)
- **Bascule majeure** : le **Pipeline Engine** devient le chef d'orchestre au lieu du Plugin Manager. Les plugins ne pilotent plus, ils **fournissent** (providers) ou **consomment** (consumers).
- Nouveau package `/app/backend/pipeline_v2/` (6 modules, ~1100 lignes) :
  - `interfaces.py` — Protocols `DetectionProvider` / `TrackingProvider` / `PlateRecognitionProvider` / `PipelineConsumer` + dataclasses `Frame` / `BBox` / `Detection` / `Track` / `PlateResult`
  - `fusion.py` — 6 stratégies configurables par caméra
  - `stages.py` — 5 étapes avec timeout + timing par stage
  - `engine.py` — `build_default()` + `stats()` + `describe()`
  - `scheduler.py` — multi-caméra FPS/priorité/backpressure
  - `adapter.py` — compat rétro v1 (les 50 plugins existants continuent à tourner)
- **Format PlateResult standard obligatoire** : `plate`, `confidence`, `bbox`, `country`, `processing_time_ms`, `provider`, `raw_text`, `vehicle_type`, `vehicle_color`, `track_id`, `extras`.
- **Tracking centralisé + ROI unique partagée** : 1 crop par véhicule réutilisé par TOUS les providers ANPR.
- **Parallélisme providers** via `asyncio.gather` + `to_thread`.
- Tests : 17 nouveaux + 52 régression = **69/69 OK**.

### Ajouté — Session 15 · Provider natif YOLO + Designer + Overlay caméra
- 🎯 **YoloDetectionProvider natif** (`pipeline_v2/providers/yolo_provider.py`) — implémente `DetectionProvider` v2, réutilise `ai_engine._model` (aucune duplication modèle), gère fallback si YOLO pas chargé.
- 🧩 **Pipeline Designer UI** (`/pipeline-designer`) — assemble Camera → Detector → Tracker → ANPR → Fusion → Consumer, catalogue de plugins filtré par interface, sélection multi-providers, 6 stratégies fusion configurables, config JSON compilée en preview. Remplacera à terme le Plugin Manager.
- 🎛️ **CameraControlOverlay** (`/pages/CameraControlOverlay.jsx`) intégré à LiveView — 5 boutons overlay (Projecteur / IR / Sirène / TTS / Reboot) apparaissent au hover sur chaque tuile caméra, actions via `POST /cameras/{id}/relay/{token}/{on|off}`, `POST /cameras/{id}/audio/tts`, `POST /cameras/{id}/reboot`.
- 🧭 Menu enrichi avec "Pipeline Designer" (section technicien).
- Tests : 6 nouveaux `test_yolo_provider_and_ui.py` + 69 régression = **75/75 OK**.

## [v0.4 · Stabilisation] — 2026-02 — Sprint correctifs Docker/GPU/ByteTrack (Session 13)
### Corrigé
- 🐳 **Docker plugins** : `context: ../backend` → `context: ..` (racine repo) + `dockerfile: backend/Dockerfile`. Le Dockerfile ajoute `COPY backend/`, `COPY backend/wsdl/`, `COPY data/plugins/` + assertion build-time (échec build si <40 plugins). Fin des 2 plugins fallback en Docker.
- 🔍 **Plugin Loader** : `_resolve_plugins_dir()` enrichi avec le candidat canonical `<backend>/data/plugins` (chemin Docker v0.4) + log clair `plugins_dir: /app/data/plugins (contient 50 entrées)`.
- 🔄 **Sync runtime ByteTrack** : `PUT /api/plugins/tracking/config` appelle désormais `load_runtime_config()` immédiatement → les paramètres UI sont réellement appliqués au moteur IA sans redémarrage.
- ⚠️ **Message ONVIF clair** : `onvif_camera()` fait un preflight sur `devicemgmt.wsdl` et lève une `FileNotFoundError` explicite ("PAS un problème d'identifiants — reconstruisez l'image Docker") au lieu du message générique trompeur.
### Ajouté
- 📊 **GPU boot log** : `server.on_startup` logge `GPU · Torch=X TorchVision=Y CUDA=OK/INDISPONIBLE (vN) · Device=<name> · N GB`.
- 📈 **Runtime state** : `GET /api/diagnostics/pipeline-metrics` retourne un nouveau champ `runtime` avec `bytetrack` (état réel du moteur), `ai_config` et `gpu` (Torch/CUDA/device). Fin du bug "ByteTrack=False dans monitoring".
### Vérifié
- Tests : 9 nouveaux `test_v04_stabilization.py` + 43 régression = **52/52 pytest OK**.
- `bug_testing_agent` (iteration_36) : verdict **fixed** — 12/12 checks API + 17/17 pytest, 50 plugins chargés sans fallback, WSDL 7/7, ByteTrack sync validé (track_thresh=0.3 appliqué immédiatement), GPU/Torch exposés.

## [v0.4 · WSDL] — 2026-02 — ONVIF WSDL embarqués (Session 12)
### Corrigé
- 🛠️ **Diagnostic** : le package `onvif-zeep-async` distribué via PyPI ne bundle plus les fichiers WSDL → `ONVIFCamera(...)` échouait avec `FileNotFoundError` sur tous les endpoints (PTZ, découverte, capabilities).
### Ajouté
- 📦 **34 WSDL/XSD embarqués** dans `/app/backend/wsdl/` (versionnés dans git, dont les 7 essentiels : devicemgmt, media, media2, ptz, events, imaging, deviceio).
- 🏭 **Factory centralisée** `wsdl_path.onvif_camera()` — remplace tous les appels directs à `ONVIFCamera()`, injecte automatiquement `wsdl_dir=WSDL_DIR`.
- 🔧 **10 callsites migrés** : 6 dans `routes/camera_control.py` + 4 dans `streaming.py` (PTZ, IR, relais, capabilities, reboot, device_info).
- ✅ **Validation au démarrage** : `validate_wsdl_dir()` log `7/7 essentiels + 16/16 optionnels présents` — warning explicite si un fichier manque.
- 🚢 **Dockerfile** enrichi : `COPY wsdl/ ./wsdl/` explicite + assertion build-time.
- 🌐 **Env override** `MGVMS_WSDL_DIR` pour déploiements exotiques.
- 🔍 **Nouveau endpoint** `GET /api/diagnostics/wsdl` pour l'UI/monitoring.
### Vérifié
- Tests : 8 unitaires + 35 régression = **43/43 OK**.

## [v0.3 · Config Caméra Modulaire] — 2026-02 — Whitelist plugins par caméra (Session 11)
### Ajouté
- 🎛️ **Nouveau champ** `Camera.enabled_plugins: list[str]` (whitelist des plugins IA activés pour cette caméra — 0 à N plugins).
- 🔌 **Nouvel endpoint** `GET /api/plugins/catalog` — 50 plugins regroupés en 12 catégories principales (ANPR/LPR, Détection IA, Tracking, Segmentation, Feu/Fumée, Sûreté active, EPI, Comptage, Retail, Parking, Agriculture, Notifications, Événements) avec icônes lucide-react.
- 🔀 **Filtrage `dispatch_pipeline`** : si `camera_config.enabled_plugins` non vide, seuls les plugins listés (par `name`) sont dispatchés — sinon fallback legacy (tous les plugins actifs).
- ⚙️ **`ai_engine._do_downstream_work`** passe `enabled_plugins=cam.get("enabled_plugins")` au bus.
- 🎨 **Nouveau composant React `CameraPluginsConfig.jsx`** : catalogue interactif avec recherche live, expand/collapse par groupe, sélection multi (tout activer/retirer, cocher tout par groupe), badges d'interface (`PipelineConsumer` / `PlateRecognizer` / `Tracker`…).
- 🔧 **`Cameras.jsx`** : le composant s'affiche quand `detect_enabled=true` (la case reste comme kill-switch global caméra).
### Vérifié
- Tests : 6 unitaires + 13 HTTP e2e + 30 régression = **49/49 OK** (testing_agent iter35, zéro bug).

## [v0.3 · Audit RTSP/ANPR] — 2026-02 — Découplage go2rtc final (Session 10)
### Corrigé
- 🧹 **Garde-fou supprimé** dans `frame_source.start()` — plus de refus d'URL non-go2rtc.
- 🐧 **ffmpeg 5.1.9 installé** dans le container (`apt-get install -y ffmpeg`).
- 🔀 **Workers démos** : `_sync_frame_source_workers` démarre aussi un worker persistant pour les caméras démo (via `rtsp://127.0.0.1:8554/cam_XXX` — go2rtc en local) au lieu de skipper.
- ⚙️ **GO2RTC_RTSP=rtsp://127.0.0.1:8554** ajouté à `.env` (résolution hostname `localhost`→`::1` refusée par ffmpeg dans le container Kubernetes).
### Ajouté
- 📊 **Métrique alpr_ms** : maintenant enregistrée dans `pipeline_metrics.record_stage()` — visible dans le dashboard.
- 🎯 **ANPR par crop véhicule** : `_alpr.predict(vehicle_crop)` remplace `_alpr.predict(img)` — meilleure précision, associations plate↔owner naturelles.
- 🔍 **Nouvel endpoint** `/api/diagnostics/frame-source` — état runtime des workers ffmpeg (alive/last_frame_age/restart_count).
- 📉 **Cache `_plate_cache` raccourci à 1s** — laisse anpr_tracker gérer les doublons via track_id, permet multi-OCR par véhicule mobile.
### Résultats mesurés (avant → après)
| Métrique | Avant | Après (p95) | Gain |
|---|---|---|---|
| fetch_ms | 2720 ms | **3-4 ms** | **~700×** |
| yolo_ms | 128 ms | 138 ms | idem |
| tracking_ms | 2 ms | 1 ms | idem |
| alpr_ms | 0 (non affiché) | **36 ms** | affiché ✓ |
| realtime_ms | 2895 ms | 260 ms avg | **11×** |
| downstream_ms | 9 ms | 13 ms | idem |
| Workers actifs | 0 | **1** (demo-cam-002) | ✓ |
### Vérifié
- Tests : 6 unitaires audit + 23 régression = **29/29 OK**.

## [v0.3 · Séparation IA/Streaming] — 2026-02 — Découplage moteur IA / go2rtc (Session 9)
### Ajouté
- 🎯 **Découplage go2rtc / IA** : `_sync_frame_source_workers` lit désormais l'URL RTSP native de la caméra (`camera.ai_rtsp_url` prioritaire → `camera.rtsp_url` → fallback go2rtc uniquement pour démos). Env `MGVMS_AI_DIRECT_RTSP=1` (défaut) active le mode direct. **go2rtc = streaming/WebRTC uniquement**.
- ✅ **Nouveau champ** `Camera.ai_rtsp_url` : URL dédiée IA (flux principal HD) permettant d'utiliser un flux différent que celui exposé aux clients WebRTC.
- ✅ **Module `anpr_tracker.py`** : accumulateur par `track_id` ByteTrack avec machine à états `ENTERED → PRESENT → LEFT` :
  - `record_reading(camera_id, track_id, PlateReading)` — accumule OCR par track
  - `tick_missing(camera_id, seen_tids)` — marque tracks disparus, émet EXIT après `lost_cycles`
  - `best_reading()` — consensus par texte + confiance max
  - Anti-doublons stationnés (1 seul ENTRY) + retente véhicules mobiles (multi-OCR)
- ✅ **Intégration `_analyze_frame`** : chaque plate détectée est routée via anpr_tracker (flag `_emit`) ; downstream ne persiste que les plates avec `_emit=True`.
- ✅ **Nouveaux endpoints diagnostics** :
  - `GET /api/diagnostics/anpr-tracker` — config + véhicules trackés par caméra
  - `GET /api/diagnostics/streaming-metrics` — go2rtc streams (producers/consumers/WebRTC clients) — **séparé** du pipeline IA
- ✅ **Frontend `/pipeline-monitor` enrichi** : panneau Streaming go2rtc + panneau ANPR Tracker.
### Vérifié
- Tests : 9 unitaires (`test_v03_ai_streaming_decoupling.py`) + 10 HTTP (testing_agent) = **19/19 OK**.

## [v0.3 · Pipeline temps réel] — 2026-02 — P0 non-bloquant (Session 8)
### Corrigé
- 🔴 **Bug fatal** : `SyntaxError` dans `ai_engine.py` (bloc `if _pipeline_ok and _pr:` mal indenté) qui empêchait le backend de démarrer.
- ✅ **Ordre des routers corrigé** dans `server.py` : `plugin_config_router` désormais AVANT `plugins_bus_router` (sinon `/api/plugins/tracking/config` intercepté par `/plugins/{name}/config`).
### Ajouté
- ✅ **Refactor `_process_camera`** en Phase A (SYNC ≤200ms) / Phase B (fire-and-forget) :
  - Phase A : fetch_frame → YOLO + ByteTrack + broadcast overlay → return
  - Phase B : `asyncio.create_task(_process_downstream)` — Multi-ANPR, Smart Zones, Workflows, Plugin bus, Event persistence
  - **Backpressure guard** : `_MAX_DOWNSTREAM_INFLIGHT=2` par caméra, drops enregistrés
- ✅ **`pipeline_metrics.py` enrichi** : `record_stage()` par étape (fetch/yolo/tracking/alpr/realtime/downstream), `record_drop()`, snapshot avec avg/max/p95 par stage, fps_5s, drops_5s.
- ✅ **ByteTrack activé par défaut** : `enabled=True, track_thresh=0.25, match_thresh=0.85, track_buffer=60, id_persist_seconds=120` — objectif : minimiser la perte d'IDs.
- ✅ **Frontend `/pipeline-monitor`** (`AIPipelineMonitor.jsx`) : dashboard temps réel avec bandeau agrégé, cartes caméras expandables (StageBar avec cible), ByteTrack Tuner, objectifs P0, diagramme d'architecture.
- ✅ Route + menu ajoutés (`nav.pipeline_monitor` = "Pipeline IA · Live", section Admin).
### Vérifié
- Tests : 11 unitaires `test_pipeline_realtime.py` + 9 HTTP intégration = **20/20 OK**.
- Métriques observées démo : `downstream_ms=5.6ms` (fire-and-forget confirmé), `tracking_ms=51ms` (ByteTrack actif), drops=0.

## [v0.2.7 · P1 Stabilisation] — 2026-02 — Assets logo + PTZ ONVIF réel + Recorder Health (Session 7)
### Ajouté
- 🎨 **Logo dark/light** : assets réels intégrés (`mg-vms-logo-light.png` / `-dark.png`).
- 📡 **PTZ ONVIF réel** : l'endpoint no-op remplacé par `ContinuousMove` + `Stop` via `onvif_zeep`.
  - 8 commandes : `pan_left/right`, `tilt_up/down`, `zoom_in/out`, `home`, `stop`
  - Nouveaux endpoints : `GET /api/cameras/{id}/ptz/presets`, `POST /api/cameras/{id}/ptz/preset/{token}`
  - UI 8-directions dans LiveView (croix + colonne zoom)
- 💾 **Recorder Health** : `GET /api/diagnostics/recorder-health` — ffmpeg alive, PID OS, dernier segment, gap détecté, continuité 24h (couverture % + trous listés).
- 📊 **Health Dashboard UI** mis à jour pour la nouvelle forme recorder.
### Vérifié
- Suite pytest : 12/12 (health + pipeline + PTZ/recorder) — voir `tests/test_ptz_and_recorder_health.py`.

## [v0.2 · Plugin Manager NG] — 2026-02 — 50 plugins isolés + Fusion + Hot reload (Sessions 2 à 6)
### Ajouté — Architecture Plugin Manager NG
- **Bus multi-plugin** avec 4 politiques fusion ANPR (`cascade` / `highest` / `vote` / `compare`).
- **Loader dynamique** manifest YAML + import isolé via `importlib`.
- **Config store persistant** + hot reload + endpoints `/api/plugins/{name}/config`.
- **50 plugins isolés** dans `/app/data/plugins/` répartis en 12 catégories (ANPR, Détection, Tracking, Segmentation, Feu/Fumée, Sûreté, EPI, Comptage, Retail, Parking, Agriculture, Notifs).
- **5 interfaces plugin** : `FrameAnalyzer`, `PlateRecognizer`, `Tracker`, `Segmenter`, `PipelineConsumer`, `EventConsumer`.
- **Pipeline chaîné** `bus.dispatch_pipeline()` wired dans `ai_engine.ai_loop` — chaque frame décodée traverse Detector → Tracker → Business → Notifications.
- **Frontend** : `PluginManagerNG.jsx` + `PluginConfigDialog.jsx` + `PipelineTestPanel.jsx` (canvas viz).
- **Bouton "Installer les deps"** (`--no-deps` par défaut pour protection env).
### Vérifié
- 24 tests pytest OK.

## [v0.1 · Plugin Manager fondations] — 2026-01 — Fernet + Diagnostics + Doc (Session 1)
### Ajouté
- Fix régression IA (go2rtc gateway strict, diagnostics AI/sync).
- Documentation 28 chapitres.
- Plugin Manager fondations : interfaces, contexte, registry.
- Fernet passwords caméras (chiffrement au repos).
- URL versioning `/api/v1/` introduit.

---

## [2.0.0] — 2026-06 — Permissions granulaires par utilisateur (gérées par admin)
### Ajouté
- **Permissions granulaires** par utilisateur (en plus des rôles), **gérées uniquement par l'admin** : `view_live`, `view_recordings`, `read_plates`, `stream_hd`, `ptz_control`, `export_files`. Admin = bypass (toutes accordées). Défauts par rôle + overrides par utilisateur (`effective_permissions`).
- Backend : `require_permission(perm)` (auth.py) appliqué sur snapshot/stream (view_live), qualité **HD/SD** (`GET /api/cameras/{id}/stream`, stream_hd), recordings timeline+playback (view_recordings), `/plates`+`/anpr/detect` (read_plates), PTZ (ptz_control), recordings/plates export (export_files). `permissions` exposé dans `/auth/me` et `/users`.
- Gestion utilisateur réservée admin (déjà le cas) : création/édition incluent un éditeur de **permissions** (UserCreate/UserUpdate + `_clean_permissions`).
- Frontend : `hasPerm()` (AppContext), **dialog de permissions** par utilisateur dans `/users` (6 bascules), masquage de la navigation (Live/Enregistrements/ANPR/Véhicules) selon les permissions. **Live View** : contrôles PTZ masqués sans `ptz_control`, badge **HD/SD** selon `stream_hd` ; **panneau d'export** masqué sans `export_files`.
### Tests
- Backend 22/22 (test_permissions.py), frontend 100% (gating nav, éditeur de perms, persistance, bypass admin). Itération 11.

## [1.9.1] — 2026-06 — Déploiement Docker testable (app réelle) + compose prod cohérent
### Ajouté — `deploy-app/` (test Docker fonctionnel)
- `docker-compose.yml` : MongoDB + **backend FastAPI** (`backend/Dockerfile`, python:3.11-slim, extra-index pour emergentintegrations) + **frontend React/Nginx** (`frontend/Dockerfile` multi-stage node:20 → nginx, `nginx.conf` SPA) → `docker compose up -d --build` lance MG-VMS complet (http://localhost:3000, API :8001).
- `.env.example` (DB_NAME, CORS_ORIGINS, JWT_SECRET, ADMIN_*, REACT_APP_BACKEND_URL, EMERGENT_LLM_KEY) + `README.md` (démarrage, commandes, notes domaine/CORS). `.dockerignore` backend & frontend.
### Vérifié
- Compose YAML valide, contextes de build résolus, tous les Dockerfiles/nginx.conf présents, gestion env OK. ⚠️ **Non exécuté dans le sandbox** (pas de Docker) — à lancer sur la machine de l'utilisateur.
- Compose production `/deploy` (18 services) revalidé : YAML OK, tous les contextes de build ont un Dockerfile. Pointeur ajouté vers `deploy-app/` pour le test rapide.

## [1.9.0] — 2026-06 — Ressources matérielles CPU/GPU (Phase 1)
### Ajouté
- **Module Ressources matérielles** (`/hardware`, technician+ en lecture, admin en écriture) — 4 onglets :
  - **Matériel** : détection réelle CPU (cœurs/threads, psutil) + RAM ; inventaire **GPU** (RTX 4070, RTX A2000, Intel UHD/QuickSync, Google Coral) **simulé** en sandbox (détection réelle nvidia-smi en prod) + matrice d'accélérations (CUDA/NVENC/NVDEC/TensorRT/QuickSync/OpenVINO/OpenCL/DirectML/Vulkan/EdgeTPU).
  - **Ressources** : allocation du composant (CPU/GPU/NVDEC/NVENC/QuickSync/AMF/Auto/Coral…) pour 10 fonctions (décodage, encodage, Live, relecture, IA, ANPR, miniatures, export, PDF, reconversion).
  - **Profils & priorités** : profils Économie/Équilibré/Performance/Ultra/Personnalisé (pré-configurent les allocations) + priorités par moteur (Temps réel/Normale/Basse) + bascule Optimisation automatique.
  - **Monitoring** temps réel (poll 2s) : CPU/RAM/charge IA/FFmpeg, flux/FPS/consommation/températures, et par GPU util/VRAM/temp/conso/ventilateur (code couleur).
- Endpoints : `GET /api/hardware/info|config|monitor`, `PUT /api/hardware/config` (admin), `POST /api/hardware/profile/{p}` (admin). Toute modif manuelle bascule en profil « custom ». Détection au démarrage (`seed_hardware`).
### Tests
- Backend 17/17 (test_hardware.py), frontend 100% (4 onglets, RBAC admin/tech/viewer, monitoring live). Itération 10.
### À venir
- Phase 2 : moteur d'auto-optimisation (règles de bascule GPU↔CPU), historique + graphiques + alertes (temp/VRAM/GPU indispo).
- Phase 3 : Pools GPU (mode entreprise), GPU par caméra, benchmarks (décodage/encodage/IA/lecture/export), matrice de compatibilité étendue. Artefacts prod `/deploy` (pynvml/NVENC/OpenVINO/Coral).

## [1.8.0] — 2026-06 — Rapports + Alerte ANPR enrichie + Poll réseau périodique
### Ajouté
- **Module Rapports** (`/reports`, role technician+) : génération CSV / Excel (openpyxl) / PDF (reportlab) pour 4 jeux — plaques ANPR, événements IA, alertes, équipements réseau. Filtres plage de dates + site (cloisonnés). Endpoints `GET /api/reports/types` et `GET /api/reports/{type}?format=&site_id=&date_from=&date_to=`.
- **Alerte « liste noire » enrichie** : les notifications Discord (embed avec **photo véhicule** + champ lien) et Telegram (sendPhoto + caption avec **lien caméra**) incluent désormais l'image et un lien profond `/recordings?camera=<id>`. `send_notification(subject, body, image_url, link_url)`. La page Recordings présélectionne la caméra depuis `?camera=`.
- **Poll réseau périodique côté serveur** : `network_poll_broadcaster` (intervalle `NETWORK_POLL_INTERVAL`, défaut 30s) sonde l'inventaire (simulé), met à jour statut+latence et **lève des alertes de transition** diffusées en temps réel (WebSocket). La page `/network` se rafraîchit automatiquement toutes les 30s.
### Tests
- Backend 25/25 (test_reports_sprint.py : 3 formats × 4 types, filtres, 403 viewer, alerte blacklist enrichie sans erreur), frontend 100% (nav role-gating, téléchargements, deep-link caméra). Itération 9.

## [1.7.0] — 2026-06 — Export de séquence vidéo (timeline → ZIP/MP4)
### Ajouté — Sandbox
- **Export de séquence** depuis la timeline (`/recordings`) : sélection de plage par **glisser sur la timeline** (surbrillance) + champs début/fin + choix de format. **ZIP réel téléchargeable** (manifeste JSON + README + vignettes des segments de la plage). **MP4 mis en file**, marqué « généré en production (FFmpeg) ». Liste des **exports récents** avec statut (Prêt/En file) et téléchargement.
- Endpoints : `POST /api/recordings/export`, `GET /api/recordings/exports`, `GET /api/recordings/exports/{id}/download` (ZIP streamé via zipfile, cloisonné par utilisateur/site).
### Ajouté — Artefacts production `/deploy`
- `recording/recorder.py` : endpoint `POST /export` (concat FFmpeg `-f concat -c copy` → MP4, ou ZIP des segments bruts) → upload MinIO/S3 + URL présignée.
### Tests
- Backend testé curl (ZIP 194Ko vérifié : manifest+thumbnails ; MP4 queued ; list), frontend vérifié (drag-select + export + exports récents).

## [1.6.0] — 2026-06 — Supervision réseau (SNMP/ICMP) + topologie
### Ajouté — Sandbox (MongoDB)
- **Module Supervision réseau** (`/network`, visible dès le rôle client) : inventaire d'équipements (Switch/Routeur/NAS/UPS/Serveur/NVR/Caméra/Générique), **carte de topologie** hiérarchique (SVG, liens parent/enfant up/down colorés par statut), vue tableau, **fiche équipement** (statut, latence, uptime, fabricant, modèle, IP, site ; UPS : batterie/sur batterie/autonomie).
- **ICMP/SNMP simulé** : `POST /api/network/equipment/{id}/ping` et `POST /api/network/poll` (sweep) mettent à jour statut + latence ; **alerte critique automatique** sur passage hors-ligne ou UPS sur batterie (réutilise broadcast WebSocket + notifications).
- Endpoints `network.py` : `GET /api/network/equipment|stats|topology|equipment/{id}`, `POST/PUT/DELETE /api/network/equipment`, `POST /api/network/{id}/ping`, `POST /api/network/poll`. Cloisonnement par site appliqué. Seed idempotent (routeur+UPS+switch+NAS+NVR+serveur par site).
### Ajouté — Artefacts production `/deploy`
- `network-monitor/` : `poller.py` (ICMP réel + SNMP UPS-MIB/IF-MIB via pysnmp, alertes), `Dockerfile` (iputils-ping + NET_RAW), `requirements.txt` ; service ajouté au `docker-compose.yml` ; table `equipment` (avec topologie `parent_id`) ajoutée au `schema.sql`.
### Tests
- Backend 12/12 (pytest test_network.py), frontend 100% (topologie, CRUD, ping/poll, fiche UPS, cloisonnement viewer). Itération 8.

## [1.5.0] — 2026-06 — Cœur Vidéo P0 (artefacts /deploy) + Timeline d'enregistrements (sandbox)
### Ajouté — Artefacts production `/deploy` (NON exécutables ici)
- **Moteur IA** `/deploy/ai-engine/` : `worker.py` (YOLOv11 Ultralytics + tracking ByteTrack, dédup par piste, écriture `events`, Redis Pub/Sub) ; `anpr.py` (LAPI réelle via fast-alpr → `plates` + alerte critique liste noire) ; `requirements.txt`.
- **Service d'enregistrement** `/deploy/recording/recorder.py` : segmentation MP4 FFmpeg, upload MinIO/S3, indexation `recordings`, API timeline + URL présignée de lecture, rétention/quota.
- **Cœur vidéo ffmpeg** complété : `stream_manager.py` (RTSP→HLS + reconnexion + snapshot + WebRTC go2rtc), `onvif_discovery.py` (WS-Discovery + profils média), `go2rtc.yaml`.
- Correction du conflit de dépendance `ffmpeg/requirements.txt` (httpx 0.26→0.28.1).
### Ajouté — Incrément testable (sandbox, MongoDB)
- **Page Enregistrements & Timeline** (`/recordings`) : sélection caméra + date, timeline 24h colorée par mode (continu/mouvement/IA), marqueurs d'événements, lecteur (lecture simulée), liste de segments, stats (couverture/volume/segments/événements).
- Endpoints `GET /api/recordings/timeline` et `GET /api/recordings/{id}/playback` (cloisonnés par site) ; seed idempotent de segments sur 3 jours.
### Tests
- Backend testé (curl e2e : timeline + playback OK), frontend vérifié (screenshot, lecture d'un segment).

## [1.4.0] — 2026-06 — Sprint 3 : Plugins + ANPR liste noire auto + Artefacts /deploy
### Ajouté
- **Socle d'architecture de plugins** : registre de 10 modules (ANPR cœur, IA YOLO, tracking, reconnaissance faciale, parking, thermique, radar, drone, MQTT, contrôle d'accès), activation/désactivation dynamique persistée (`GET/PUT /api/plugins`), page UI Plugins (admin), protection des plugins cœur.
- **Alerte automatique « plaque liste noire »** : `POST /api/anpr/detect` + `analyze-plate` déclenchent une alerte critique + broadcast WebSocket + dispatch notifications quand la plaque est en liste noire. Simulateur de détection sur la page ANPR.
- **Artefacts de production `/deploy`** (NON exécutables ici) : `docker-compose.yml` micro-services, `Dockerfile`s (api, frontend, ai-engine GPU, ffmpeg, recording, notification, backup), schéma **PostgreSQL** optimisé (index GIN trigram, partitions), **SQLAlchemy** + **Alembic**, configs **Prometheus/Grafana/Loki/Alertmanager**, manifests **Kubernetes** (Deployments, StatefulSet PG, Ingress WebSocket, HPA), README d'architecture.
### Modifié
- Rate-limit `/auth/login` assoupli (30/min) pour les IP partagées ; la protection anti brute-force reste le verrouillage après 5 échecs/compte.
### Tests
- 14/14 Sprint 3 backend + frontend 100% (itération 7).

## [1.3.0] — 2026-06 — Sprint 2 : Temps réel (P1)
### Ajouté
- **WebSocket** `/api/ws` (authentifié par token, cloisonné par site) : push live des **métriques système** (toutes les 5s) et des **alertes** (à la création). Reconnexion auto côté front.
- **Métriques système réelles** via **psutil** dans `/api/dashboard/stats` (CPU/RAM/stockage/température/bande passante/uptime) — remplacent les valeurs aléatoires.
- **Pagination serveur** non-cassante sur `/plates`, `/events`, `/alerts`, `/audit` : params `limit`/`offset` + header `X-Total-Count` (le corps reste un tableau JSON). UI « Charger plus » sur ANPR et Audit.
- **Front** : indicateur « LIVE » (topbar), toasts d'alerte temps réel, badge d'alertes live, rechargement auto du dashboard/alertes sur nouvelle alerte.
- `POST /api/alerts` : `broadcast_alert` ; `site_id` désormais honoré (alerte rattachable à un site sans caméra) ; `test_camera` diffuse le changement de statut.
### Tests
- 12/12 Sprint 2 + 30/30 régression = **42/42 backend**, frontend 100% (itération 6).

## [1.2.0] — 2026-06 — Sprint 1 : Sécurité (P1)
### Ajouté
- **Anti brute-force** : verrouillage du compte 15 min après 5 échecs (clé IP:email, collection `login_attempts`), HTTP 423.
- **Rate-limiting** des endpoints sensibles (`/auth/login` 10/min, `/auth/forgot-password` 5/5min, `/auth/reset-password` 10/5min), HTTP 429 + `Retry-After`.
- **Reset password** : `POST /auth/forgot-password` (réponse générique anti-énumération) + `POST /auth/reset-password` (jeton `secrets`, TTL 1h, usage unique), envoi best-effort par SMTP si configuré.
- **En-têtes de sécurité OWASP** sur toutes les réponses (X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy, X-XSS-Protection) via `SecurityMiddleware`.
- **Cloisonnement par site** : helpers `allowed_sites()` / `site_scope()` appliqués à sites, caméras, événements, plaques, alertes et dashboard. `site_ids` assignables par l'admin (UI Users + `PUT /users/{id}`).
- **Refresh token câblé** côté frontend : intercepteur axios qui rafraîchit l'access token sur 401 et rejoue la requête ; stockage `mg_refresh`.
- **Frontend** : flux « Mot de passe oublié », page `/reset-password`, dialog d'affectation des sites par utilisateur.
### Modifié
- **CORS** restreint à l'origine explicite du frontend (au lieu de `*`).
- Cookie `access_token` passé en `secure=True`.
- Seed : `client` rattaché au 1er site, `viewer` au 2e (démo du cloisonnement).
### Sécurité
- Tests : 17/17 backend + parcours frontend validés (itération 5).

## [1.1.0] — 2026-06 — Notifications & Intégrations
### Ajouté
- Canaux SMTP / Discord / Telegram configurables dans l'UI (admin), secrets chiffrés (Fernet) et masqués en lecture, test d'envoi par canal, activation/désactivation.
- Envoi automatique sur alerte critique (`POST /alerts` + BackgroundTasks).
- Tests : 20/20 backend + 14/14 frontend.

## [1.0.0] — 2026-06 — MVP initial
### Ajouté
- Auth JWT + RBAC (admin/technicien/client/lecture seule/invité) + 2FA TOTP.
- Multi-sites, gestion caméras (RTSP/ONVIF config, test, snapshot, PTZ — simulés).
- Mur vidéo (1→64), dashboard (KPI + graphiques), ANPR (recherche, watchlist, export CSV, analyse IA d'image), recherche véhicule, alertes, carte OSM, audit, gestion utilisateurs, paramètres.
- Bilingue FR/EN, thèmes clair/sombre.
- Tests : 30/30 backend + parcours frontend.
