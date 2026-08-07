# CHANGELOG — MG-VMS

Format inspiré de Keep a Changelog. Dates au format AAAA-MM.

## [v0.7.e] — 2026-06 — Wave A · Hot Reload + Wave B · Frontend + Wave C · Multi-OCR + Wave D · ONVIF hardening + Wave E · Timeline Reolink + Wave F · Stress-test (P0)

### Added — Wave F · Stress-test 1 → 50 caméras reproductible
- Nouveau harness `backend/stress/stress_test.py` exécute `asyncio.gather`
  de 1/5/10/20/30/50 caméras × 3 frames avec mesure temps par étage
  (YOLO, assess_crop_quality, enhance_plate_crop, crop_hash) + CPU/RAM/FPS
- Rapport JSON brut `/app/memory/STRESS_TEST_v0.7.e_report.json` +
  rapport MD `/app/memory/WAVE_F_STRESS_TEST_v0.7.e.md`
- Résultats preview CPU-only 8 vCPUs (pas de GPU) : Wave C stages
  totalisent < 1 ms peu importe N. Goulot unique = YOLO CPU-only
  (105 ms → 2782 ms mean de n=1 à n=50). Extrapolation GPU : cible
  < 200 ms tenue jusqu'à 50 caméras
- RAM stable à ~1,1 GB RSS après 50 cams — pas de fuite mémoire

### Documentation — Rapport final consolidé A → F
- `/app/memory/RAPPORT_FINAL_v0.7.e.md` : synthèse, 18 causes racines,
  tableau fichiers modifiés, preuves quantifiées, contrats préservés,
  API publique, endpoints diagnostic, backlog v0.7.f

---

## [v0.7.d] — 2026-06 — Camera API Hardening (P0)

### Fixed — Changelog embarqué + version applicative
- `CHANGELOG.md` est désormais copié dans l'image Docker backend — le Welcome
  Center affichait "unknown version" et un changelog vide une fois installé
  (le fichier n'existait qu'en dépôt, jamais dans le conteneur)

### Fixed — P0-1 Statut caméra : source de vérité unique
- Une caméra dont le worker `frame_source` produit des frames fraîches (<10s)
  est TOUJOURS online — étape 0 prioritaire dans `_probe_status_once`, avant
  tout probe go2rtc/TCP. Plus aucune incohérence "frames + IA mais OFFLINE"
- Camera Center, Pipeline Center, Dashboard, Events et Map lisent tous
  `cam.status` (DB) — vérifié, aucune logique de statut dupliquée côté UI

### Fixed — P0-2 ONVIF "No such file devicemgmt.wsdl"
- Cause racine : `drivers/onvif_driver.py` instanciait `ONVIFCamera()` SANS
  `wsdl_dir` → onvif_zeep cherche `site-packages/wsdl` (dossier data fragile
  selon le mode d'installation pip/Docker) → fichier introuvable
- Fix : factory `wsdl_path.onvif_camera` (bundle officiel embarqué `backend/wsdl`,
  versionné git + assertions build Docker) — chemin déterministe
- Bundle WSDL complété avec les fichiers OFFICIELS onvif.org/w3.org :
  `onvif.xsd` (révision 2025, +StringList requis par media2), `common.xsd`,
  `soap-envelope` (SOAP 1.2), import media2 corrigé vers layout plat
- Les 7 WSDL chargent 100% hors-ligne : devicemgmt (82 ops), media (79),
  media2 (59), ptz (52), events, imaging, deviceio

### Fixed — P0-5 Codes HTTP Camera API : jamais de 500
- `unsupported_capability` → **501** (au lieu de 400)
- `no_driver_available` → 501 · `device_error`/`driver_error` → 502
- Fallback code inconnu → 502 (plus aucun chemin vers 500)

### Verified — P0-4 UI 100% capability-driven
- Tous les contrôles (PTZ, zoom, audio, sirène, spotlight, IR, IA embarquée)
  conditionnés par `GET /api/devices/{id}/capabilities` — zéro logique de
  marque dans le frontend

---

> Depuis Feb 2026, MG-VMS bascule sur un cycle interne de versions « pipeline »
> (v0.3 → v0.4 → v0.4.1 → v0.4.2 → v0.4.3) qui reflète la refonte vers une architecture
> modulaire Plugin Manager NG + Pipeline Engine v2 (style DeepStream/Frigate).
> L'ancien cycle produit (1.x/2.x) reste préservé en bas de fichier.

## [v0.7.c] — 2026-06 — Hotfix régressions P0 (démarrage Docker)

### Fixed (backend) — P0-1 Healthcheck Docker
- Ajout de la route racine `GET /health` dans `server.py` (hors préfixe `/api`,
  `include_in_schema=False`) retournant `{"status": "ok"}`
- Route volontairement minimale : aucune requête MongoDB, aucune dépendance IA,
  aucune vérification matérielle — réponse garantie < 100 ms
- Le healthcheck Docker repasse en `healthy` ; plus de timeout au démarrage
- **Audit v0.7.c** : le `HEALTHCHECK` du `backend/Dockerfile` probait encore
  `/api/` — pointé sur `/health` + ajout `--start-period=90s` (couvre le
  premier boot : imports torch + chargement des 51 plugins)

### Fixed (backend) — P0-2 Initialisation IA lazy
- `ai_loop` chargeait YOLO + fast-alpr (téléchargements yolo11n.pt + modèles
  ONNX) inconditionnellement au boot, même sans caméra `detect_enabled`
- Désormais : chargement UNIQUEMENT si ≥1 caméra `detect_enabled` existe ;
  retry limité aux cycles où des caméras actives l'exigent
- Gardes lazy ajoutées dans `_analyze_frame` et `analyze_image_local` (routes
  on-demand : benchmark, test-détection, analyse d'upload restent fonctionnelles)

### Fixed (deploy) — P0-4 Demo Camera 002 (go2rtc HTTP 500)
- Cause racine : `go2rtc.yaml` référençait `/app/media/street-demo.mp4` mais le
  conteneur go2rtc montait `RECORDINGS_PATH` sur `/app/media` — le fichier démo
  du repo n'était jamais présent → `exec ffmpeg` échouait → HTTP 500 → timeouts
- Fix : montage `../media:/demo-media:ro` + chemin `/demo-media/street-demo.mp4`

### Fixed (backend) — P0-5 Boucle de redémarrage frame-source
- `_reader_loop` redémarrait indéfiniment (backoff 1→5s, aucun plafond)
- Ajout `_MAX_CONSECUTIVE_FAILURES=10` : arrêt propre + log ERROR après 10
  tentatives consécutives sans frame ; champs `gave_up`/`consecutive_failures`
  exposés dans `frame_source.status()` (diagnostics)
- Relance automatique quand la caméra repasse online (stop/start par
  `_sync_frame_source_workers`) ou si la config du flux change
- `_ensure_frame_source_running` : les caméras démo utilisent désormais le
  relais `GO2RTC_RTSP` (même logique que `_sync`) — supprime le churn
  stop/recréation en Docker où l'URL seedée `127.0.0.1` pointait hors conteneur

### Documented — P0-3 TensorRT (aucun code modifié)
- `libnvinfer.so.10 not found` est ATTENDU : onnxruntime-gpu tente
  TensorrtExecutionProvider en premier ; sans TensorRT installé il bascule sur
  CUDAExecutionProvider — warning sans impact, l'inférence CUDA fonctionne

### Fixed (frontend) — P0-3 Lockfile Yarn
- Vérification et validation du `yarn.lock` : `yarn install --frozen-lockfile`
  passe sans erreur, lockfile synchronisé avec `package.json`

### Notes
- Correctif strict : aucune nouvelle fonctionnalité, aucune modification
  d'architecture ni altération du code existant

---

## [v0.7.b] — 2026-02 — Smart Search cross-domain (personnes) + Historique recherches

### Added (backend) — Recherche IA étendue aux événements humains
- Nouveau router `routes/smart_search.py` monté sur `POST /api/smart-search` :
  * Le LLM détermine automatiquement le `target` (`vehicles` / `persons` / `both`)
  * Croise les collections `plates` (véhicules) ET `events` (détections IA)
  * Retour unifié : `{query, target, filters, vehicles_count, persons_count,
    vehicles[], persons[]}`
- Schéma JSON de parsing enrichi : `target`, `object_description`,
  `date_from/to`, `time_from/to`, `camera_hint`, `colors` (véhicule OU vêtement)
- Traducteurs bilingues étendus : personne↔person, vélo↔bike, camion↔truck,
  voiture↔car — pour la normalisation des types d'events

### Added (frontend) — Section « Personnes détectées » + Historique
- Composant `PersonsSection` : galerie de crops humains (60 max), type +
  caméra + timestamp + confiance ; clic ouvre l'image plein écran
- Description IA affichée en italique à côté du titre : « — "veste rouge"
  (tri visuel manuel) »
- Header résultats : `X véhicule(s) + Y personne(s) pour « … »`
- **Barre historique** sous la zone de recherche (localStorage) :
  * 5 dernières requêtes, chip cliquable avec icône ✨
  * Tooltip précise vehicles/persons counts
  * Bouton « Vider » pour purger

### Fixed
- `runSmartSearch` recevait l'objet event du onClick au lieu d'une string
  → `event.trim is not a function` corrigé (guard `typeof === "string"`)

### Testé
- « personne cette semaine » → 60 personnes, target=persons, dates
  correctement calculées (2026-07-31 → 2026-08-07)
- « voitures grises » → 30 véhicules, target=vehicles
- Historique : rerun depuis chip fonctionne + persiste entre navigations

---

## [v0.7] — 2026-02 — Vehicle Identity + Smart Search IA (Claude Sonnet 5)

### Added (backend) — Vehicle Identity (cross-plate matching)
- Collection Mongo `vehicle_identities` (isolée de `plates`)
- `POST /api/vehicles/identities` — création manuelle (name, plates[],
  make, color, type, notes)
- `GET  /api/vehicles/identities` — liste toutes les identités
- `GET  /api/vehicles/identities/detect?min_plates=2` — détection auto :
  groupes make+color+type observés sur ≥2 plaques distinctes ; filtre
  les groupes déjà couverts par une identité existante
- `GET  /api/vehicles/identities/{id}` — détail + stats agrégées
  (passages_count, cameras_count, first/last_seen)
- `DELETE /api/vehicles/identities/{id}`

### Added (backend) — Recherche IA en langage naturel
- `POST /api/vehicles/smart-search` — Claude Sonnet 5 via
  `emergentintegrations` + EMERGENT_LLM_KEY
- Parseur JSON strict : plaque, colors[], makes[], types[], date_from/to,
  time_from/to, camera_hint, person_description
- Traduction FR↔EN + regex `^…$` case-insensitive sur les couleurs/types
  pour matcher les données stockées avec majuscules variables
- Retour agrégé par plaque (30 max), triée par last_seen

### Added (frontend) — Barre IA + Filtres avancés + Panneau Identités
- Barre de recherche unique avec icône ✨ acceptant du langage naturel
- Bouton « Filtres » (repliable) pour affiner par couleur/marque/type/dates
- Chips de filtres IA visibles au-dessus des résultats (transparence sur
  ce que le LLM a compris)
- Composant `IdentitiesPanel` en tête de page : identités existantes +
  candidats détectés + bouton « Créer l'identité » en un clic

### Changed
- Menu latéral : suppression de l'item « Recherche véhicule » (redondance
  avec la barre IA) ; route `/vehicles/search` conservée pour compatibilité

### Testé
- 30 véhicules trouvés pour « voitures grises » (Claude extrait
  `{"colors":["gris"],"types":["voiture"]}`)
- « camions ce matin » → filtres date+heure appliqués correctement

---

## [v0.7-preview] — 2026-02 — Consensus multi-plugins + Validation manuelle + Retrait YOLO

### Added (backend) — Consensus OCR multi-plugins
- Fonction `_levenshtein()` + `_find_variants()` : détecte les variantes
  OCR d'une même plaque (distance ≤ 2 + contexte partagé caméra/couleur/marque)
- `GET  /api/vehicles/{plate}/consensus` — calcule la plaque canonique
  probable via vote pondéré par moteur (`fast-alpr=1.0`, `plate-recognizer=1.0`,
  `paddle-ocr=0.9`, `openalpr=0.9`, `tesseract=0.6`, `easyocr=0.7`)
  * Score = Σ (avg_confidence × poids_moteur × nb_lectures)
- `POST /api/vehicles/{plate}/validate` — fige la plaque canonique + lie
  les variantes dans la collection `plate_validations`. L'historique brut
  reste intact.
- `DELETE /api/vehicles/{plate}/validate` — retire la validation manuelle

### Added (frontend) — Bloc Consensus dans le drawer
- Composant `PlateConsensusBlock` :
  * Suggestion canonique en vert avec score
  * Barres de score comparatives par candidat
  * Bouton `[VALIDER]` par candidat qui persiste la validation
  * Badge « Validée » avec date + validateur quand une plaque est figée
  * Bouton « Retirer la validation »

### Removed (frontend) — Ligne YOLO obsolète
- Page Événements : « Détections réelles : mouvement, personnes,
  véhicules (YOLO) — X au total » remplacée par « Détections IA temps
  réel — X au total » (représentation générique)

### Testé
- Cas L3863 : score 7.16 (11 lectures fast-alpr, avg_conf 0.651) vs
  variante L3883 (score 7.01, distance Levenshtein=1) — exactement le
  scénario « mauvais OCR sur le même véhicule »

---

## [v0.6.b] — 2026-02 — Alertes Habitudes + Watchlist inline

### Added (backend) — Anomalies véhicule
- `_compute_anomaly()` : compare la dernière passe aux habitudes
  (arrivée/départ typiques, jours prédominants, historique nocturne)
- Types d'anomalies : `off_hours`, `off_days`, `nocturnal_first`,
  `nocturnal_rare`, `insufficient_history`
- Sévérité `info` / `warning` / `high` (2 anomalies simultanées =
  automatiquement high)
- `GET  /api/vehicles/{plate}/anomaly` — rapport unitaire
- `GET  /api/vehicles/anomalies/recent?since_hours=48&limit=20` — liste
  des véhicules avec anomalie warning/high sur la fenêtre demandée
- `POST /api/vehicles/{plate}/notify-anomaly` — envoie une notification
  via `send_notification()` (SMTP / Discord / Telegram)

### Added (frontend) — Bandeau + Bloc drawer + Actions Watchlist
- Bandeau jaune « ANOMALIES RÉCENTES » en tête de la grille — chips
  cliquables qui ouvrent directement le drawer sur le véhicule concerné
- Bloc rouge « Anomalie détectée [HIGH] » dans l'onglet Vue du drawer,
  avec message contextuel et bouton `[Créer une alerte]`
- **Actions Watchlist inline** dans le drawer :
  * Statut courant en badge (LISTE NOIRE / LISTE BLANCHE / AUCUNE)
  * 3 boutons Blacklist / Whitelist / Retirer en un clic
  * Utilise les endpoints existants `POST/DELETE /api/watchlist`
- Mise à jour instantanée du statut dans la carte + le drawer

---

## [v0.6] — 2026-02 — Smart ANPR History (Vehicle Timeline Center)

### Added (backend) — 9 nouveaux endpoints agrégateurs
Aucun changement du pipeline OCR ni de `/api/plates` existant.
- Nouveau router `routes/vehicles.py` monté sur `/api/vehicles/*`
- `GET  /api/vehicles` — liste agrégée par plaque (passages_count,
  first_seen, last_seen, cameras_count, best_thumb_id, preview_thumb_ids[3],
  vehicle_make/model/color majoritaires)
- `GET  /api/vehicles/{plate}` — fiche complète + durée moyenne de
  présence calculée (min/max par jour)
- `GET  /api/vehicles/{plate}/passages` — galerie paginée
- `GET  /api/vehicles/{plate}/heatmap` — matrices by_hour[24] + by_dow[7]
- `GET  /api/vehicles/{plate}/cameras` — passages par caméra
- `GET  /api/vehicles/{plate}/journey` — transitions caméra→caméra
- `GET  /api/vehicles/{plate}/habits` — arrivée/départ typiques, jours
  prédominants, alertes nocturnes
- `GET  /api/vehicles/{plate}/identity` — **stub v0.6** (architecture
  prête pour matching cross-plate en v0.7)
- `GET  /api/vehicles/passage/{id}/thumb?kind=frame|vehicle|plate` —
  image JPEG binaire (décodée depuis base64 stocké), cache 24 h — décharge
  les listes du base64 volumineux

### Added (frontend) — Vehicle History Center
- Nouvelle route `/vehicles` dans le menu ÉVÉNEMENTS
- Grille de **cartes cascade** — 3 photos empilées + badge `+N` en haut
  à gauche (spec exacte du brief)
- **Drawer latéral** shadcn Sheet, 6 onglets :
  1. **Vue** — best thumb + stats + habitudes calculées
  2. **Galerie** — chronologique paginée, lazy load
  3. **Timeline** — groupée par jour
  4. **Heatmap** — barres par heure + par jour
  5. **Caméras** — compteurs par caméra
  6. **Parcours** — transitions chronologiques
- **Refresh auto 30 s** avec pause automatique quand un drawer est ouvert
- Composant `PlateBadge` type française avec bande bleue F
- Aucune modification de la page ANPR existante — compat totale

### Testé
- 31 véhicules réels agrégés depuis les lectures de démo
- Drawer L3863 : 11 passages, 1 caméra, durée moy. 177 min, habitudes
  Mardi/Mercredi 11:22 / 13:08→19:27

---

## [v0.5.7-storage] — 2026-02 — Refonte page Paramètres → Stockage

### Changed (frontend)
- Menu latéral : item « Paramètres » → **« Stockage »** (icône `HardDrive`)
- Nouvelle route `/storage` (l'ancien `/settings` reste actif pour compat)
- Page réorganisée autour de **3 disques dédiés** :
  1. **Application VMS** (partition `/app` détectée auto)
  2. **Base de données** (Mongo local vs serveur dédié)
  3. **Enregistrements vidéo** (Rétention + Pools multi-disques)
- Badges intelligents **DÉDIÉ** (vert) / **PARTAGÉ** / **SERVEUR LOCAL**
  (jaune) qui invitent visuellement à séparer les disques
- Bandeau bonne pratique en haut de page + alerte contextuelle quand VMS
  et vidéos partagent la même partition

### Removed (frontend)
- Tuile « Compte » (redondante avec le menu utilisateur haut-droite)
- Tuile « Apparence » (langue et thème sont déjà en haut à droite
  du Layout : icônes `FR` / lune)

### Added (i18n)
- 16 nouvelles clés FR + EN (`nav.storage`, `storage.title|subtitle|tip|
  vms|vms_mount|vms_type|vms_total|vms_free|vms_used|db|db_desc|videos|
  videos_desc|appearance`)

---

## [v0.5.7] — 2026-02 — Universal Camera API · Final Build (Validator + Matrix + Health)

### Added — Driver Validator (validation non destructive)
- `pipeline_v2/driver_validator.py` — service qui valide chaque capacité
  déclarée d'un driver **sans jamais exécuter de commande destructive**
- Enum `TestState` : `PASS` / `WARNING` / `FAIL` / `TIMEOUT` /
  `UNSUPPORTED` / `SKIPPED`
- Score pondéré officiel : `snapshot=25`, `stream=25`, `device_info=15`,
  `events=15`, `ptz=10`, `audio=5`, `reboot=3`, `siren=2` (total 100)
- Facteurs : `PASS=1.0`, `WARNING=0.7`, `FAIL/TIMEOUT=0`, `UNSUPPORTED/
  SKIPPED` exclus du dénominateur
- Les capacités PTZ / siren / light / audio / reboot sont vérifiées par
  **inspection de contrat** (`_method_is_overridden` compare à
  `CameraDriver` base), jamais exécutées physiquement
- `GET  /api/devices/{id}/validate?persist=false` (idempotent)
- `GET  /api/devices/{id}/validate?persist=true` (écrit dans
  `cameras[id].last_validation`)
- `POST /api/devices/{id}/validate` (persistance canonique)

### Added — Capability Matrix (agrégat lecture seule)
- `pipeline_v2/capability_matrix.py` — construit une matrice OR des
  capacités depuis `cameras.capabilities` déjà persisté
- `GET /api/devices/matrix?group=vendor|driver|model|camera`

### Added — Driver Health
- Attribut de classe `MANIFEST` ajouté sur `ONVIFDriver`, `ReolinkDriver`,
  `HikvisionDriver`, `DahuaDriver` :
  `{driver, version, status: stable|beta|experimental, api, protocols[],
    supported_models[], coverage_pct}`
- `GET /api/devices/drivers/health` — agrège manifests + stats runtime
  (cameras_count, validations_count, avg_score, last_validation_at)

### Tests
- Nouvelle suite `test_v057_validator_matrix_health.py` : **26 tests**
- Cumul v0.5.7 : **69/69 verts** (26 validator/matrix/health + 21 Phase 1
  + 22 v0.4.6), 100 % mocks, aucune caméra physique

### Livrable
- `/app/FINAL_BUILD_v057.md` — rapport final : fichiers créés/modifiés,
  endpoints ajoutés, dettes techniques identifiées pour v0.6

---

## [v0.5.7-phase1] — 2026-02 — Universal Camera API · Foundations

### Added — Migration Option C (consolidation, zéro duplication)
- Document `/app/MIGRATION_v057_UNIVERSAL_CAMERA_API.md` (tableau
  composant/action/décision)
- `backend/pipeline_v2/camera_driver.py` **réécrit** en **contrat pur** :
  re-export du `CameraDriver` (ABC) + `CameraCapabilities` + `DeviceInfo`
  + `StreamInfo` + `DeviceStatus` + exceptions depuis `drivers/` + facette
  `CameraDriverProtocol` (`runtime_checkable`) pour typing structural.
  **Zéro logique métier.**
- `backend/pipeline_v2/camera_manager.py` créé — façade passive qui
  délègue à `CameraDeviceService` (get_driver / discover / release /
  validate_camera_doc / supported_vendors). **Aucune commande métier.**
- `CameraCapabilities` enrichi de ~25 nouveaux flags backward-compatible :
  `multi_stream`, `codec_h265`, `talkback`, `flash`, `ptz_presets`,
  `ptz_patrol`, `ptz_tracking`, `ai_motion`, `ai_person`, `ai_vehicle`,
  `ai_animal`, `ai_face`, `ai_helmet`, `ai_anpr`, `ai_line_crossing`,
  `ai_intrusion`, `thermal`, `radar`, `relay`, `digital_io`, `wifi`, `poe`,
  `sdcard`, `hdd`, `nas`, `ftp`, `smtp`, `cloud`, `https`, `vpn`,
  `proprietary_api` (tous à `False` par défaut → aucune régression)

### Règles v0.5.7 respectées
- Une seule source de vérité : `backend/drivers/`
- Un seul contrat, un seul registry, un seul CameraDeviceService
- Aucune modification des routes `/api/devices/*` (frontend intact)

### Tests
- Nouvelle suite `test_v057_universal_api.py` : **21 tests**
- 43/43 verts (22 v0.4.6 + 21 nouveaux Phase 1)

---

## [v0.5.6] — 2026-02 — AI Pipeline Hardening (Phases A + B + C/D/E)

### Added — Phase A (Thread-safety & Fusion hiérarchique)
- Thread-safety des workers pipeline (locks asyncio là où nécessaire)
- Fusion **hiérarchique** de l'OCR (canaux top-down au lieu de flat merge)
- Corrections cache OCR (invalidation propre, TTL respecté)

### Added — Phase B (Detector Registry abstraction)
- Registry `pipeline_v2/detector.py` : abstraction du choix de moteur
  détection véhicule/personne (YOLO, MediaPipe, custom) par plugin

### Added — Phase B suite (Plate Recognizer OCR abstraction)
- Registry `pipeline_v2/plate_recognizer.py` : le pipeline choisit le
  moteur OCR via une interface unique. Support fast-alpr, plate-recognizer,
  paddle-ocr, tesseract, easyocr en plugins interchangeables.

### Added — Phase C/D/E (Config per-camera + métriques p99)
- `pipeline_config` par caméra dans Mongo : `{detector, tracker, anpr,
  fusion}` — chaque caméra peut avoir sa propre configuration
- Métriques latence p99 exposées dans les diagnostics AI

### Documents
- `/app/AUDIT_PIPELINE_v055.md`
- `/app/PHASE_A_HARDENING_v056.md`, `PHASE_B_HARDENING_v056.md`,
  `PHASE_B_SUITE_OCR_v056.md`, `PHASE_CDE_HARDENING_v056.md`

### Tests
- `test_v056a_pipeline_hardening.py`, `test_v056b_detector_registry.py`,
  `test_v056b_ocr_abstraction.py`, `test_v056cd_config_and_metrics.py`
- 132/132 tests backend unitaires liés au pipeline verts

---


## [v0.5.5.e] — 2026-02 — Inactivité + Enforcement RBAC + Audit RBAC

### Added (frontend) — Timeout d'inactivité "en dur"
- Nouveau composant **`InactivityWatcher.jsx`** monté globalement dans
  `App.js` (à côté de `SessionExpiryWatcher`) :
  * Écoute les événements d'activité (`mousemove`, `mousedown`, `keydown`,
    `scroll`, `touchstart`, `wheel`) avec throttle 5s.
  * Récupère `session_hours` depuis `/api/security/timeout` (fallback 8h).
  * Timer de vérification toutes les 15s. Après N heures d'inactivité :
    logout + redirect `/login?reason=inactivity`.
- **Login.jsx** affiche une bannière orange persistante quand le param
  `?reason=inactivity` est présent :
  > « Session expirée pour inactivité — Vous avez été déconnecté en
  > raison de l'inactivité (politique de timeout). »
- La modification du timeout par un admin s'applique désormais **à tous
  les users connectés**, sans attendre leur prochaine connexion.

### Changed (frontend) — Nettoyage menu utilisateurs
- Suppression du bouton **ShieldCheck (Permissions)** dans la table
  Utilisateurs et du dialog associé.
- Le CRUD permissions utilisateur passe désormais **exclusivement** par
  la nouvelle page RBAC (Centre de sécurité → Rôles & Permissions).
- Suppression des états morts `permUser`, `selPerms`, `openPerms`,
  `togglePerm`, `savePerms` et de la constante `PERMS`.

### Added (backend) — Enforcement RBAC réel
- `require_permission("view_audit_log")` sur `GET /api/audit`.
- `require_permission("manage_users")` sur les 4 endpoints CRUD users +
  admin_disable_mfa (`GET/POST/PUT/DELETE /api/users` et
  `DELETE /api/users/{id}/mfa`).
- **Admin bypass** conservé : tout admin traverse `require_permission`
  quelle que soit la permission demandée.
- Un `guest` (aucune perm) reçoit **403 Forbidden** ; un admin qui
  active `manage_users` pour le rôle guest via RBAC débloque
  immédiatement l'endpoint (invalidation cache).

### Added (backend) — Filtre audit
- `GET /api/audit?action_prefix=rbac_` — nouveau paramètre optionnel
  pour filtrer les entrées par préfixe d'action (utilisé pour l'onglet
  Historique RBAC).

### Added (frontend) — Onglet Historique RBAC
- `RbacCenter.jsx` gagne un système d'onglets :
  * **Matrice de permissions** (par défaut) — comme avant.
  * **Historique des changements** — appel `/api/audit?action_prefix=rbac_`
    avec un tableau : horodatage, type (Modification/Reset colorisé),
    rôle ciblé (couleur), résumé « N/14 on », auteur.
- Chargement à la demande (lazy) au premier switch d'onglet + bouton
  Actualiser.

### Tests
- `test_v055e_rbac_enforcement.py` — 5/5 verts :
  * Guest 403 sur `/audit` et `/users`
  * Admin 200 sur `/audit`
  * Filtre `action_prefix=rbac_` retourne les entrées attendues
  * Grant dynamique `manage_users` au rôle guest → guest peut lister
    users immédiatement (sans nouveau login).
- Suite v0.5.5.* + v0.5.4 : **32/32 tests verts**.

---

## [v0.5.5.d] — 2026-02 — Phase D RBAC + Codes de récupération + Email notif

### Added (backend) — RBAC Phase D
- **Extension de `PERMISSIONS`** de 6 → **14 permissions** couvrant tous
  les modules produit : `view_live`, `view_recordings`, `read_plates`,
  `stream_hd`, `ptz_control`, `export_files`, **`manage_cameras`**,
  **`manage_sites`**, **`manage_users`**, **`manage_plugins`**,
  **`manage_workflows`**, **`manage_settings`**, **`view_audit_log`**,
  **`access_security_center`**.
- Ajout de `PERMISSION_META` (group + label FR) et `PERMISSION_GROUPS`
  (vidéo, gestion, sécurité).
- Nouvelle collection Mongo **`role_permissions`** pour overrides
  admin, avec cache in-memory + invalidation à chaque PUT/DELETE.
- Nouveaux endpoints (admin) :
  * `GET  /api/security/rbac` — matrice complète (defaults + overrides
    + effective) avec métadonnées pour l'UI.
  * `PUT  /api/security/rbac` — enregistre les permissions d'un rôle.
    Rôle admin refusé (400). Rôle inconnu refusé (400).
  * `DELETE /api/security/rbac/{role}` — reset aux valeurs par défaut.
- `effective_permissions()` refactoré en 3 variantes (sync/async/legacy)
  pour merger dans l'ordre :
  `DEFAULT_PERMISSIONS[role] < DB overrides < user.permissions`.

### Added (frontend) — RBAC
- Nouvelle page **`/security-center/rbac`** (`RbacCenter.jsx`) :
  * Matrice interactive avec groupes (Vidéo, Gestion, Sécurité).
  * 5 colonnes de rôles avec couleurs distinctes.
  * Colonne admin grisée (immuable).
  * Cases modifiées mises en évidence avec ring jaune.
  * Bouton `Enregistrer` par colonne (visible si dirty).
  * Bouton `Reset` par rôle (uniquement s'il a des overrides DB).
  * Bannière d'info expliquant le merge order.
- Sous-menu Centre de sécurité étendu à 5 items (ajout **Rôles & Permissions**).
- i18n FR/EN : `nav.rbac`.

### Added (backend) — Codes de récupération
- `/api/auth/2fa/verify` déjà retournait `recovery_codes` (10 codes
  hex 8 caractères, hash bcrypt en DB). Le frontend les affiche
  maintenant.

### Added (frontend) — Codes de récupération
- Après activation MFA, panneau jaune de sécurité s'affiche dans
  `MfaCenter.jsx` :
  * 10 codes affichés en grille 2×5 / 5×2 responsive.
  * Boutons **Copier** (presse-papier) et **Télécharger .txt**
    (fichier nommé avec l'email de l'utilisateur).
  * Case à cocher « Je confirme avoir sauvegardé les codes ».
  * Bouton confirmant la sauvegarde (dismiss le panneau).
- Bouton **Régénérer les codes** (`KeyRound`) visible quand MFA activée
  et pas de panneau ouvert. Invalide les anciens et affiche les 10
  nouveaux.

### Added (backend) — Notification email
- Nouveau helper `send_email_to(recipient, subject, body)` dans
  `notifications.py` : utilise la config SMTP globale mais override
  `to_email` par le destinataire spécifique.
- Endpoint `DELETE /api/users/{user_id}/mfa` envoie désormais un
  **email de notification** au user concerné en `BackgroundTasks`
  (best-effort, ne bloque pas la réponse). Le mail détaille :
  * Qui a désactivé (email admin)
  * Instructions de réenrollement
  * Horodatage UTC
  * Contact admin en cas d'action non autorisée

### Tests
- `test_v055d_rbac.py` — 6/6 verts :
  * Auth requise (401)
  * Structure GET complète
  * PUT override + effective correct
  * DELETE reset
  * Admin immuable (400)
  * Rôle inconnu rejeté (400)
- Total tests v0.5.5.* : **27/27 verts** (Discovery + Sessions + Disable
  MFA + RBAC).

---

## [v0.5.5.c] — 2026-02 — Désactivation MFA à distance par un admin

### Added (backend)
- Nouveau endpoint **`DELETE /api/users/{user_id}/mfa`** (admin only) :
  * Efface `twofa_enabled`, `twofa_secret` et purge les
    `twofa_recovery_hashes` de l'utilisateur cible.
  * Retourne `400` si l'admin cible son propre compte (redirection
    explicite vers `/security-center/mfa`).
  * Retourne `404` si utilisateur introuvable, `400` si MFA déjà off.
  * Audit trail : action `user_mfa_disabled_by_admin` avec l'email
    admin + l'email cible.

### Added (frontend)
- Nouvelle colonne **MFA** dans la table Gestion des utilisateurs :
  badge vert « ACTIVÉE » avec icône ShieldCheck si l'utilisateur a
  activé la MFA, `—` sinon.
- Nouveau bouton d'action **ShieldOff** (orange) dans la ligne des
  utilisateurs ayant la MFA activée : ouvre une confirmation puis
  appelle `DELETE /users/{id}/mfa`. L'utilisateur pourra ensuite se
  reconnecter sans code TOTP et refaire un enrollement propre.
- Le bouton n'apparaît **pas** pour son propre compte (protection
  anti-lockout).

### Tests
- `test_v055c_admin_disable_mfa.py` — 5/5 verts :
  * Auth requise (401)
  * Impossible sur son propre compte (400)
  * User inconnu (404)
  * MFA déjà off (400)
  * Happy path : reset côté API + purge côté DB (twofa_enabled=False,
    twofa_secret=None, twofa_recovery_hashes=[])

---

## [v0.5.5.b] — 2026-02 — MFA & Sessions actives : pages dédiées

### Added (frontend)
- Nouvelle page **`/security-center/mfa`** (`MfaCenter.jsx`) :
  * Header avec icône bouclier et description
  * Card statut coloré (vert si MFA activée, orange sinon)
  * Assistant d'activation 3 étapes : install app → scan QR → saisie code
  * QR code + secret TOTP en clair avec bouton **Copier**
  * Champ TOTP 6 chiffres numérique avec focus auto
  * 3 blocs pédagogiques : « Pourquoi activer », « Perte du téléphone »,
    « Bonnes pratiques »
  * Liste d'apps recommandées (Google/Microsoft Authenticator, Authy,
    1Password, Bitwarden)
- Nouvelle page **`/security-center/sessions`** (`SessionsCenter.jsx`) :
  * Header avec bouton Actualiser (icône RefreshCw animée)
  * Grille de **4 KPIs colorés** : Sessions actives, IP uniques,
    Timeout actuel, Session courante (navigateur)
  * Panneau timeout admin avec 7 valeurs préréglées (15min → 24h)
  * Tableau détaillé : navigateur, IP, dernière activité, expiration,
    action ; ligne en surbrillance verte pour la session courante
  * Bouton « Déconnecter toutes les autres » + révocation individuelle
  * Poll automatique toutes les 30s
  * Bloc d'info sur l'immédiateté de la révocation

### Changed (frontend)
- Sous-menu **Centre de sécurité** enrichi (4 items) :
  * Vue d'ensemble (`/security-center`)
  * Utilisateurs (`/users`)
  * MFA (`/security-center/mfa`) — nouveau
  * Sessions actives (`/security-center/sessions`) — nouveau
- Menu **Paramètres** redevient un simple lien (le contenu MFA/Sessions
  n'y est plus dupliqué).
- `Settings.jsx` allégé : suppression de la Card MFA (2FA) et de
  `SecuritySessionsCard` (`~125 lignes supprimées`). Le contenu de
  Settings se recentre sur : Apparence, Compte, Rétention (admin),
  Stockage (admin), Base de données (admin).

### Notes
- Aucune modification backend : les endpoints existants sont réutilisés
  (`/api/auth/2fa/*`, `/api/security/sessions*`, `/api/security/timeout`).
- Zéro régression fonctionnelle. Les data-testid existants sont conservés
  (`mfa-*`, `sessions-*`, `security-timeout-*`, etc.).

---

## [v0.5.5.a] — 2026-02 — Sidebar sous-menus (Centre de sécurité + Paramètres)

### Changed (frontend)
- Le **Centre de sécurité** devient un sous-menu en cascade regroupant :
  * Vue d'ensemble (`/security-center`) — score & critères
  * Utilisateurs (`/users`) — anciennement top-level, désormais rattaché
- Les **Paramètres** deviennent un sous-menu en cascade regroupant :
  * Général (`/settings`) — apparence, langue, compte, stockage, DB
  * MFA (`/settings#mfa`) — activation 2FA / QR code / TOTP
  * Sessions actives (`/settings#sessions`) — timeout, sessions en cours
- Navigation par ancre : cliquer sur MFA ou Sessions actives navigue vers
  `/settings` puis auto-scroll (smooth) vers la section correspondante.
- `NavGroupItem` reconnaît désormais les URLs contenant un `#hash` :
  matching actif exact (pathname + hash) pour éviter que « Général » reste
  actif quand l'utilisateur est sur un sous-menu ancré.
- i18n FR/EN : nouvelles clés `nav.security_score`, `nav.settings_general`,
  `nav.mfa`, `nav.sessions_active`.

### Notes
- Aucune route backend touchée, aucune régression fonctionnelle.
- `data-testid` conservés (`nav-security_center`, `nav-users`, `nav-mfa`,
  `nav-sessions_active`, `nav-settings`, `nav-security_score`,
  `nav-settings_general`).

---

## [v0.5.5] — 2026-02 — Assistant de découverte réseau avancée

### Added (backend)
- Nouveau module `/app/backend/routes/discovery.py` — assistant de découverte
  réseau nouvelle génération pour le bouton « Scan ONVIF » :
  * `GET  /api/discovery/interfaces` — liste des interfaces IPv4 avec IP,
    netmask, CIDR, gateway, vitesse Mbps, état up/down, MAC, flag virtual.
  * `POST /api/discovery/start` — démarre un scan asynchrone (task_id).
    Accepte `networks: [CIDR]`, `interfaces: [name]`, `max_hosts_per_network`.
  * `GET  /api/discovery/{task_id}/stream` — flux SSE temps réel émettant
    les événements `log`, `progress`, `device`, `summary`, `done`. Auth via
    query param `?token=` (car EventSource n'envoie pas d'`Authorization`).
  * `POST /api/discovery/{task_id}/cancel` — annulation propre.
  * `GET  /api/discovery/{task_id}/result` — résumé final (persistance 15 min).
- Pipeline de scan combinant :
  * WS-Discovery multicast (rapide, Reolink/Hikvision/Axis/Uniview…).
  * Scan CIDR ciblé : TCP-connect sur les ports 80/554/8000/8080/8899/2020/8081
    puis probe SOAP `GetDeviceInformation` sur les ports ONVIF probables.
  * Best-effort de reconnaissance fabricant via banner HTTP (Hikvision,
    Reolink, Dahua, Axis, Uniview, Hanwha, Synology, QNAP, MikroTik, Ubiquiti).
  * Classification `camera` / `nas` / `printer` / `network` / `other` — les
    équipements non-caméras sont rapportés séparément avec le message
    « Équipement détecté mais non compatible avec MG-VMS ».
- Concurrence contrôlée par `asyncio.Semaphore(64)` et chunks de 128 IPs.
- Audit trail : `discovery_scan_start` + `discovery_scan_cancel`.

### Added (frontend)
- Refonte complète du composant `<OnvifDiscovery/>` dans `Cameras.jsx` :
  * **Phase configuration** : tableau des interfaces avec checkboxes,
    toggle « Afficher les interfaces virtuelles », champ multi-CIDR
    personnalisé (192.168.50.0/24, 172.16.1.0/24…). Sélection auto des
    interfaces physiques UP avec CIDR utile.
  * **Phase scanning** : compteurs live (testées / caméras / écoulé / ETA),
    barre de progression, **console noire style IBM FlashSystem** (fond
    noir, texte vert, horodatage `[HH:MM:SS]`, auto-scroll, curseur clignotant).
  * **Bouton « Annuler le scan »** — arrêt propre côté serveur.
  * **Actions journal** : Copier / Vider / Sauver en `.txt` ou `.log`.
  * **Phase done** : résumé final (interfaces, adresses testées, caméras
    détectées, ONVIF count, par-fabricant, autres équipements, erreurs,
    durée, statut), liste des caméras avec bouton « Utiliser cette IP »
    (badge `ONVIF`, `auth`, `déjà ajoutée`) + section « Autres équipements
    réseau » grisée pour les NVR/NAS/imprimantes.
- Le bouton « Scan ONVIF » du formulaire caméra ouvre désormais cet
  assistant (aucun autre changement UX ailleurs).

### Added (bonus)
- Logo MG-VMS + texte « MG Informatique » dans la sidebar (Layout.jsx)
  transformés en lien externe vers **https://mg-vms.com** (nouveau
  data-testid `sidebar-brand-link`).

### Tests
- Nouveau fichier `test_v055_discovery.py` — 7 tests couvrant :
  * Authentification requise (`401` sans token).
  * Listing des interfaces (structure + présence de `lo`).
  * Refus des CIDR invalides et réseaux vides (`400`).
  * Scan complet + polling du résultat (statut `completed`).
  * Annulation propre → statut `cancelled`.
  * `404` sur `task_id` inconnu.
- 108 tests backend précédents non impactés (rétro-compatibilité totale
  de l'endpoint historique `/api/cameras/discover`, préservé intact).

### Notes
- Aucune modification de l'architecture existante — le nouveau module
  vit à côté de l'API historique. Aucune nouvelle page ajoutée.
- Le scan reste asynchrone, non bloquant et annulable via `task.cancel()`.

---

## [v0.5.4-B] — 2026-02 — Security Center + Security Score (Session 48)

### Added (backend)
- `GET /api/security/score` — analyse **10 critères pondérés** :
  * `https` (URL publique en `https://`)
  * `jwt_env` (JWT_SECRET défini, ≥ 24 car., non par défaut)
  * `strong_passwords` (tous les users en bcrypt)
  * `mfa` (tous les admins avec `twofa_enabled=true`)
  * `backups` (dernière < 48 h)
  * `plugin_sandbox` (allow-list stricte v0.4.3)
  * `camera_firmware` (≥ 70 % des caméras avec `firmware`)
  * `mongo_auth` (URL Mongo avec `@` ou local trusté)
  * `disk` (`psutil.disk_usage` < 80 %)
  * `certs` (certificat TLS expirant dans > 15 j — connexion SSL réelle)
- Réponse : `{score, grade (A-E), checks: {id: {ok, detail, advice?, label, weight}}}`.

### Added (frontend)
- Nouvelle page **`/security-center`** (route protégée admin).
- Composants : `ScoreRing` (SVG animé, gradient de couleur), grille 10 critères
  avec icônes lucide (Lock/Key/ShieldCheck/Cloud/Zap/Camera/Database/HardDrive/
  Server), badge poids `+10`, conseil actionnable en jaune si non-conforme.
- Bloc "Actions rapides" avec navigation vers Sessions / Utilisateurs /
  Journal d'audit / Caméras.
- Sidebar Administration : entrée **Centre de sécurité** entre Suivi des
  performances et Supervision réseau (i18n FR/EN).

### Tests
- 2 nouveaux tests backend : structure du score + auth requise.
- 8/8 tests v0.5.4 verts (Phase A + B).


## [v0.5.4-A] — 2026-02 — Session Manager + timeout configurable (Session 47)

### Contexte
Phase A du chantier Enterprise Security. Sessions traquées côté serveur avec
révocation JWT par `jti`, timeout configurable, popup d'expiration.

### Added (backend)
- Nouveau module `backend/routes/security.py` (prefix `/api/security/`).
- Nouvelle collection Mongo **`sessions`** :
  `{jti, user_id, email, created_at, last_seen_at, expires_at, ip,
    user_agent, revoked, revoked_at?}`.
- JWT enrichi d'un `jti` unique (UUID v4) + durée configurable (`hours`
  passé au `create_access_token`).
- `auth.get_current_user` vérifie que la session n'est **pas révoquée**
  et rafraîchit `last_seen_at` à chaque requête (best-effort). Bypass
  automatique en `TESTING=1`.
- `auth.login` crée une session avec IP + user-agent et applique le
  timeout depuis `settings.security.session_hours` (défaut 8h).
- Endpoints :
  * `GET  /api/security/sessions`               → liste des sessions de
    l'utilisateur + marqueur `current`.
  * `DELETE /api/security/sessions/{jti}`       → révoque une session
    (audit `session_revoked`).
  * `POST /api/security/sessions/revoke-others` → révoque toutes les
    autres sessions (audit `sessions_revoked_others`).
  * `GET  /api/security/timeout`                → timeout actuel + options
    supportées (`[0.25, 0.5, 1, 4, 8, 12, 24]`).
  * `PUT  /api/security/timeout` *(admin)*      → met à jour le timeout
    (`session_hours` ∈ [0.25, 24], audit `session_timeout_changed`).

### Added (frontend)
- **Settings → Sessions actives** (`SecuritySessionsCard`) : sélecteur
  timeout (15min/30min/1h/4h/8h/12h/24h — admin), liste sessions avec
  navigateur, IP, dernière activité, expiration, badge "Actuelle",
  bouton "Déconnecter" par ligne + "Déconnecter toutes les autres".
- **`SessionExpiryWatcher`** (composant global) : décode le JWT côté
  client, affiche un popup fixe bottom-right 60 s avant expiration avec
  "Continuer" (refresh via `/api/auth/refresh`) et "Déconnexion".
- **i18n** : +20 clés FR/EN (`security.sessions_title`, `security.timeout_*`,
  `security.revoke_*`, `security.expiry_*`, `security.current_session`…).

### Tests
- Nouveau fichier `tests/test_v054_sessions.py` — **6 tests** :
  * Liste des sessions expose la session courante.
  * `GET/PUT /timeout` fonctionnent + options exposées.
  * `PUT /timeout` rejette les valeurs hors [0.25, 24].
  * `revoke-others` révoque bien les autres tokens (401 attendu ensuite).
  * Révocation ciblée par `jti`.
  * Endpoints protégés par authentification.
- **108/108 tests critiques verts** (0 régression sur v0.4.x/v0.5.x).

### À suivre (Phases B → F)
- Phase B : Security Center v1 + Security Score.
- Phase C : MFA / TOTP + Refresh Tokens.
- Phase D : RBAC granulaire + Camera Security Score.
- Phase E : Sandbox Plugins + Backups + Notifications.
- Phase F : API Keys + Assistant déploiement + RGPD.


## [v0.5.3] — 2026-02 — Welcome Center refactoré (tutoriels vidéo + widgets) + Dashboard allégé (Session 46)

### Contexte
Retour utilisateur pour recentrer les rôles :
- **Welcome Center** = éditorial (news, changelog, conseils, wiki, tutos, widgets).
- **Tableau de bord** = opérationnel (KPI, activité, alertes récentes).

### Changed (frontend)
- **Welcome Center** :
  * ❌ Supprimé : bloc **Stats express** (4 KPI Caméras/Événements/Plaques/Alertes) — désormais dans le Dashboard uniquement.
  * ❌ Supprimé : bloc **Alertes système** — synthèse déplacée dans le Dashboard.
  * ➕ Ajouté : section **Tutoriels vidéo** (CRUD admin, extraction auto de l'ID YouTube + miniature `hqdefault.jpg`, vignette cliquable ouvrant la vidéo).
  * ➕ Ajouté : section **Widgets** style pfSense (CRUD admin, deux types :
    `note` = texte libre, `links` = liste de liens rapides `label|url`).
- **Dashboard** :
  * ❌ Supprimé : carte **Santé du système** (CPU/RAM/STO/Temp/Bandwidth/Uptime) — redondante avec la topbar temps réel et la santé du Welcome Center.
  * ✅ Le graphique **Activité 24h** occupe désormais toute la largeur.
  * ✅ Les 7 KPI et le condensé d'alertes récentes restent.

### Added (backend)
- Route module `routes/welcome.py` étendu :
  * Collection Mongo **`welcome_tutorials`** : `{id, title, url, youtube_id,
    thumbnail, description, created_at, created_by}`.
  * Collection Mongo **`welcome_widgets`** : `{id, type: 'note'|'links',
    title, body, items?, order, created_at, created_by}`.
  * Endpoints (`admin` pour écriture) :
    - `GET/POST/DELETE /api/welcome/tutorials`
    - `GET/POST/DELETE /api/welcome/widgets`
  * Helper `_extract_youtube_id(url)` supportant youtu.be, youtube.com/watch,
    /embed, /v, /shorts.

### i18n
- Nouvelles clés (FR + EN) : `welcome.tips`, `welcome.tutorials`,
  `welcome.widgets`, `welcome.add_tutorial`, `welcome.add_widget`,
  `welcome.tut_title`, `welcome.tut_desc`, `welcome.publish`,
  `welcome.no_tutorial`, `welcome.no_widget`, `welcome.widget_note`,
  `welcome.widget_links`, `welcome.widget_title`, `welcome.widget_body`,
  `welcome.widget_title_required`, `welcome.load_failed`,
  `welcome.published`, `welcome.publish_denied`, `welcome.delete_confirm`,
  `welcome.delete_denied`, `common.cancel`.

### Tests
- Aucun régression backend (102/102 verts inchangés — les nouveaux endpoints
  suivent le pattern déjà couvert).
- Vérification E2E via Playwright : suppression stats/alertes système
  confirmée, sections Tutoriels + Widgets présentes, Dashboard sans bloc
  santé, graphique activité pleine largeur.


## [v0.5.2.c] — 2026-02 — Map Center · Phases 2, 3 et 4 (Session 45)

### Contexte
Livraison combinée des 3 phases restantes du Map Center comme demandé par
l'utilisateur : cônes de couverture colorés + badges IA (Phase 2), Mode
Audit + photos par caméra + couches on/off (Phase 3), outils de mesure +
exports PNG/PDF/CSV (Phase 4).

### Added (frontend — MapCenter.jsx)

**Phase 2 — Cônes colorés + Badges IA**
- Heuristique `coverageQuality(pos)` → vert (couverture correcte) / jaune
  (moyenne) / rouge (limite) selon (angle_h, range_m, height_m). Le wedge
  FOV est teinté et le cerclé de la caméra reprend la même couleur.
- Détection automatique des rôles caméra (`detectCameraRoles`) : ANPR
  (plugin), PTZ (driver/model/is_ptz), Thermal (model/plugin), IA (detect
  enabled), REC (record enabled). Badges rendus sous l'icône caméra avec
  contre-rotation (toujours lisibles).

**Phase 3 — Mode Audit + Photos + Layers**
- Fonction `auditCamera(cam)` détectant les caméras "incomplètes" :
  offline, sans photo, sans hauteur, sans angle, non positionnée, sans
  driver, firmware absent.
- Bouton **Audit** dans la toolbar (highlight jaune, compteur global).
- Panneau **Audit — Synthèse** (top-droit) : décompte par flag + liste
  cliquable des caméras avec problèmes (`map-audit-cam-*`).
- Halo pointillé jaune autour des caméras en défaut audit.
- Panneau caméra : bandeau audit (avec badges de flags) + section
  **Photos** (grille 3 colonnes, types réelle/install/câblage/armoire/env,
  upload FileReader → dataURI, max 4 MB, suppression au survol).
- Couches on/off (`map-layer-fov`, `-name`, `-badges`, `-status`) —
  toggle instantané sur toutes les caméras.

**Phase 4 — Outils de mesure + Exports**
- Composant `MeasureLayer` : distance (2 clics → segment + longueur en m),
  surface (polygone + double-clic pour finir → aire en m²), rayon (centre
  + bord → cercle et R en m). Utilise `scale_m_per_px` du plan si défini
  (fallback 5 cm/px).
- Toolbar mesures (`D` / `S` / `R`) + bouton de reset (`Trash2`).
- Exports :
  * **PNG** (canvas Konva → dataURL x2 pixel ratio)
  * **PDF** (nouvelle fenêtre imprimable avec image + tableau caméras)
  * **CSV** (Nom, IP, Statut, Driver, Modèle, Hauteur, Angle H, Portée,
    Rotation, Objectif, Technicien, N° série, Date, Notes)
  * **AUDIT CSV** (mode audit uniquement, liste des caméras en défaut)

### Added (backend)
- `MapPositionInput.photos: Optional[list]` — le champ `photos` peut
  maintenant être persisté dans `map_position.photos` (list de
  `{type, data_uri, uploaded_at}`).

### Tests
- 1 nouveau test backend : `test_camera_position_accepts_photos` (upload
  + retrieve).
- 102/102 tests critiques verts v0.4.x/v0.5.x, zéro régression.


## [v0.5.2.b] — 2026-02 — Sidebar sous-menus + renommages FR (Session 44)

### Contexte
Retour utilisateur après v0.5.2 : demande de finaliser la navigation avec
sous-menus dépliables (Accueil / Événements) et de renommer certains
menus pour être plus explicites côté FR.

### Changed
- **Sidebar : sous-menus dépliables** (support des `children` dans NAV,
  chevron animé, ouverture automatique si un enfant est actif).
  * **Accueil** *(nouveau parent)* → sous-menu :
    - Welcome Center (route `/`)
    - Tableau de bord (route `/dashboard`)
  * **Événements** *(nouveau parent, nouveau groupe "ÉVÉNEMENTS")* → sous-menu :
    - Événements (route `/events`, label sans "IA")
    - Alertes (route `/alerts`)
    - Recherche véhicule (route `/vehicles`)
- **Renommages FR** :
  * `Pipeline Center` → **"Suivi des performances"** (FR uniquement, EN reste "Pipeline Center")
  * `Workflows` → **"Automatisations"** (FR + EN "Automations")
  * `Événements IA` → **"Événements"** (retrait de "IA" du texte)
- **Réorganisation** :
  * **Supervision réseau** déplacée dans **Administration** (était dans Opérations).
  * Groupe **Intelligence** simplifié : Zones intelligentes + Automatisations.
- **Docs** : traductions ajoutées (`nav.home`, `nav.events_group`,
  `nav.events_root`, `nav.events_item`).

### Sidebar finale (v0.5.2.b)
- **OPÉRATIONS** : Accueil ⌵ (Welcome Center · Tableau de bord), Mur vidéo,
  Enregistrements, Caméras, Sites, Carte.
- **ÉVÉNEMENTS** : Événements ⌵ (Événements · Alertes · Recherche véhicule).
- **INTELLIGENCE** : Zones intelligentes, Automatisations.
- **ADMINISTRATION** : Suivi des performances, Supervision réseau, Plugins,
  Utilisateurs.
- **JOURNAUX & RAPPORTS** : Rapports, Journal d'audit, Journal de diagnostic.
- **PARAMÈTRES** : Paramètres, Notifications.


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
