# MG-VMS — Product Requirements Document

## Implemented (2026-07-24)
- ✅ **Fix MJPEG `ERR_INCOMPLETE_CHUNKED_ENCODING` (2.16.2 — 2026-07-24)**
  - **Cause racine identifiée** : `streaming.py::live_mjpeg` ne catchait pas les exceptions upstream (`httpx.ReadError`, `RemoteProtocolError`) quand le producteur ffmpeg de go2rtc mourait (OOM VRAM, CUDA reset, restart). L'exception remontait → `StreamingResponse` tronquée → Chrome affichait `ERR_INCOMPLETE_CHUNKED_ENCODING` + image noire. Aggravé par `_ensure_variants` invoqué à chaque requête (thundering herd sur go2rtc).
  - **Fix appliqué (chirurgical, pas de réécriture)** dans `/app/backend/streaming.py` :
    1. **Cache `_ensure_variants_cached()`** — throttle par caméra (TTL 60 s), lock async par caméra pour éviter la race. Diminue drastiquement les appels HTTP vers go2rtc + les `resolve_pipeline()`.
    2. **Robustesse `relay()`** — catche explicitement `httpx.ReadError`, `RemoteProtocolError`, `ReadTimeout`, `ConnectError`, `ConnectionResetError`. Distingue `CancelledError` (client parti → log debug silencieux) des erreurs upstream (log warning).
    3. **Reconnexion transparente au upstream** — si le ffmpeg producer meurt, retry jusqu'à 5x avec backoff progressif (1.5, 3, 4.5, 6, 7.5 s). MJPEG frame-based : la concaténation est transparente pour le browser (boundary auto-aligné).
    4. **Header `X-Accel-Buffering: no`** ajouté pour désactiver le buffering intermédiaire nginx/proxy.
  - **Tests sandbox validés** : single-client stream OK (2 fps, boundary + magic JPEG confirmés), 3 requêtes rapides consécutives → 1 seul appel `/api/streams` vers go2rtc (cache OK), client abandonné → cleanup silencieux sans stack trace.
  - **À valider sur serveur GPU réel** : test 5 clients simultanés + `docker restart go2rtc` (doit reprendre auto) + `pkill ffmpeg cam_XXX` (doit se reconnecter).
- ✅ **Audit sécurité (2026-07-24) — Rapport "Code Quality" du handoff = faux positifs**
  - `exec()` allégué dans routers.py:995, recorder.py:81/299 → en réalité `asyncio.create_subprocess_exec()` (args tokenisés, safe).
  - "Import dynamique" routers.py:1045 → en réalité `data.model_dump()` (Pydantic, safe).
  - "Dépendance circulaire" auth.py↔notifications.py → import lazy dans une fonction (pattern standard Python).
  - Anti-pattern `is True/False/const` → aucun trouvé.
  - Aucun `eval()`, `os.system`, `shell=True` dans `/app/backend/*.py`.
  - Seule amélioration mineure appliquée : credentials de test `tests/test_iter23_anpr_csv.py` déplacés en env vars (`TEST_ADMIN_EMAIL`, etc.) avec fallback aux valeurs actuelles.


## Implemented (2026-07)
- ✅ **Phase 4 (suite) — Player WebRTC frontend (2.16.1 — 2026-07-23)**
  - **Objectif** : remplacer l'`<img>` MJPEG par un `<video>` HTML5 recevant du H.264 pass-through via WebRTC — latence 200-500 ms au lieu de 1-2 s, aucun transcodage go2rtc (donc 0 charge CPU/GPU serveur pour l'aperçu), aucun artefact MJPEG.
  - **Backend** : nouveau endpoint `POST /api/pipeline/webrtc/{camera_id}` — proxy SDP signaling entre le navigateur et go2rtc `/api/webrtc?src=cam_XXX`. Auth centralisée, aucun besoin de reverse-proxy custom pour le signaling (le média RTP passe ensuite en direct navigateur↔go2rtc:8555 via ICE).
  - **Frontend** :
    - Nouveau composant `WebRTCPlayer.jsx` : `new RTCPeerConnection` avec STUN Google, `addTransceiver("video"/"audio", recvonly)`, `createOffer` + gathering ICE complet (2 s max), POST offer au backend, applique la SDP answer. `<video autoPlay playsInline muted>` reçoit le stream H.264 natif. Overlay "Négociation WebRTC…" pendant le handshake. Callbacks `onError` + `onConnected`.
    - `LiveView.jsx` :
      - Charge `preview_mode` depuis `/api/pipeline/config` au démarrage.
      - Composant `Feed` : essaie WebRTC en 1er sauf si `preview_mode=mjpeg` forcé. Bascule automatique sur MJPEG (`<img>` classique) si WebRTC échoue (`onError` → `setWebrtcFailed(true)` → re-render).
      - Badge de qualité coloré : `WEBRTC` cyan quand actif, `HD` vert / `SD` orange en fallback.
      - Reset du fallback à chaque changement de caméra / mode / HD-SD.
  - **Comportement sandbox** : Cloudflare edge ne relaie pas les ports UDP ICE (go2rtc:8555 pas exposé), donc négociation ICE timeout → **fallback MJPEG activé automatiquement**. Les 2 caméras démo restent visibles sans écran noir ni crash. C'est exactement le comportement attendu en cas d'infrastructure non-WebRTC-ready.
  - **Comportement production (RTX A2000 + reverse-proxy configuré)** :
    - Reverse-proxy doit exposer `go2rtc:8555/tcp` (WebRTC signaling secondaire) + range UDP (par défaut auto-négocié).
    - Alternative simplifiée : ajouter dans `go2rtc.yaml` la ligne `webrtc.ice_servers` avec un serveur STUN/TURN public + `webrtc.listen: ":8555"` déjà présent.
    - Une fois routé → badge `WEBRTC` cyan, latence typique 200-500 ms, 0 charge CPU/GPU serveur pour l'aperçu (H.264 pass-through direct depuis la caméra).
  - **À suivre** : NVDEC direct pour le pipeline IA (bypass OpenCV VideoCapture pour lire directement depuis `ffmpeg -hwaccel cuda -c:v h264_cuvid` piped en numpy) — ~2 jours de travail.


- ✅ **Phase 4 — Moteur vidéo intelligent (2.16.0 — 2026-07-23)**
  - **Objectif** : refonte du pipeline vidéo pour exploiter NVDEC / NVENC / scale_cuda quand présents, WebRTC pass-through au lieu de MJPEG systématique, recorder `-c copy` sans perte, et interface admin claire pour tout piloter.
  - **Backend `/app/backend/video_engine.py`** (~250 lignes) :
    - `_ffmpeg_capabilities()` mémoïsée : détecte via subprocess ffmpeg `-hwaccels` / `-decoders` / `-encoders` / `-filters` la présence de : `cuda` / `vaapi` / `vulkan` / `qsv`, décodeurs cuvid (h264/hevc/av1/mjpeg/mpeg4/vp9/vp8), encodeurs nvenc (h264/hevc/av1), filtres CUDA (scale_cuda, colorspace_cuda, hwupload_cuda, overlay_cuda, thumbnail_cuda, yadif_cuda, scale_npp).
    - `has_cuda_pipeline()` croise capabilities FFmpeg + présence GPU NVIDIA (NVML) — n'active le pipeline GPU que si les 2 sont OK.
    - Config persistée (collection `system_config` clé `video_engine`) : `pipeline_mode` (auto/gpu/cpu/direct), `preview_mode` (auto/webrtc/mjpeg/mse), `ai_pipeline` (auto/gpu/cpu), `recorder_mode` (auto/copy/reencode), `hd_preview_width`, `sd_preview_width`, `low_latency`.
    - `resolve_pipeline(cam)` : décide par caméra le pipeline effectif — retourne mode, décodeur (h264_cuvid / hevc_cuvid / software), preview (webrtc si H.264, sinon mjpeg), recorder (copy si H.264/H.265, reencode-gpu/cpu sinon), IA (gpu si torch.cuda dispo), + **filtres FFmpeg optimisés** (`#hardware=cuda#width=640#low_latency`) — appliqués aux flux go2rtc.
    - `engine_status()` : rapport global pour la page `/pipeline` (config + capabilities + pipeline effectif par caméra + raison du choix).
  - **Backend `streaming.py`** :
    - `register_camera_stream()` et `_ensure_variants()` utilisent maintenant `resolve_pipeline(cam)` pour construire les filtres. Sur GPU présent → `ffmpeg:{name}#video=mjpeg#hardware=cuda#width=640#low_latency` (NVDEC + scale_cuda + faible latence). Sur CPU → filtres SW classiques + low_latency.
  - **4 endpoints REST** :
    - `GET /api/pipeline/config` — config actuelle + capabilities FFmpeg + `cuda_pipeline_ready`.
    - `PUT /api/pipeline/config` — met à jour (admin) avec validation stricte des valeurs autorisées + audit log.
    - `GET /api/pipeline/status` — rapport global (config + caps + pipeline par caméra).
    - `GET /api/pipeline/webrtc/offer/{camera_id}` — URL du signaling go2rtc WebRTC pour cette caméra (`/webrtc/api/ws?src=cam_XXX`) — le frontend l'utilisera pour établir la `RTCPeerConnection` H.264 pass-through.
  - **Frontend nouvelle page `/pipeline` (PipelineVideo.jsx)** :
    - Bandeau **Capacités FFmpeg détectées** : 8 badges (CUDA pipeline / hwaccel cuda / h264_cuvid / hevc_cuvid / h264_nvenc / hevc_nvenc / scale_cuda / colorspace_cuda) — verts si présents, rouges sinon. Version FFmpeg + liste des hwaccels bruts.
    - 4 blocs radio (Pipeline vidéo global · Prévisualisation · Pipeline IA · Recorder) avec descriptions humaines.
    - Options avancées : largeur HD (0=native), largeur SD, faible latence.
    - **Tableau Pipeline effectif par caméra** : nom, codec/résolution, mode (badge coloré CPU/GPU), décodeur, preview, recorder, IA, **raison du choix** — permet de comprendre en un coup d'œil pourquoi telle caméra tourne sur CPU ou GPU.
    - Boutons Actualiser, Sauvegarder (activé si `dirty`), **Appliquer à toutes les caméras** (déclenche `/refresh-stream` en batch → recrée les flux go2rtc avec les nouveaux filtres).
    - Sidebar : entrée `Pipeline vidéo` (Administration) i18n FR/EN.
  - **Comportement observé sur sandbox (pas de GPU)** : `mode=cpu`, `decoder=software`, `preview=webrtc` (auto-choix H.264), `recorder=copy` (H.264 natif → 0 encodage inutile), `ai=cpu`, filtre `video=mjpeg#low_latency`. Sur RTX A2000 : tous les badges verts, `mode=gpu`, `decoder=h264_cuvid`, filtre `video=mjpeg#hardware=cuda#width=640#low_latency` = **NVDEC actif + scale_cuda**.
  - **À suivre (backlog Phase 4 restant)** :
    - Player WebRTC natif côté frontend (RTCPeerConnection + go2rtc signaling WebSocket) pour remplacer MJPEG quand `preview_mode=webrtc`.
    - Fix des artefacts vidéo : analyse conversion couleur (yuv420p → rgb), buffers, pixel format à isoler par diagnostic sur les caméras affectées.
    - Utilisation directe de NVDEC par le pipeline IA (bypass OpenCV VideoCapture actuel) — nécessite modification de `_fetch_frame` en `ai_engine.py` pour lire directement depuis un décodeur cuvid.


- ✅ **Phase 3 — Accélération GPU + Benchmark ANPR (2.15.0 — 2026-07-23)**
  - **Objectif** : certifier le support GPU multi-vendor, ajouter une icône GPU dans le header (comme CPU/RAM/STO), et livrer un outil de comparaison de perf pour diagnostiquer les régressions ANPR.
  - **Backend `/app/backend/gpu.py`** (nouveau module ~250 lignes, 100% no-crash) :
    - Détection NVIDIA via `nvidia-ml-py==13.610.43` (successeur du package `pynvml` déprécié).
    - Par device : nom, UUID, VRAM total/used/free/util%, **utilisation encoder/decoder H.264/H.265** (crucial VMS), température, puissance, ventilateur, clocks GPU/VRAM, CUDA compute capability, mode persistance.
    - Détection runtimes multi-vendor : `torch.cuda` (PyTorch), `TensorRT` (import + fallback binaire trtexec), `onnxruntime` (CUDA/TensorRT/ROCM/CoreML/DirectML providers), `OpenCV CUDA` (`cv2.cuda.getCudaEnabledDeviceCount`).
    - `gpu_summary()` = snapshot compact mémoïsé 2 s pour le poll header. `gpu_full_info()` = rapport détaillé pour la page. `is_gpu_active_for_pipeline()` = bool.
    - Fallback gracieux : sans NVIDIA driver → `available=false` + `error="NVML Shared Library Not Found"` (message exact non tronqué). Sur RTX A2000 utilisateur (VM + Docker `--gpus all`) → tous les champs remplis.
  - **Backend `realtime.metrics_snapshot()`** enrichi de `gpu={available, vendor, name, gpu_util_pct, vram_*, temperature_c}` — polled par le header via `/dashboard/stats` existant.
  - **3 endpoints REST** :
    - `GET /api/system/gpu/summary` — snapshot compact (poll header, permission `view_live`).
    - `GET /api/system/gpu` — rapport complet (page GPU, permission `technician`).
    - `POST /api/system/anpr-benchmark?camera_id=&iterations=1..30` — lance le pipeline complet `_analyze_frame` en boucle sur un frame réel go2rtc, retourne `avg_total_ms`, `avg_yolo_ms`, `avg_alpr_ms`, `estimated_fps`, `plates_detected_total`, `plates_ocr_success`, `plates_ocr_failed`, `ocr_success_rate`, `gpu_active`, `torch_backend`, `torch_version`, `cuda_version`, `yolo_model`, `alpr_model`, `samples[]`, `run_at`. Validation stricte des bornes (1-30 itérations).
  - **Frontend Header (Layout.jsx)** :
    - Nouveau composant `GpuMiniBar` — icône `Zap` cliquable (nav vers `/gpu`), 3 états :
      - GPU actif → couleur selon `gpu_util_pct` (vert < 65%, orange < 80%, rouge sinon) + tooltip nom/VRAM/temp.
      - GPU absent → texte `CPU` rouge + `N/A` + tooltip explicatif "Aucun GPU NVIDIA détecté — pipeline IA sur CPU".
    - Rangée dans le header : CPU · RAM · STO · **GPU** (nouveau).
    - Bug fixé : import `Zap` était dupliqué en lucide-react (2 fois dans la même destructuration) → build cassé → réparé.
  - **Frontend nouvelle page `/gpu` (GPUStatus.jsx)** :
    - Bandeau statut coloré (vert si GPU actif, rouge sinon) — nom, driver version, NVML version, CUDA driver + état pipeline (YOLO GPU/CPU).
    - Grille 12 StatCards temps réel (util GPU, encoder, decoder, VRAM used/total/util%, température, puissance, ventilateur, clocks GPU/VRAM, compute cap).
    - Table des 4 runtimes détectés (statut Actif/Inactif + version + détails).
    - Support multi-GPU : liste tous les devices si > 1.
    - Section aide 5 étapes si pas de GPU (drivers, container-toolkit, `--gpus all`, `nvidia-smi`, PyTorch `+cuXX`).
    - Auto-refresh 5 s (toggle ON/OFF).
  - **Frontend nouvelle page `/anpr-benchmark` (AnprBenchmark.jsx)** :
    - Sélecteur caméra + itérations (1-30) + bouton "Lancer le benchmark".
    - 2 cartes côte à côte : **Baseline** (sauvegardée en localStorage) vs **Actuel** — chaque carte affiche résolution, FPS estimé, cycle total moy, YOLO moy, ALPR moy, détections/frame, plaques total, OCR réussi, taux OCR, torch backend/version, CUDA version, modèle YOLO. Badge `GPU`/`CPU` visuel.
    - Panneau **Comparaison Baseline → Actuel** : 7 barres delta (cycle total, YOLO, ALPR, FPS, plaques détectées, taux OCR, détections/frame) avec code couleur automatique (vert si meilleur, rouge si dégradation, gris si identique) + variation absolue et %.
    - Alerte automatique si backend d'accélération a changé entre les 2 mesures (CPU→GPU ou inverse).
    - Boutons "Enregistrer comme baseline" + "Effacer baseline".
  - **Sidebar** : 2 nouvelles entrées section Administration : `Accélération GPU` (icône Zap) et `Benchmark ANPR` (icône Cpu). i18n FR + EN.
  - **Validation bug_testing_agent** — verdict **fixed** :
    - Backend contract 100% : requirements.txt OK, module gpu.py utilise encoder/decoder/bytes-str, import sans crash + `available=false` + error explicite, endpoints /summary et /full retournent bon schéma, `/dashboard/stats` inclut gpu, benchmark validation (0 et 50 → 400) + iterations=3 → ~230ms CPU cycle, `gpu_active=false`, `torch_backend=cpu`.
    - Frontend contract 100% : login admin OK, `data-testid=metric-GPU` visible avec fallback CPU rouge N/A, clic navigue vers /gpu, sidebar montre Accélération GPU et Benchmark ANPR, /gpu rend titre + bandeau + runtimes + reload + aide 5 étapes, /anpr-benchmark rend config + bouton, exécution benchmark → toast succès + carte "Version actuelle" avec métriques.
    - Le comportement sur GPU physique (RTX A2000) ne peut être testé dans le sandbox mais le code est prêt : tous les champs NVML sont capturés dans un `try/except` isolé (aucun crash même si un champ manque sur un driver ancien).


- ✅ **Régression perf ANPR corrigée + Phase 1 Diagnostic caméra (2.13.5 + 2.14.0 — 2026-07-23)**
  - **Bug utilisateur** : « L'ANPR est bcp plus lent, moins réactif » sur le dernier push.
  - **Cause racine** :
    1. Depuis v2.13.0, `_jpeg_data_uri()` compressait par défaut à 1280 wide @ q85 (au lieu de 360 @ q60) — encodage ~10× plus lent.
    2. `_analyze_frame` encodait systématiquement `frame_thumb` à chaque cycle IA, MÊME sans événement (30-80 ms/cycle inutiles sur caméras 2K).
    3. Premier fix insuffisant : `_evaluate_scenarios` appelait `_ensure_frame_thumb(result)` en début de fonction, neutralisant le lazy contract → **détecté par le bug_testing_agent**.
  - **Fix v2.13.5** (encodage lazy) :
    - `_analyze_frame` retourne l'image numpy `_img_bgr` (au lieu de la base64 précalculée).
    - Nouveau helper `_ensure_frame_thumb(result)` avec mémoïsation dans `result["frame_thumb"]` — appelé UNIQUEMENT à l'insertion d'un événement. 0 event = 0 encodage.
    - `frame_preview` (debug) réduit à q60.
    - Tous les callers (`_process_camera` motion/face/YOLO/plate) migrés vers `_ensure_frame_thumb(result)`.
  - **Fix v2.13.6** (correctif après bug_testing_agent) :
    - `_evaluate_scenarios` : `thumb` devient `lambda: _ensure_frame_thumb(result)` — appelé UNIQUEMENT dans les branches où un scénario matche réellement.
    - 2 nouveaux tests prouvent le contrat : `test_no_encoding_when_no_detections` (0 détection → 0 encodage) + `test_encoding_only_when_scenario_triggers` (1 match → 1 seul encodage mémoïsé).
  - **Phase 1 Diagnostic caméra (2.14.0)** — sections 1-4 du prompt refonte :
    - Nouveau module `/app/backend/diagnostics.py` (~250 lignes) :
      - Table `CAUSE_RULES` : 18 patterns regex mappés à des causes explicites (Timeout RTSP, Authentification refusée, Caméra hors ligne, Erreur DNS, GOP corrompu, Pertes réseau, Flux interrompu, Flux RTSP invalide, Erreur ONVIF, Crash go2rtc, Saturation GPU, Mémoire insuffisante, Saturation CPU, Exception Python, TCP réinitialisé, Erreur UDP, Caméra redémarrée, Cause inconnue).
      - `identify_cause(error_text)` retourne `(cause, confidence_%, detail)`.
      - `capture_stream_metrics(cam)` interroge go2rtc pour fps réel, bitrate, codec détecté (fallback gracieux).
      - `record_disconnect(cam, error_text, source)` + `record_reconnect(camera_id, attempts)` : logue les transitions online↔offline dans la collection `camera_diagnostics` avec URL masquée, uptime avant incident, tentatives, durée reconnexion, erreur brute complète (4KB max).
      - `tail_log(source, filter_text, lines)` : lecture async des logs supervisor (backend/go2rtc) via `deque` (efficace sur gros fichiers).
      - `camera_diagnostic_summary(id)` : MTBF, moyenne reconnexion, top 5 causes, dernier incident (fenêtre 30 j).
    - Hook dans `streaming.camera_status_loop` : détection des transitions ONLINE↔OFFLINE, capture de l'erreur brute go2rtc (HTTP status + body), enregistrement automatique. Compteur de tentatives de reconnexion par caméra.
    - **5 nouveaux endpoints** :
      - `GET /api/diagnostics/journal?camera_id=&cause=&event_type=&limit=&offset=` — journal global filtrable + multi-site.
      - `GET /api/diagnostics/camera/{id}/summary` — résumé 30j.
      - `GET /api/diagnostics/camera/{id}/logs?lines=100` — tail logs backend+go2rtc filtrés sur la caméra.
      - `GET /api/diagnostics/camera/{id}/report` — rapport JSON complet téléchargeable (config + summary + 200 incidents + 200 lignes de logs, URL masquée, **pas de mot de passe en clair**).
      - `POST /api/diagnostics/camera/{id}/test-cause` — utilitaire admin pour tester l'heuristique sur un texte d'erreur.
    - **Nouvelle page frontend `/diagnostics`** :
      - Vue d'ensemble par caméra : cartes MTBF/déconnexions/reconnexions/temps moyen + causes fréquentes colorées + bouton téléchargement rapport (JSON avec nom `mgvms-diag-{cam}-{date}.json`).
      - Filtres : caméra, cause, type d'événement (déconnexion/reconnexion).
      - Journal (table) : date, caméra, site, cause probable (badge coloré par sévérité), uptime avant, état reconnexion.
      - Modal détail incident : type, source, états, uptime, tentatives, durée reconnexion, profil ONVIF, codec/résolution/FPS demandé & réel/bitrate/transport, URL masquée, **erreur brute complète** (pré-formatée, jusqu'à 4KB).
      - Nouveau lien `Journal de diagnostic` dans le sidebar (section Administration).
      - i18n FR + EN.
  - **Validation bug_testing_agent** :
    - Verdict = **fixed**, 100% backend + 100% frontend, retest_needed=false.
    - Vérifié : spy `_ensure_frame_thumb` sur `_evaluate_scenarios` sans détection → `call_count=0`. Avec attroupement → `call_count=1`.
    - Vérifié : événements réels demo-cam-002 génèrent bien des miniatures HD (~768×432).
    - Vérifié : les 5 endpoints diagnostic répondent correctement, URL RTSP masquée dans le rapport, page frontend `/diagnostics` rend pour admin.
    - Pytest : **37/37** (iter25 + iter26 + iter27 + iter28 = 7 nouveaux).


- ✅ **Hybridation ANPR — Scène HD + insets véhicule + plaque OCR (2.13.4 — 2026-07-23)**
  - **Contexte** : après le passage au HD des miniatures d'événements (v2.13.0), les plaques LAPI et alertes blacklist restaient sur `plate_crop` seul (~21×26 px) — plaque lisible mais aucun contexte visuel de la scène.
  - **Fix backend `ai_engine.py`** :
    - Documents `plates` : ajout du champ `frame_thumb` (scène HD complète 1280 wide, quality 85) en plus de `plate_crop` (crop OCR net) et `vehicle_crop` (crop véhicule complet).
    - `_raise_blacklist_alert` : la miniature principale (`thumbnail`) est désormais `frame_thumb` (scène HD) ; `plate_crop` et `vehicle_crop` conservés en champs séparés pour l'affichage en insets.
  - **Fix frontend `EventViewer.jsx`** — **hybridation visuelle** :
    - Fond : scène HD (item.thumbnail) zoomable/pannable (comportement existant).
    - Overlay bas-droite (bordure blanche) : **inset VÉHICULE** (`vehicle_crop`, max 180×110).
    - En dessous (bordure cyan `#00E5FF`) : **inset PLAQUE OCR** (`plate_crop`, max 180×70) + libellé texte de la plaque (tracking-widest, mono, gras) sous le crop pour lisibilité maximale.
  - **Fix frontend `Anpr.jsx` + `Alerts.jsx`** :
    - `viewerItems` transmet désormais `thumbnail: frame_thumb`, `plate_crop`, `vehicle_crop` séparément — EventViewer déclenche automatiquement le rendu hybride quand les 2 champs coexistent.
  - **Validation Playwright** : plaque `G57854` @ 33s fraîchement détectée → JSON API expose `frame_thumb=768×432·16KB`, `vehicle_crop=116×102·3KB`, `plate_crop=21×26·<1KB`. Ouverture du viewer sur `/anpr` → screenshot confirme scène HD au centre + insets `VÉHICULE` et `PLAQUE OCR G57854` en overlay droit. crops=1/vehicle=1/plate=1 côté DOM. ✅
  - **Récapitulatif complet des miniatures HD** :
    | Type d'alerte | thumbnail | crops annexes |
    | --- | --- | --- |
    | YOLO (Personne, Voiture, …) | scène HD (1280 wide) | `crop_thumbnail` (bbox) |
    | Mouvement, Face, Scénarios IA | scène HD | — |
    | Plaque LAPI + Alerte blacklist | scène HD (1280 wide) | `plate_crop`, `vehicle_crop` (insets) |

- ✅ **Mur vidéo — Navigation clavier + timeline événements en mode focus (2.13.3 — 2026-07-23)**
  - **Navigation entre caméras au clavier** (mode focus uniquement) :
    - `←` / `→` : caméra précédente / suivante (cyclique). Skip automatique des slots vides.
    - `ESC` : sortie du mode focus.
    - `T` : bascule affichage timeline.
    - Boutons `ChevronLeft` / `ChevronRight` + compteur `N/M` (position dans la mosaïque) dans la barre d'action.
    - Ignore les événements clavier si l'utilisateur tape dans un `<input>` / `<textarea>`.
  - **Mini-timeline des 10 derniers événements** en overlay bas de la caméra focalisée :
    - Fetch initial + rafraîchissement toutes les 8 s via `GET /api/events?camera_id=X&limit=10`.
    - Vignette + label + heure (`HH:MM:SS`) pour chaque événement. Vignettes cliquables → **modal plein écran** avec image HD (utilise la miniature 1280×720 du fix v2.13.0), horodatage FR complet, nom caméra, confidence YOLO.
    - Bouton toggle « Timeline » (raccourci `T`) pour masquer/afficher.
    - État vide propre : « Aucun événement récent pour cette caméra. »
  - **UX** : la timeline est superposée au flux vidéo (pointer-events-auto sur la timeline, transparent partout ailleurs), sans bloquer l'image en dessous. Design cohérent (`bg-black/80`, bordure `#00E5FF` au hover, mono-font pour les timestamps).
  - **Validation Playwright** : screenshot mode focus (compteur 2/2, timeline 10 vignettes avec heures 06:17:30 → 06:20:53, bordures noires) + navigation ← → confirmée (2/2 → 1/2, changement de caméra effectif). ✅

- ✅ **UX Mur vidéo : tuiles rectangulaires, cliquables + focus mode + détection sous-flux (2.13.2 — 2026-07-23)**
  - **Format rectangulaire 16:9** : les tuiles utilisent maintenant `aspect-video` + `object-contain` (au lieu de `object-cover` sur cellule carrée). Plus aucun cropping — l'intégralité de la vidéo caméra (nativement en 16:9) est visible dans chaque tuile de la mosaïque.
  - **Tuiles cliquables → mode focus** : cliquer une tuile ouvre une vue "focus" single-view où la caméra sélectionnée occupe toute la largeur (`gridTemplateColumns: 1fr`). Un bouton **« Fermer le focus »** apparaît dans la barre supérieure. Retour à la mosaïque via clic sur la tuile, sur ce bouton, ou touche **ESC**. Les boutons de layout (1/4/9/16…) sont masqués en mode focus. Bordure `#00E5FF` autour de la tuile active. Le clic sur les boutons PTZ n'active PAS le focus (event.stopPropagation + `data-ptz-btn`).
  - **Détection automatique de sous-flux** :
    - Live View : badge d'alerte jaune « ⚠ Sous-flux détecté ({résolution}) — ouvrez le diagnostic pour re-sélectionner le profil principal. » superposé sur chaque tuile dont la caméra a une `resolution < 1280×720`.
    - Cameras (liste) : badge `SUB` orange dans la colonne Résolution avec tooltip explicatif.
    - Diagnostic (dialog) : bandeau d'alerte détaillé avec instructions étape par étape pour re-sélectionner le profil main via le formulaire d'édition.
    - Le badge résolution est aussi affiché en overlay sur chaque tuile Live pour un contrôle visuel immédiat.
  - **Sortie ESC** : `useEffect` avec listener global `keydown` sur `Escape` en mode focus.
  - **Validation UI** : Playwright screenshots — mosaïque 4 tuiles 16:9 (2 vidéos actives visibles entières + 2 slots vides rectangulaires), mode focus (tuile 1 en pleine largeur avec bouton "Fermer le focus"). pytest backend 30/30 vert (aucune régression).

- ✅ **BUG FIX Live SD/HD + Miniatures d'événements HD (2.13.0 → 2.13.1 — 2026-07-23)**
  - **Complément v2.13.1** — auto-migration pour caméras existantes :
    - **Problème** : les caméras enregistrées avant le fix v2.13.0 n'avaient que la variante `_sd` dans go2rtc → le toggle HD frontend envoyait `?hd=1` mais le backend proxifiait vers un `_hd` inexistant → écran gris ou fallback SD.
    - **Fix backend `_ensure_variants(name)`** : nouveau helper qui vérifie et crée à la volée les variantes `_hd`/`_sd` manquantes dans go2rtc, sans toucher au producteur principal (pas de churn recorder/IA). Appelé :
      - au démarrage via `sync_all_streams` — parcourt toutes les caméras existantes et complète les variantes manquantes ;
      - à chaque hit sur `/api/stream/{id}/live.mjpeg` et `/api/stream/{id}/frame.jpeg` — auto-migration transparente en cas de config obsolète.
    - **Nouvel endpoint `POST /api/cameras/{id}/refresh-stream`** (permission `technician`) : force la ré-registration complète des 3 flux (base + `_hd` + `_sd`) dans go2rtc. Utile après un redémarrage go2rtc ou un changement de config caméra. Auditté (`camera_stream_refreshed`).
    - **Diagnostic enrichi** (`GET /api/cameras/{id}/diagnostic`) : expose désormais `flux.go2rtc_hd_registered` + `flux.go2rtc_sd_registered` + `stream_urls.live_mjpeg_hd` + `stream_urls.frame_jpeg_hd` pour visualiser l'état exact des 3 variantes.
    - **Frontend `DiagnosticDialog`** : nouveaux indicateurs (checks HD/SD séparés) + bouton **"Ré-enregistrer le flux (HD + SD)"** avec toast de confirmation. Bandeau d'alerte jaune si une variante manque.
  - **Validation** : test de simulation → suppression manuelle de `cam_demo-cam-001_hd` dans go2rtc, puis appel de `/frame.jpeg?hd=1` → la variante est recréée automatiquement, HD 1280×720 renvoyé. `POST /refresh-stream` renvoie 200 + URL masquée. Diagnostic expose bien les 3 checks. ✅

- ✅ **BUG FIX Live SD/HD + Miniatures d'événements HD (2.13.0 — 2026-07-22)**
  - **Bug 1** — le bouton SD/HD du Live n'avait aucun effet, la prévisualisation restait toujours en 640px (sous-flux).
    - **Cause racine** : `_mjpeg_stream()` retournait *toujours* `{name}_sd` (variante MJPEG 640 hardcodée). L'endpoint `/api/stream/{id}/live.mjpeg` n'acceptait pas de paramètre HD.
    - **Fix backend** :
      - `register_camera_stream` enregistre désormais **3 variantes** dans go2rtc : `{name}` (source RTSP brute pour recorder+IA), `{name}_hd` (ffmpeg → MJPEG résolution native), `{name}_sd` (ffmpeg → MJPEG width=640).
      - `_mjpeg_stream(camera_id, hd=False)` retourne `{name}_hd` ou `{name}_sd` selon le booléen.
      - `/api/stream/{camera_id}/live.mjpeg?hd=1` accepte le param, vérifie `has_permission(user, "stream_hd")`, et proxifie la bonne variante. Rétrogradation silencieuse vers SD si l'utilisateur n'a pas la permission.
      - `/api/stream/{camera_id}/frame.jpeg?hd=1` (défaut) tente le flux brut natif → fallback `_hd` → fallback `_sd`.
      - `unregister_camera_stream` supprime les 3 variantes.
      - `go2rtc.yaml` (caméras démo) enrichi avec les entrées `_hd`.
    - **Fix frontend `LiveView.jsx`** :
      - `streamUrl(camId, hd)` propage `&hd=1` dans l'URL.
      - Le `useEffect` du composant `Feed` inclut désormais `hd` dans les dépendances → force le rechargement du `<img>` MJPEG à chaque toggle SD ↔ HD.
    - **Validation** : `curl /api/stream/demo-cam-001/frame.jpeg?hd=0` → **640×360**, `?hd=1` → **1280×720**. Idem sur `live.mjpeg` (bytes MJPEG extraits) : SD = 640×360, HD = 1280×720. ✅
  - **Bug 2** — miniatures des événements trop faibles pour identifier personnes/plaques/objets.
    - **Cause racine** : `_jpeg_data_uri()` compressait à `max_width=360 @ quality=60` par défaut. De plus, les événements YOLO (Personne/Voiture) stockaient uniquement le *crop* du bbox (souvent < 100 px) comme thumbnail.
    - **Fix** :
      - `_jpeg_data_uri()` : nouveau défaut **1280 max_width @ q=85**. Ne fait JAMAIS de upscale (préserve la taille naturelle des petits crops). Interpolation `INTER_AREA` pour downscale de qualité.
      - Événements YOLO : `thumbnail = frame_thumb` (scène complète HD 1280×720 ou native) + `crop_thumbnail = det["thumbnail"]` (le crop bbox reste en secondaire).
      - Événements Mouvement, Visage, Alertes IA : déjà en `frame_thumb`, bénéficient automatiquement du nouveau défaut HD.
    - **Validation** : nouvel événement Personne enregistré → `thumbnail=768×432 · 16 KB` (scène complète du flux principal) + `crop_thumbnail=30×49 · 1 KB` (bbox précis conservé). Identifiable en plein écran. ✅
  - **Tests** : `tests/test_iter27_sd_hd_thumbs.py` (7 tests unitaires — sélecteur MJPEG HD/SD, `_jpeg_data_uri` HD par défaut + pas de upscale + max_width custom, noms de flux distincts). **Total pytest : 30/30** (iter25 + iter26 + iter27).

- ✅ **BUG FIX ONVIF — Le profil choisi (main/sub) est désormais persisté exactement (2.12.0 — 2026-07-22)**
  - **Cause racine** : `POST /api/cameras` (mode ONVIF) appelait `_try_ffprobe_variants(selected["rtsp_url"], …)` qui générait des variantes RTSP (main + sub, h264 + h265) et retenait la **première qui répondait** — potentiellement le sub-stream, même si l'utilisateur avait explicitement coché le profil main dans le dialog. Résultat : la debug page affichait bien `h264Preview_02_main` (2304x1296), mais après sauvegarde, go2rtc/live preview utilisait le sub-stream basse résolution.
  - **Fix backend** :
    - Nouveau helper `_ffprobe_validate_exact(base_url, transport, user, pass)` dans `streaming.py` — valide **EXACTEMENT** l'URL fournie (aucune substitution de variante). Fallback autorisé uniquement entre TCP et UDP (le transport peut varier, l'URL jamais).
    - `POST /api/cameras` (mode=onvif) : remplace `_try_ffprobe_variants` par `_ffprobe_validate_exact`. L'URL du profil choisi est **la seule** testée et persistée. En cas d'échec + `allow_rtsp_override=false` → HTTP 400 explicite : « URL RTSP du profil "X" injoignable — choisissez un autre profil ou cochez "Créer malgré le test RTSP" ».
    - `PUT /api/cameras/{id}` (mode=onvif) : idem. La `resolution`/`codec` est rafraîchie depuis le ffprobe réel (précis), mais `rtsp_url` reste = URL du profil sélectionné.
    - `POST /api/cameras/test-connectivity` : nouveau champ `profile_token` (optionnel). Si fourni → pick le profil correspondant + `_ffprobe_validate_exact` (aucune substitution). Sinon → comportement historique (variants pour découverte). Le step `rtsp_open` expose désormais `profile_token` + `profile_name` + label « profil « Main » » dans le message.
  - **Fix frontend `Cameras.jsx`** :
    - `runConnectivity` envoie désormais `profile_token` au backend (respect du choix explicite lors du re-test).
    - Auto-sélection par **résolution maximale** (produit largeur×hauteur) à la place du premier profil de la liste — Reolink/Hik renvoient souvent le sub en premier, l'utilisateur voulait le main par défaut.
    - Nouveau badge visuel `MAIN` (bleu) / `SUB` (gris) devant chaque profil, détecté par regex sur le nom + l'URL.
    - Bordure `#00E5FF` autour du profil actuellement sélectionné (radio checked).
    - Note UX : « Aucune substitution de flux — l'URL exacte du profil coché est persistée et utilisée par go2rtc. Cliquez sur "Tester la connexion" après avoir changé de profil pour re-valider. »
    - Changer le profil radio réinitialise `connCheck` pour forcer le re-test.
  - **Tests** : `tests/test_iter26_onvif_profile_exact.py` (4 tests unitaires — retourne exact URL, fallback tcp→udp sans changer l'URL, jamais de substitution main↔sub, échec propre si les 2 transports échouent). testing_agent iteration_26 : 22/22 pytest (18 iter25 + 4 iter26), 100% backend, 0 issue, retest_needed=False.

- ✅ **BUG FIX FINAL — Suppression totale du fragment `#transport=…` dans les URLs RTSP (2.11.2 — 2026-07-22)**
  - **Cause racine** : go2rtc échoue à décoder les flux RTSP lorsque l'URL contient `#transport=udp` (ou `#transport=tcp`). Symptômes constatés par l'utilisateur : "Aperçu indisponible", `frame.jpeg` KO, faux échec dans le workflow d'édition caméra. Validé manuellement par l'utilisateur : URL sans fragment → tout fonctionne (frame JPEG 35 KB, live OK, décodage OK).
  - **Fix appliqué dans `_build_rtsp_url`** :
    1. **Suppression totale de l'ajout automatique du fragment `#transport=…`** (auparavant systématique).
    2. **Nettoyage historique** : si une URL entrée contient déjà `#transport=…` (données legacy stockées avant ce fix), le fragment est retiré à la génération.
  - **Transport RTSP toujours honoré** :
    - **ffprobe** : utilise l'option CLI `-rtsp_transport tcp|udp` dans `_ffprobe` (déjà en place).
    - **go2rtc** : négociation automatique (TCP par défaut pour la plupart des caméras IP).
  - **Validation manuelle** :
    - `_build_rtsp_url({rtsp_transport:'udp'})` → `rtsp://user:pass@host/path` (pas de fragment) ✅
    - `GET /api/stream/demo-cam-001/frame.jpeg` → JPEG **44 KB** (avant : décodage KO) ✅
    - `POST /api/cameras/test-connectivity` avec transport='udp' → `rtsp_url_validated=true` ✅
  - **Tests testing_agent iteration_25 : 18/18 backend pytest PASS. 0 issue. retest_needed=False.**


## Implemented (2026-07)
- ✅ **BUG FIX CRITIQUE — Fragment `#transport=tcp` stripé avant ffprobe + Logs traceurs (2.11.1 — 2026-07-22)**
  - **Cause racine** : `_build_rtsp_url` ajoute `#transport=tcp` à l'URL (nécessaire pour go2rtc). Cette URL passée telle quelle à ffprobe → ffprobe interprète `#transport=tcp` comme partie du path RTSP → **404 Stream Not Found** systématique sur toutes les caméras, y compris celles qui marchent parfaitement en manuel.
  - **Fix** : nouvelle fonction `_strip_go2rtc_fragments(url)` retire tout après le premier `#`. Appliquée dans `_ffprobe` juste avant l'exécution de la commande. Le fragment reste dans l'URL retournée à go2rtc (pour l'enregistrement du stream).
  - **Bug secondaire** : conflit `rtsp_url_used` passé en double kwarg dans `add(**rtsp_details, rtsp_url_used=...)` → crash. Filtré via `if k not in ("transport_used", "rtsp_url_used")`.
  - **Logs traceurs** ajoutés dans toute la chaîne — visibles dans `/var/log/supervisor/backend.err.log` :
    - `TEST_CONNECTIVITY start mode=... ip=... transport=... codec_pref=...`
    - `TEST_CONNECTIVITY ping HOST:PORT → ok/error`
    - `TRY_VARIANTS base=... pref=... transport=... → N variante(s) : [...]`
    - `VARIANT_TEST transport=TCP url=<masked>`
    - `FFPROBE URL=<masked> (transport=tcp)`
    - `FFPROBE CMD=[ffprobe, -rtsp_transport, tcp, ..., <masked>]`
    - `FFPROBE RC=0 stderr=...` (ou TIMEOUT/crash)
    - `FFPROBE OK → {resolution, fps, codec, ...}`
    - `VARIANT_TEST MATCH → <masked> (transport=tcp, codec=H264)`
    - `TEST_CONNECTIVITY end mode=... success=... rtsp_validated=... attempts=N`
  - **Passwords toujours masqués** dans logs et réponses HTTP (via `_mask_url_password`).
  - Test manuel confirmé : `rtsp://127.0.0.1:8554/cam_demo-cam-001` en mode='rtsp' → **validated=true, codec=H264, resolution=1280x720**.

- ✅ **NETTOYAGE ARCHITECTURE — Suppression code mort (2.11.1 — 2026-07-22)**
  - **Supprimé `/app/deploy/`** (836 KB) : ancienne architecture microservices (ai-engine, api, frontend, network-monitor, notification, recording, ffmpeg, monitoring, k8s, backup — services séparés Docker) remplacée par l'architecture actuelle à 2 services (`/app/backend` + `/app/frontend`) déployée via `/app/deploy-app/docker-compose.yml`.
  - **Supprimé 19 tests obsolètes** dans `/app/backend/tests/` (test_iter13-test_iter21, backend_test.py, test_real_system.py, test_hardware.py, test_network.py, test_notifications.py, test_permissions.py, test_reports_sprint.py, test_security_sprint.py, test_sprint2_realtime.py, test_sprint3_plugins_blacklist.py). **Conservés** : test_iter22_face_recognition.py + test_iter23_anpr_csv.py (reflètent le code actuel).
  - **Vérifié** : tous les modules backend (network, notifications, reports, security, realtime, hardware) sont importés par server.py, routers.py, ai_engine.py, auth.py. Aucun module orphelin.
  - **Architecture actuelle** (single source of truth) : 1 seul `streaming.py`, 1 seul `ai_engine.py`, 1 seul `recorder.py`, 1 seul `plugins.py`, 1 seul `plugin_config.py`, 1 seul `storage.py`, 1 seul `face_recognition_engine.py`. Aucune duplication.
  - **Tests testing_agent iteration_24 : 18/18 backend pytest PASS. 0 issue. retest_needed=False.**


## Implemented (2026-07)
- ✅ **IMPORT/EXPORT CSV ANPR — Watchlist globale + listes locales par caméra (2.11.0 — 2026-07-22)**
  - **Backend `plugin_config.py`** — nouveaux endpoints :
    - `POST /api/plugins/anpr/watchlist/import` : multipart csv_file, parse tolérant (BOM UTF-8 Excel, latin-1 fallback), header optionnel `plate,list_type,reason` (ou `plate` seul + query `default_list_type`), UPSERT par plaque (insertion + update rétroactif de `list_status` sur `db.plates`), max 2 Mo, refuse si aucun enregistrement valide.
    - `GET /api/plugins/anpr/watchlist/export` : CSV téléchargeable (`Content-Disposition: attachment`).
    - `POST /api/plugins/anpr/cameras/{id}/lists/import?target=whitelist|blacklist` : merge (union sans doublons) dans `anpr_config.whitelist_local` / `blacklist_local`, max 512 Ko.
    - `GET /api/plugins/anpr/cameras/{id}/lists/export?target=whitelist|blacklist` : CSV téléchargeable.
    - Helper `_parse_csv_plates(content, default_list_type)` : normalisation plaques uppercase + suppression espaces, tolérance colonnes (`plate|plaque|immatriculation`, `list_type|type`, `reason|motif`, valeurs FR `blanche/noire` → `white/black`), retour `(rows, errors)` avec collection d'erreurs par ligne.
  - **`auth.get_current_user`** : accepte désormais le token via query-param (`?token=…`) en fallback, pour permettre aux `<a href="…/export?token=X">` de télécharger les CSV sans header Authorization (les navigateurs ne peuvent pas injecter d'en-têtes sur un lien de téléchargement).
  - **Frontend `PluginPage.jsx`** :
    - Boutons `wl-export-btn` (export watchlist globale) + `wl-import-btn` (input file caché, upload multipart, toast de résultat) dans l'entête de la carte "Configuration par caméra" de `/plugins/anpr`.
    - Nouveau composant réutilisable `LocalListImportButtons` injecté dans les champs whitelist/blacklist du `AnprCameraDialog` : boutons `local-whitelist-{import,export}` + `local-blacklist-{import,export}`.
  - **Tests testing_agent iteration_23 : 20/20 backend pytest + Playwright OK. 0 issue, retest_needed=False.**


## Implemented (2026-07)
- ✅ **RECONNAISSANCE FACIALE — InsightFace + Upload photo + Analyse temps réel (2.10.0 — 2026-07-22)**
  - **Backend `face_recognition_engine.py`** : nouveau module 100% local basé sur `insightface` (ONNX buffalo_s, CPU). Fonctions clefs :
    - `availability()` : détecte si insightface est installé + retourne les notes d'installation pour l'UI.
    - `extract_embedding(image_bytes)` : ouvre l'image, détecte le/les visage(s), retourne l'embedding 512D + méta (bbox, det_score, gender, age). Refuse si 0 ou >1 visage.
    - `analyze_frame(bgr_frame, known, threshold)` : compare tous les visages détectés dans une frame BGR à la base de visages (cosine similarity).
    - `image_to_thumbnail(bytes, 120)` : produit un data-URL JPEG pour affichage UI (~10 kB).
  - **Endpoints** :
    - `GET /api/plugins/face_recognition/availability` : état lib + notes.
    - `POST /api/plugins/face_recognition/faces/{id}/photo` : upload multipart, appelle extract_embedding, persiste `encoding` + `thumbnail` + `photo_meta` + `photo_uploaded_at` dans `db.faces`. Validation : image only, max 8 Mo, exactement 1 visage détecté.
    - Le `GET /faces` ne retourne JAMAIS le champ `encoding` (perf + surface d'attaque réduite).
  - **Intégration `ai_engine._process_camera`** : si `settings.face_recognition_config.enabled=true` ET ≥1 visage avec encoding, la frame BGR est passée à `analyze_frame`. Les matches génèrent :
    - un événement `Visage · <name>` avec `face_id`, `face_name`, `watchlist`, `confidence` (similarité cosinus).
    - une alerte `critical` "Visage sur liste de surveillance" si `watchlist=True` et `alert_on_watchlist=True`.
    - Cooldown propre par (caméra, face_id).
  - **Frontend `FaceRecognitionSettings`** :
    - Nouvelle carte `face-availability` (verte/orange) qui expose l'état d'installation avec notes.
    - Bouton `face-upload-{id}` par visage → input file → POST photo → thumbnail rendu + affichage det_score + bbox.
    - Badge "SANS PHOTO" tant qu'aucun embedding n'existe.
    - Toggle `enabled` désactivé si la lib est absente.
  - **Modèle buffalo_s (~50 Mo)** téléchargé automatiquement au 1er upload de photo depuis les serveurs officiels InsightFace.
  - **requirements.txt** mis à jour via `pip freeze` : `insightface==1.0.1`, `onnxruntime==1.27.0`, `onnx==1.22.0`.
  - **Tests testing_agent iteration_22 : 11/11 backend pytest + Playwright E2E OK (upload Tom Hanks → embedding 512D, det_score=0.84). 0 issue.**


## Implemented (2026-07)
- ✅ **BUG FIX RTSP DEBUG — Debug + Validation obligatoire + Encodage RFC3986 (2.9.2 — 2026-07-22)**
  - **Debug RTSP en clair** : `POST /api/cameras/test-connectivity` renvoie désormais `rtsp_url_validated: bool`, `validated_url: URL_masquée`, `validated_transport`, et `debug_attempts: [{url_masked, transport, ok, codec, resolution, fps}]`. Chaque tentative montre l'URL EXACTE testée avec le password masqué (`admin:******@…`).
  - **Encodage RFC3986 UNE seule fois** : `_build_rtsp_url` détecte la présence de credentials via `host_part.split("/", 1)[0]` (au lieu de chercher `@` n'importe où dans l'URL) → ne réencode jamais. `Rlwt29#+jpf` → `Rlwt29%23%2Bjpf`, jamais `%2523%252Bjpf`. Vérifié : URL déjà avec creds encodés est préservée.
  - **Ordre de test explicite** : `_try_ffprobe_variants` teste dans l'ordre demandé — **H264 TCP → H265 TCP → H264 UDP → H265 UDP** — en cyclant chaque variante Reolink/Hik/Dahua. Si `preferred_codec="h264"` ou `"h265"`, seul ce codec est testé (mais sur les 2 transports).
  - **Nouvel helper `_mask_url_password`** : remplace le password (encodé ou non) par `******` pour affichage sûr.
  - **Validation OBLIGATOIRE** : `POST /api/cameras` avec `mode="rtsp"` + `allow_rtsp_override=false` refuse désormais avec **HTTP 400** si aucune variante ne répond à ffprobe (message : "URL RTSP invalide — aucune variante n'a répondu"). Auparavant la caméra était acceptée puis go2rtc tentait la connexion à la demande.
  - **Frontend `Cameras.jsx`** : nouveau bloc `[data-testid=rtsp-debug-panel]` (ouvert par défaut si validation échoue) qui liste les tentatives avec badge Transport, indicateur ✓/✗, URL masquée + codec/résolution détectés. Ligne verte `[data-testid=validated-url]` affichant l'URL retenue quand validated=true. Le bouton "Créer la caméra" refuse la soumission si `rtsp_url_validated=false` (toast d'erreur explicite).
  - **Tests testing_agent iteration_20 + retest iteration_21 : 15/15 backend pytest + Playwright OK — 0 issue.**


## Implemented (2026-07)
- ✅ **BUG FIX ONVIF Reolink — RTSP fallback constructeur + Override (2.9.1 — 2026-07-22)**
  - **Cause racine** : ONVIF Reolink retourne parfois `/h264Preview_01_main` alors que la caméra encode réellement en H.265 → ffprobe échoue → création caméra bloquée.
  - **Fallback constructeur intelligent** : nouvelle fonction `_rtsp_variants(base_url, preferred_codec)` génère la liste des URLs à tester dans l'ordre optimal :
    - **Reolink** : 6 combinaisons `/h26[45]Preview_0[12]_(main|sub)`.
    - **Hikvision** : 4 chaînes `/Streaming/Channels/{101,102,201,202}`.
    - **Dahua** : 4 canaux `/cam/realmonitor?channel={1,2}&subtype={0,1}`.
    - Le codec préféré (`h264` / `h265`) place les variantes correspondantes en tête.
  - **`_try_ffprobe_variants`** essaie chaque variante avec `ffprobe -rtsp_transport tcp|udp`, valide le codec réel, et retourne l'URL qui fonctionne + les métadonnées (résolution, fps, codec, bitrate).
  - **`_ffprobe(url, transport)`** respecte désormais `transport="tcp"|"udp"` (avant : TCP hardcodé). Ajoute la récupération du bitrate.
  - **`test-connectivity`** : le step `rtsp_open` en cas d'échec renvoie `allow_override: true` + `tried_variants: [...]`.
  - **`POST /api/cameras`** : nouveau champ `allow_rtsp_override` (défaut False). Si True + mode ONVIF + go2rtc échoue à ouvrir le flux, la caméra est créée en `status: "offline"` avec audit `camera_created_no_rtsp`. Résolution auto : `payload.rtsp_url`, `codec`, `resolution`, `fps` sont remplis depuis ffprobe des variantes.
  - **Frontend `Cameras.jsx`** : nouveau bouton conditionnel `cam-form-override` ("Créer malgré le test RTSP", jaune) qui apparaît uniquement si `mode="onvif"` + `onvif_auth=ok` + `rtsp_open=error`. Injecte `allow_rtsp_override=true` dans le POST.
  - **`GET /api/cameras/{id}/diagnostic`** : ajoute `profile_name` et `rtsp_url_masked` (mot de passe → `****`). Dialog frontend affiche Fabricant / Modèle / Profil / URL RTSP masquée.
  - **Tests testing_agent iteration_19 : 17/17 backend pytest + Playwright OK — 0 issue.**


## Implemented (2026-07)
- ✅ **SPRINT FINAL — Correction chaîne vidéo live + RTSP + Diagnostic (2.9.0 — 2026-07-22)**
  - **BLOCKER LIVE RÉSOLU** : go2rtc 1.9.8 ne transcode plus H.264 → MJPEG automatiquement sur `/api/stream.mjpeg` pour un producer H.264 pur (retour Content-Length: 0). Fix : `_mjpeg_stream(camera_id)` retourne **toujours** la variante `_sd` (qui contient explicitement `ffmpeg:...#video=mjpeg#width=640`). L'en-tête `content-type` (avec `boundary=frame`) est désormais transmis intact au navigateur (avant : le paramètre boundary était perdu). Résultat testé : Chrome/Firefox affichent le live des 2 caméras démo (mire + trafic).
  - **RTSP TCP/UDP par caméra** : nouveau champ `rtsp_transport` ("tcp"|"udp", défaut "tcp"). `_build_rtsp_url` ajoute `#transport=tcp|udp` au fragment go2rtc → passage TCP/UDP réel au niveau ffmpeg upstream.
  - **Codec préféré par caméra** : nouveau champ `preferred_codec` ("auto"|"h264"|"h265", défaut "auto") — visible dans le diagnostic + persisté en base.
  - **Nouveau endpoint diagnostic** : `GET /api/cameras/{id}/diagnostic` — agrège état go2rtc + camera_online + IA (dernière analyse, timings YOLO/ALPR, motion %, détections) + activité 24h (events + plates) + last_event + last_plate.
  - **Frontend `Cameras.jsx`** :
    - 2 nouveaux selects `rtsp-transport` (TCP recommandé / UDP) et `preferred-codec` (Auto / H.264 / H.265) dans le dialog de création/édition.
    - Nouveau bouton `diagnostic-btn` (icône radar) sur chaque ligne → ouvre `DiagnosticDialog` avec 4 sections (Flux vidéo · IA · Activité 24h · Dernières détections).
  - **Frontend `streaming.py` `frame_jpeg`** : essai HD → fallback SD si le stream HD ne délivre pas de JPEG (fiabilise les snapshots).
  - **Audit localhost côté frontend : 0 occurrence** (déjà propre — toutes les URLs passent par `process.env.REACT_APP_BACKEND_URL`).
  - **Tests testing agent (iteration_18) : 11/11 backend + Playwright OK, 0 issue.**


## Implemented (2026-07)
- ✅ **SPRINT P1.a — Uniformisation `<EventViewer>` (2.8.1 — 2026-07-22)**
  - Backend : nouveau `GET /api/recording-context?camera_id=X&at=ISO_TS` (helper factorisé `_lookup_recording_for`). `GET /api/events/{id}/recording` accepte désormais un `alert_id` en plus d'un event_id/plate_id (fallback dans l'ordre `events → plates → alerts`).
  - Frontend `EventViewer.jsx` : `playAround` détecte automatiquement le type d'item (via `id`) et bascule sur `/recording-context` si l'item ne provient pas de `db.events/plates` mais possède `camera_id + timestamp` (cas des alertes IA scénarios).
  - `Alerts.jsx` : chaque alerte devient interactive — le thumbnail est un bouton (`alert-thumb-btn`) + bouton œil (`alert-view-btn`) qui ouvrent l'EventViewer HD avec navigation ← → dans toutes les alertes.
  - `Dashboard.jsx` : la card "Alertes récentes" (6 dernières) est désormais cliquable — chaque `dash-alert-row` est un bouton qui ouvre l'EventViewer.
  - Résultat : les 4 surfaces d'événements (Events / ANPR / Alerts / Dashboard) partagent la même visionneuse HD + vidéo -5/+5s.

- ✅ **SPRINT P1.b — Audit zéro-sandbox (2.8.1 — 2026-07-22)**
  - Suppression des 3 clés i18n obsolètes `hw.simulated` / `rec.simulated` / `net.simulated` (FR + EN) qui n'étaient plus référencées.
  - `hardware.py` : docstring "Sandbox : CPU/RAM détectés réellement…" remplacée par "Détection RÉELLE : CPU/RAM via `psutil`, GPU via nvidia-smi/rocm-smi/OpenVINO. Aucun placeholder." Suppression du flag `simulated_gpu` de la réponse `/api/hardware/info` (toujours False).
  - `routers.py` : suppression des champs `"simulated": False` dans `/api/cameras/{id}/stream` et `/api/recordings/{id}/playback`.
  - `plugins.py` : suppression du duplicate `_health_access_control` (ancienne version "roadmap P2") — le health check remonte désormais l'état réel (nombre de contrôleurs déclarés).
  - Tests iteration_17 : **10/10 backend + Playwright OK, zéro issue.**


## Implemented (2026-07)
- ✅ **SPRINT P0 FINAL — Mise en production des plugins avec configuration (2.8.0 — 2026-07-22)**
  - **Nouveau module `plugin_config.py`** (backend) — endpoints CRUD par plugin :
    - **ANPR** : `GET/PUT /api/plugins/anpr/config` (pays, min/max plate px, ocr_confidence, cache, alertes) + `GET/PUT /api/plugins/anpr/cameras/{id}` (ROI polygone normalisé 0-1, min ≥3 pts, whitelist/blacklist locales, min_confidence, country_override) + `GET /api/plugins/anpr/cameras` (liste avec compteurs). ROI appliquée **temps réel** dans `ai_engine.py` (test point-in-polygon sur centre plaque).
    - **ByteTrack** : `GET/PUT /api/plugins/tracking/config` (track_thresh 0.1-0.9, match_thresh 0.5-0.95, track_buffer, min_box_area, id_persist_seconds). Intégration réelle via `supervision.ByteTrack` — un tracker par caméra, IDs persistants attachés à chaque événement + overlay Live.
    - **Face Recognition** : config (seuil, modèle, alertes) + CRUD `db.faces` (nom, watchlist, notes). Health check honnête (avertissement légal RGPD).
    - **Parking** : CRUD `db.parking_zones` (polygone dessiné sur snapshot de la caméra, capacité, camera_id enrichi).
    - **Access Control** : CRUD contrôleurs (gate/door/barrier/reader, IP:port, protocol http/wiegand/osdp/mqtt) + `POST /controllers/{id}/test` (ping TCP réel).
    - **Thermal / Radar / Drone** : CRUD manuel de capteurs matériels (aucune fabrication de données — l'admin déclare l'équipement).
    - Route helper `GET /api/plugins/_helpers/camera-snapshot/{id}` → JPEG frame live pour servir de fond aux éditeurs de polygone.
  - **Nouveau module `storage.py`** (backend) — gestion multi-disques :
    - `GET /api/storage/overview` → détection auto des partitions physiques (`psutil.disk_partitions`, filtre les fs virtuels), pools déclarés avec usage réel (`shutil.disk_usage` + comptage segments par pool).
    - CRUD pools : `POST/PUT/DELETE /api/storage/pools` — validation chemins interdits (/etc, /boot…), création `mkdir`, refus si non-accessible, blocage suppression si caméra assignée.
    - Assignation par caméra : `GET/PUT /api/storage/cameras/{id}/assignment` → `record_mode` (continuous/motion/ai/off) + `storage_pool_id` + `max_size_gb` + `profile_token` ONVIF.
  - **`recorder.py`** — enregistrement multi-cible : `_cam_target_dir(cam)` route vers pool assigné (fallback dossier principal), `_cam_all_dirs` indexe tous les répertoires (transition sans perte). `record_mode=motion` supprime les segments sans événement, `record_mode=ai` supprime les segments non IA. Purge propre.
  - **Nouveau composant `PolygonEditor.jsx`** — éditeur canvas réutilisable, coordonnées **normalisées 0-1** (indépendant résolution), clic pour ajouter un sommet, drag pour déplacer, annuler dernier, tout effacer, minimum configurable (défaut 3).
  - **`PluginPage.jsx`** entièrement enrichi — 7 composants de config production :
    - `AnprSettings` + `AnprCameraDialog` (config globale + dialog par caméra avec bouton "Dessiner la ROI" ouvrant PolygonEditor sur snapshot live)
    - `TrackingSettings` (formulaire ByteTrack complet avec bornes)
    - `FaceRecognitionSettings` (config + CRUD visages + avertissement RGPD)
    - `ParkingSettings` + `ParkingZoneDialog` (création de zone dessinée sur snapshot caméra)
    - `AccessControlSettings` + `AcDialog` (CRUD contrôleurs + test TCP)
    - `SensorSettings` + `SensorDialog` réutilisable (thermal/radar/drone)
  - **`Settings.jsx`** — nouvelle carte **Stockage multi-disques** (admin only) : liste des 9+ partitions détectées avec barre d'usage colorée (vert/orange/rouge), bouton "Utiliser" qui pré-remplit le formulaire, table des pools déclarés avec toggle activer/désactiver + quota édité inline + volume enregistrements réel, zone d'ajout manuel (nom + chemin + quota).
  - **`Cameras.jsx`** — dialog de création/édition étend le formulaire avec un bloc **"Configuration d'enregistrement"** : select Mode (continuous/motion/ai/off), select Canal ONVIF (peuplé après test connectivité), select Disque cible (pools actifs avec Go libres visibles), champ Quota max. À la sauvegarde, appel additionnel `PUT /api/storage/cameras/{id}/assignment`.
  - **`plugins.py`** — health checks refondus (aucune donnée fictive) :
    - `_health_tracking` : vérifie `supervision`/`ultralytics` installés + config ByteTrack en base + événements tracés sur 24 h.
    - `_health_anpr_v2` : ajoute checks config globale + nb caméras avec ROI.
    - `_health_parking` : `configured` si zones>0.
    - `_health_access_control` : `configured` si contrôleurs>0.
    - `_health_hardware_sensor` : `configured` si l'admin a déclaré au moins un capteur (thermal/radar/drone).
  - **Tests testing agent (iteration_16) : 25/25 backend pytest + Playwright frontend intégral OK. 0 issue.**


## Implemented (2026-07)
- ✅ **SPRINT P2.a — Rétention & stockage vidéo (2.7.0 — 2026-07-22)**
  - **Backend** : `_apply_retention()` réécrit avec **2 passes** — (1) purge par âge (segments > N jours), puis (2) purge par quota disque (tant que `free_gb < min_free_gb` **OU** `used_pct > max_disk_pct`, supprimer le plus ancien segment). Rapport détaillé retourné : `{deleted_by_age, deleted_by_quota, freed_gb}`.
  - Config runtime persistée dans `settings.retention` : `retention_days` (1-365) · `min_free_gb` (0.5-10000) · `max_disk_pct` (10-99). Chargée à chaque cycle du recorder — édition à chaud sans redémarrage.
  - Nouveaux endpoints (admin) :
    - `GET /api/settings/retention` → snapshot complet : config + `disk` (total_gb, used_gb, free_gb, used_pct) + `recordings` (count, size_gb, oldest, newest).
    - `PUT /api/settings/retention` → mise à jour des seuils.
    - `POST /api/settings/retention/run` → **purge manuelle immédiate**, retourne le rapport.
  - **Frontend** : nouvelle section "Rétention & stockage vidéo" dans `/settings` (admin uniquement) — 4 cartes chiffrées (total/utilisé/libre/occupation avec code couleur), **barre de progression** disque avec marqueur du seuil `max_disk_pct`, 3 métriques enregistrements (nombre / volume / plus ancien), 3 champs seuils éditables, bouton **Enregistrer les seuils** + bouton **Purger maintenant** (rouge, avec confirmation).
  - Auto-refresh 30 s de l'état pour visualiser en temps réel l'impact des purges.

## Implemented (2026-07)
- ✅ **SPRINT P0.4 — Pages dédiées par plugin (2.6.3 — 2026-07-22)**
  - **Backend** — `PLUGIN_CATALOG` déclare désormais un champ `route` par plugin. `seed_plugins` met à jour les manifestes (route/description/version) sans écraser `enabled`. Nouveau endpoint `GET/PUT /api/settings/mqtt` (broker host/port/user/pass/prefix/tls).
  - **Frontend** — nouvelle page générique `/plugins/:pluginId` (composant `PluginPage.jsx`) qui affiche pour chaque plugin :
    - En-tête : nom, catégorie, version, badge de statut réel.
    - Checklist santé + métriques (Total / 24 h / Dernier événement).
    - Section spécifique :
      - **Détection IA (YOLO)** → formulaire complet éditable (intervalle 0.2–60 s, seuil confiance 0.1–0.95, taille min plaque, cache plaques, cible cpu/cuda/auto) branché sur `PUT /api/ai/config`. Application à chaud.
      - **MQTT** → formulaire complet (host, port, user, pass, préfixe topic, TLS) branché sur `PUT /api/settings/mqtt`. Bouton **Tester la connexion (TCP)** vers le broker.
      - Autres plugins (tracking, face_recognition, parking, thermal, radar, drone, access_control) → note « Fonctionnalité en développement » **honnête**, avec la checklist des prérequis réels et la roadmap explicite (P2/P3, matériel requis, etc.). Aucun bouton fictif.
  - **Sidebar dynamique** — nouvelle section **Extensions** qui liste automatiquement les plugins activés + non-erreur, avec icône dédiée et pastille de statut (vert=OK, orange=à configurer). Route configurée par le manifeste plugin. Le plugin ANPR conserve son entrée principale `/anpr` (pas de doublon).
  - **App.js** : nouvelle route `/plugins/:pluginId`.
  - Vérifié en preview : sidebar affiche `Détection IA (YOLO)` (vert), `Tracking (ByteTrack)` (orange), `Gestion Parking` (orange). Page Détection IA charge la config live et permet l'édition à chaud. MQTT config persistée en base et lue au refresh de la page Plugins → passe l'item "Broker MQTT configuré" à ✓.

## Implemented (2026-07)
- ✅ **SPRINT P0.3 — État réel des plugins (2.6.2 — 2026-07-22)**
  - Refonte `/app/backend/plugins.py` : ajout d'un `health_check()` par plugin qui **teste réellement** les dépendances et la configuration (aucune donnée fictive).
  - Nouveaux endpoints : `GET /api/plugins` renvoie désormais `{...manifest, enabled, status, health: {checks:[{name, ok, detail}], loaded, configured, healthy, events_total, events_24h, last_event_at, warning?}}` · `GET /api/plugins/{id}/health` pour un check à la demande.
  - **4 statuts globaux réels** : `ok` (vert) · `error` (rouge — deps manquantes) · `not_configured` (orange — deps OK mais config absente) · `disabled` (gris — désactivé volontairement).
  - Health checks implémentés par plugin :
    - `anpr` : import `fast_alpr` + nb caméras IA + total plaques + événements 24 h + dernier événement
    - `ai_detection` : `ultralytics` + `cv2` (versions détectées) + cible `torch.cuda`/`cpu` + caméras IA online + événements
    - `tracking` : `supervision` / `bytetracker` (version détectée) + persistance IDs (roadmap)
    - `face_recognition` : `face_recognition` / `deepface` / `insightface` + base de visages
    - `parking` : nb zones de stationnement
    - `thermal` / `radar` / `drone` : "Aucun matériel détecté" (jamais de fake)
    - `mqtt` : `paho.mqtt` + broker configuré
    - `access_control` : contrôleurs enregistrés
  - Refonte `/app/frontend/src/pages/Plugins.jsx` : bordure de carte colorée selon le statut, checklist `✓` / `✗` par item avec version des libs affichée en mono, warning à droite du statut, grille métriques `Total / 24 h / Dernier événement` pour les plugins actifs qui génèrent des événements, bouton `Rafraîchir` + rafraîchissement auto toutes les 20 s.
  - Vérifié en preview : ANPR OK (163 plaques, 83/24h), AI Detection OK (1100 events, 592/24h), Tracking `Non configuré` (supervision présent mais IDs non persistés), Face Recognition `Erreur` (aucune lib installée), Parking `Non configuré` (0 zones), Thermal `Erreur` (aucun matériel), autres `Désactivé`.

## Implemented (2026-07)
- ✅ **SPRINT P0.2 — Overlay IA temps réel en Live View (2.6.1 — 2026-07-21)**
  - **Backend** : à chaque cycle IA, les détections sont diffusées via WebSocket (`broadcast_ai_detections` dans `realtime.py`) avec le message `{type: "ai_detections", data: {camera_id, site_id, timestamp, boxes: [{cls, label, confidence, vehicle_color, bbox_norm}], counts: {Personne: 2, Voiture: 1}, motion_pct}}`. Les bboxes sont **normalisées 0-1** côté serveur pour que le client puisse les scaler à sa taille d'affichage sans connaître la résolution IA.
  - **Frontend** : `AppContext` maintient `aiDetections` (par `camera_id`) alimenté par le WebSocket. `LiveView.jsx` dessine un `<canvas>` transparent en overlay au-dessus de chaque `<img>` MJPEG.
  - **Palette IA** : couleur distincte par classe — Personne=vert, Voiture=bleu, Camion/Bus=orange, Moto=rose, Vélo=cyan, Animal/Chien/Chat=violet, inconnu=rouge.
  - **Labels** : `<classe> <confiance%> · <couleur véhicule>` (préparé pour ByteTrack ID `#N`).
  - **Compteur d'objets** par caméra en haut à droite : ex. `2 Personne · 1 Voiture`.
  - **Toggle Overlay IA** dans le bandeau Live (persisté en `localStorage`, `Eye` / `EyeOff`).
  - N'affiche l'overlay que si `cam.detect_enabled === true`.
  - Latence : bboxes rafraîchies à la même cadence que le cycle IA (par défaut 2 s, réglable via `PUT /api/ai/config`).

## Implemented (2026-07)
- ✅ **SPRINT P0.1 — Événements interactifs & visionneuse professionnelle (2.6.0 — 2026-07-21)**
  - **Composant `<EventViewer>` réutilisable** (`/app/frontend/src/components/EventViewer.jsx`) : modal plein écran overlay noir, image centrée, panneau latéral métadonnées, footer clavier.
  - **Miniatures cliquables** dans les pages Événements IA et ANPR/Plaques → ouvrent la visionneuse.
  - **Navigation** : boutons prev/next latéraux + flèches gauche/droite clavier, compteur `N / total`.
  - **Zoom** : molette souris avec point pivot au curseur (jusqu'à 6x), boutons `-` / `+` / `reset`.
  - **Pan** : glisser-déposer quand zoom > 1x (curseur `grab` / `grabbing`).
  - **Fermeture** : bouton X, touche Échap.
  - **Actions** : `Télécharger l'image` (a[download]), `Copier dans presse-papier` (`ClipboardItem`).
  - **Panneau métadonnées** : caméra, site, horodatage, plugin (Détection / ANPR fast-alpr / …), type d'événement, confiance %, plaque, statut liste blanche/noire, couleur véhicule, marque/modèle/type, ByteTrack ID (si présent), motion_pct.
  - **Bouton « Lire la vidéo autour de cet événement »** → nouvel endpoint `GET /api/events/{id}/recording` qui trouve le segment MP4 couvrant le timestamp et renvoie `offset_sec = event_ts − segment_start − 5s`. Bascule automatique image → `<video>` avec `currentTime=offset` et lecture auto. HTTP 404 clair si aucun enregistrement ne couvre l'événement.
  - Fallback gracieux : sur plaques ANPR sans `thumbnail` explicite, utilise `vehicle_crop` puis `plate_crop`.

## Implemented (2026-07)
- ✅ **SPRINT P1 — Optimisation IA & workers indépendants (2.5.0 — 2026-07-21)**
  - **Workers IA indépendants** : la boucle `ai_loop` traite désormais les caméras en parallèle via `asyncio.gather`. Une caméra lente ne bloque plus les autres.
  - **YOLO / ALPR séparés** : YOLO est exécuté d'abord (~50 ms/frame en CPU ARM64). ALPR n'est appelé QUE si un véhicule est détecté → gain énorme quand la scène est vide (`alpr=0ms` observé).
  - **Cache plaques (TTL configurable, défaut 8 s)** : `(camera_id, plate)` → expiry. Évite l'OCR répété sur la même voiture qui traverse la scène.
  - **Filtre taille minimale de plaque** (`min_plate_px`, défaut 24 px) : les crops trop petits sont rejetés avant OCR → évite les faux positifs et l'OCR inutile.
  - **Config IA runtime** : `GET /api/ai/config` + `PUT /api/ai/config` (admin) — `interval_seconds` (0.2-60 s), `confidence` (0.1-0.95), `min_plate_px` (8-200), `plate_cache_seconds` (0-300), `device` (cpu / cuda / auto). Persistance MongoDB, appliqué à chaud sans redémarrage.
  - **GPU-ready** : détection automatique `torch.cuda.is_available()` avec fallback CPU. YOLO utilise `device=cuda:0` si disponible. `device_effective` exposé dans `/ai/config`.
  - **Timings détaillés par étape** : chaque analyse retourne `decode_ms / motion_ms / yolo_ms / alpr_ms / total_ms` — visibles dans les logs et le mode debug.
  - **Mode Debug ALPR (#4)** :
    - Backend : `GET /api/ai/debug/{camera_id}` retourne le dernier snapshot d'analyse (image analysée base64, résolution, device, timings, véhicules détectés avec bbox/couleur, tentatives OCR avec statut kept/skipped/cache + taille, motion_pct).
    - Frontend : bouton `Debug IA` (cerveau bleu) sur chaque caméra `detect_enabled=true` → dialog complet.
  - Log IA amélioré : `IA · <cam> : N détection(s) [X] · mouvement=Y% · N plaque(s) · yolo=Xms alpr=Yms` à chaque cycle.

## Implemented (2026-07)
- ✅ **SPRINT P0 — Stabilisation caméra & audit sandbox (2.4.0 — 2026-07-21)**
  - **Root cause du ping-pong Connect/Disconnect identifiée et fixée** : `_probe_status_once` appelait `register_camera_stream` toutes les 30 s → DELETE + PUT sur le flux go2rtc → tous les consommateurs (browser MJPEG, recorder ffmpeg, IA) étaient déconnectés en boucle. Corrigé : la sonde périodique vérifie désormais `/api/streams` (READ-ONLY) et ne (ré-)enregistre que si le flux a réellement disparu.
  - **Un seul décodage par caméra** : suppression du producteur redondant `ffmpeg:<name>#video=mjpeg` dans le flux principal (`register_camera_stream` + `go2rtc.yaml` démos). Chaque flux a désormais un **producteur unique** ; les consommateurs MJPEG (Live, snapshot, IA) utilisent la conversion à la demande de go2rtc → pipeline partagé Live/Recording/IA/ALPR.
  - **Nettoyage automatique des flux temporaires** `probe_*` au démarrage du backend (résidus des tests de connectivité qui étaient persistés dans `go2rtc.yaml`).
  - **Audit sandbox #11** — suppression de tous les éléments de démonstration/fake :
    - `POST /api/anpr/detect` (endpoint qui injectait des plaques fictives) → supprimé
    - Bouton « Simuler une détection » (ANPR) → retiré de l'UI
    - Bouton « Simuler une alerte critique » (Alerts) → retiré (générait un alert `Intrusion détectée — zone périmètre` fictif)
    - Badges UI trompeurs `hw.simulated` (Hardware) et `net.simulated` (Network) → remplacés par état réel (« Aucun GPU détecté » quand la liste est vide) ou retirés
    - Commentaires backend « Sandbox : flux/lecture simulés » sur `/recordings/timeline` corrigés — les enregistrements sont 100 % réels (MP4 sur disque)
  - Vérifié via `ps -ef` + `/api/streams` : 1 seul ffmpeg par flux, 0 producer doublon, aucun churn pendant 65 s d'observation.


## Original problem statement
Plateforme professionnelle de vidéosurveillance (concurrent de Milestone, Genetec, Nx Witness, UniFi Protect). Cible: collectivités, mairies, entreprises, industries, sites sensibles, parkings. 100% web, responsive, multi-sites, IA (YOLO/ANPR), tracking, alertes, RBAC, monitoring, etc.

## Stack reality (this environment)
React + FastAPI + MongoDB (Kubernetes single backend/frontend). Note: the requested multi-container Docker (Vue/PostgreSQL/Celery/GPU-YOLO/RTSP ingestion) is not supported in this sandbox; the platform is built modularly on the supported stack and maps to that production architecture later.

## User personas
- Administrateur: gestion complète (utilisateurs, sites, caméras, suppression)
- Technicien: gestion sites/caméras/listes
- Client: consultation, PTZ, acquittement alertes
- Lecture seule / Invité: consultation restreinte

## Core requirements (static)
1. Auth JWT + RBAC (5 rôles) + 2FA TOTP
2. Multi-sites
3. Caméras (RTSP/ONVIF config, test connexion, snapshot, PTZ)
4. Live View mur vidéo (1→64)
5. Dashboard pro (stats système, graphiques)
6. ANPR + recherche véhicule + listes blanche/noire + IA vision
7. Alertes + Audit + Carte OSM
8. Bilingue FR/EN, thème clair/sombre

## Implemented (2026-07)
- ✅ **CAMERA MANAGEMENT PRO (2.3.0 — 2026-07-21)**
  - **Mode ONVIF** : plus jamais d'URL RTSP demandée manuellement. Workflow complet : IP + port + user + pass → `GetProfiles` → `GetStreamUri` → **choix de profil (Main / Sub / 3ᵉ)** → enregistrement auto go2rtc → caméra créée. RTSP totalement transparent.
  - **Mode RTSP manuel avec Assistant** : 25 fabricants supportés (Reolink, Hikvision, Dahua, Axis, Hanwha, Uniview, Bosch, Vivotek, TP-Link VIGI, UniFi Protect, Milesight, Provision-ISR, Avigilon, Tiandy, Hik-OEM, Annke, Ezviz, Amcrest, Foscam, ACTi, GeoVision, Panasonic, Sony, Pelco, Générique). Choix fabricant → modèle → flux (main/sub/main_h264/sub_h265/…) → canal → **URL générée automatiquement**. Champ RTSP toujours modifiable manuellement.
  - **Bibliothèque extensible** `/app/backend/camera_profiles.json` : ajouter un nouveau fabricant ne nécessite aucune modification de code (recharge à chaque requête `GET /api/cameras/brands`).
  - **Encodage automatique des credentials** : `# @ + : espace /` sont automatiquement URL-encodés (RFC 3986) à la fois par `_build_rtsp_url` (côté serveur) et par `POST /api/cameras/generate-rtsp-url`. L'utilisateur peut coller n'importe quel mot de passe.
  - **Bouton « Détecter automatiquement »** (`POST /api/cameras/auto-detect`) : un clic → fabricant, modèle, firmware, PTZ, profils, URI RTSP, résolution effective (ffprobe). TCP pré-check 3 s pour fail-fast.
  - **Test de connexion 7 étapes** avec statut ✅/⚠️/❌ par étape : `ping` · `onvif_port` · `onvif_auth` · `rtsp_port` · `rtsp_open` · `go2rtc` · `preview` + **aperçu vidéo JPEG** live dans le dialog.
  - **Édition complète** : modif de nom, IP, protocole, ports, credentials, profil vidéo, URL RTSP, résolution, fps, bitrate, paramètres IA, paramètres d'enregistrement. `PUT /api/cameras/{id}` recharge automatiquement go2rtc sans supprimer la caméra. Password laissé vide = conserve l'ancien.
  - **Priorité** : ONVIF auto → RTSP généré via assistant → saisie manuelle en dernier recours (comme demandé).
  - Ordre d'inclusion des routers corrigé (`stream_router` avant `api_router`) pour que `/api/cameras/brands`, `/generate-rtsp-url`, `/auto-detect` ne soient plus interceptés par `/api/cameras/{id}`.

## Implemented (2026-07)
- ✅ **PRODUCTION READINESS #2 — Modes RTSP/ONVIF séparés (2.2.0 — 2026-07-21)**
  - **CameraInput** gagne un champ `mode` (`rtsp` | `onvif`). Frontend : toggle « Mode RTSP » / « Mode ONVIF » en haut du dialog, avec bascule des champs affichés.
  - **Mode RTSP** : valide seulement Port RTSP + URL RTSP (ffprobe).
  - **Mode ONVIF** : valide seulement Port ONVIF + identifiants ONVIF. L'URL RTSP est **auto-découverte** via `GetStreamUri` sur le premier profil, puis registrée dans go2rtc. Aucune saisie RTSP requise.
  - `POST /api/cameras/test-connectivity` désormais mode-aware.
  - `POST /api/cameras` et `PUT /api/cameras/{id}` supportent les deux modes ; TCP pré-check ONVIF (fail-fast 3 s) pour éviter les timeouts SOAP sur hôtes injoignables.
  - **Édition de caméra** : bouton crayon dans la liste, dialog partagé qui accepte modification de nom, IP, protocole, ports, credentials, URL RTSP, enregistrement, IA. `PUT` recharge automatiquement la config go2rtc.
  - **Live vidéo stable** : `<img>` MJPEG (via go2rtc) avec reconnexion automatique (backoff 2.5 s) au lieu de tomber sur « No Signal ». Le RTSP brut n'est JAMAIS exposé au frontend — seulement `live.mjpeg`/`frame.jpeg` du backend proxy.
  - **IA logs clairs** : chaque cycle et chaque caméra loggue `IA · <name> (<id>) : N détection(s) [Personne:0.53, ...] · mouvement=X% · N plaque(s)` dans `backend.err.log`.
  - **Dépendances propres** : `litellm` (URL customer-assets) et `emergentintegrations` retirés de `requirements.txt`. Endpoint `/api/ai/analyze-plate` réécrit avec le pipeline **local** (`fast-alpr` + YOLO) — zéro cloud, zéro clé LLM. Dockerfile backend nettoyé (plus de `--extra-index-url`). `docker compose up --build` fonctionne depuis un clone propre.

## Implemented (2026-06)
- ✅ **PIPELINE CAMÉRA RÉEL / PRODUCTION (2.1.0 — 2026-07-20)** : (1) enregistrement auto dans go2rtc après POST/PUT `/api/cameras` + vérification `/api/streams` avant retour succès ; rollback DB (HTTP 400) si go2rtc refuse. (2) `CameraInput` ajoute `rtsp_port` (554) et `onvif_port` (80) configurables. (3) `POST /api/cameras/test-connectivity` : TCP ping IP:rtsp_port + IP:onvif_port + ffprobe RTSP (résolution/fps/codec). Sauvegarde bloquée côté UI si test KO. (4) `camera_status_loop` (30 s) : statut Online/Offline reflète l'état RÉEL du flux (frame JPEG lisible). (5) recorder : `stop_all_recorders()` au shutdown + `sweep_orphan_recorders()` au démarrage. (6) Login : plus de pré-remplissage ni bloc identifiants démo. (7) Branding Emergent supprimé (title = `MG-VMS`, meta description, script emergent-main.js retiré). Backend pytest 9/9 + frontend Playwright 100% (itération 15).
- ✅ PERMISSIONS GRANULAIRES (2.0.0) : par-utilisateur, gérées **uniquement par admin** — view_live, view_recordings, read_plates, stream_hd (HD/SD), ptz_control, export_files. `require_permission` appliqué sur les endpoints concernés ; éditeur de permissions dans `/users` + masquage nav. Tests 22/22 backend + frontend 100% (itération 11).
- ✅ RESSOURCES MATÉRIELLES CPU/GPU — Phase 1 (1.9.0) : module `/hardware` 4 onglets — détection réelle CPU/RAM + **4 GPU simulés** + accélérateurs ; allocation par fonction (10) ; profils (Éco/Équilibré/Perf/Ultra/Custom) + priorités par moteur + auto-optimize ; **monitoring temps réel** (poll 2s, CPU/GPU/VRAM/temp/conso/IA/FFmpeg). Endpoints info/config/monitor/profile (writes admin). Tests 17/17 backend + frontend 100% (itération 10). Reste Phase 2 (auto-optimisation + historique) & Phase 3 (pools GPU, benchmarks, /deploy).
- ✅ RAPPORTS + ANPR ENRICHI + POLL RÉSEAU (1.8.0) : module **Rapports** `/reports` (CSV/Excel/PDF × plaques/events/alertes/équipements, filtres date+site) ; alerte liste noire **enrichie** (photo véhicule + lien caméra Discord/Telegram, deep-link `/recordings?camera=`) ; **poll réseau périodique** serveur (30s) avec alertes temps réel + auto-refresh UI. Tests 25/25 backend + frontend 100% (itération 9).
- ✅ EXPORT DE SÉQUENCE (1.7.0) : depuis la timeline `/recordings`, sélection de plage (glisser + champs) → **ZIP réel** téléchargeable (manifeste + vignettes) ; **MP4 mis en file** (généré en prod FFmpeg). Endpoints export/list/download + endpoint prod `POST /export` (concat FFmpeg) dans `/deploy/recording`. Testé curl + screenshot.
- ✅ SUPERVISION RÉSEAU (1.6.0) : module `/network` — inventaire (switch/routeur/NAS/UPS/serveur/NVR), **topologie** SVG, fiche équipement, ICMP/SNMP **simulé** (ping/poll) + alertes auto (hors-ligne / UPS batterie). Artefacts prod `/deploy/network-monitor` (pysnmp+ICMP) + table `equipment`. Tests 12/12 backend + frontend 100% (itération 8).
- ✅ CŒUR VIDÉO P0 + TIMELINE (1.5.0) : artefacts prod `/deploy/ai-engine` (YOLOv11+ByteTrack `worker.py`, ANPR réel `anpr.py`), `/deploy/recording/recorder.py` (MP4+MinIO+timeline+rétention), cœur ffmpeg complété (stream_manager/onvif/go2rtc) — NON exécutables ici. Sandbox : page **Enregistrements & Timeline** (`/recordings`) + endpoints `GET /api/recordings/timeline` & `/playback`, seed idempotent. Testé curl + screenshot.
- ✅ SPRINT 3 PLUGINS + ANPR LISTE NOIRE AUTO + ARTEFACTS /deploy : socle de plugins (10 modules, activation dynamique, page admin), alerte auto sur plaque liste noire (POST /api/anpr/detect + analyze-plate → alerte critique + WebSocket + notifications), rate-limit login assoupli (30/min). Artefacts prod /deploy (docker-compose micro-services, Dockerfiles, schéma PostgreSQL+SQLAlchemy+Alembic, Prometheus/Grafana/Loki, K8s) — NON exécutables ici. Tests 14/14 backend + frontend 100% (itération 7).
- ✅ SPRINT 2 TEMPS RÉEL (P1) : WebSocket /api/ws (auth token + cloisonnement site) push métriques (5s) + alertes live ; métriques système réelles (psutil) ; pagination serveur (offset/limit + X-Total-Count, réponses restent des listes) + UI « Charger plus » (ANPR, Audit) ; indicateur LIVE + toasts temps réel. Tests 42/42 backend + frontend 100% (itération 6).
- ✅ SPRINT 1 SÉCURITÉ (P1) : anti brute-force (lockout 15min/5 essais), rate-limiting auth, reset password (jeton TTL usage unique), en-têtes OWASP, CORS restreint, cloisonnement par site (allowed_sites/site_scope), refresh token câblé front, affectation des sites par utilisateur. Tests 17/17 backend + frontend OK (itération 5).
- ✅ Notifications/Intégrations: page de config SMTP + Discord + Telegram (saisie admin), secrets chiffrés (Fernet) + masqués en lecture, test d'envoi par canal, activation/désactivation par canal, envoi auto sur alertes critiques (BackgroundTasks). POST /api/alerts déclenche la dispatch. Tests: backend 20/20, frontend 14/14.
- ✅ JWT Bearer auth, RBAC require_role, 2FA TOTP (setup/verify/disable), admin+3 demo users seeded
- ✅ Sites CRUD, Cameras CRUD + test/snapshot/PTZ endpoints (simulated)
- ✅ Live View video wall with 1/4/9/16/25/36/49/64 layouts
- ✅ Dashboard KPIs + 24h activity area chart + detection pie + system health
- ✅ ANPR plate search w/ filters, CSV export, watchlist, AI image analysis (OpenAI gpt-5.4 via emergentintegrations)
- ✅ Vehicle search (plate/color/make/type/site/direction/date)
- ✅ Alerts center (ack), Audit log, OpenStreetMap map view
- ✅ Users management, Settings (theme/lang/2FA)
- ✅ Bilingual FR/EN, dark/light themes — control-room design
- Tested: backend 30/30, frontend flows 100%

## Backlog (prioritized)
- P1: Real RTSP/WebRTC streaming, ONVIF auto-discovery, real YOLOv11 detection + ByteTrack/DeepSort tracking
- P1: Recordings timeline + MP4/AVI/JPEG/ZIP export, storage backends (NAS/SMB/NFS/S3/MinIO)
- P2: Alert channels (Email/Telegram/Discord/Webhook/MQTT/SMS), PDF/Excel reports
- P2: Floor plans with camera placement, Prometheus/Grafana monitoring, backup/restore
- P3: Facial recognition, thermal, drone, plugins/marketplace, mobile apps

## MOCKED / SIMULATED
- Camera live streams (placeholder images), test-connection & snapshot results, system CPU/RAM metrics, seeded demo events/plates/alerts. AI ANPR uses a real LLM call.

## Next tasks
- Wire real video ingestion pipeline (separate worker/ffmpeg service in production compose)
- Add alert notification channels + reports module

## Session 2026-06 (fork) — Stack de production /deploy complétée
Demande utilisateur : (1) architecture propre complète dans /deploy, (2) frontend Vue 3 + Vite + TS pour /deploy, sans toucher au code sandbox, suppression des références "emergent".
- ✅ /deploy/api/ : API FastAPI complète — SQLAlchemy 2.0 async (psycopg3) + Alembic (migrations auto au boot) + PostgreSQL + Redis + Celery (worker+beat). 17 modules : auth (JWT httpOnly + refresh + brute-force + reset), users (matrice permissions), organizations, sites, cameras (ONVIF/PTZ délégués au service ffmpeg), streams (WebRTC/HLS go2rtc, dégradation SD si !stream_hd), recordings (timeline), playback (URLs signées S3/MinIO), events (WS temps réel via Redis pub/sub), ai (règles + recherche plaques + analytics), notifications, maps, storage, monitoring (stats + métriques Prometheus), audit, settings, health. Versions verrouillées testées en venv propre (50 routes importées OK).
- ✅ /deploy/notification/ : service consommant la file Redis mgvms:notifications → Email SMTP / Discord / Telegram / Webhook.
- ✅ /deploy/frontend/ : Vue 3.5 + Vite 6 + TypeScript + Pinia + vue-router. 8 vues (Login, Dashboard temps réel WS, Caméras CRUD, Direct+PTZ+badge SD, Enregistrements+export, Événements+ack, Utilisateurs avec matrice de permissions, Paramètres/canaux notif). Build + vue-tsc : 0 erreur. Dockerfile multi-étapes Node20→Nginx.
- ✅ Zéro référence "emergent" dans /deploy et /deploy-app (EMERGENT_LLM_KEY supprimée). NB : dans /deploy-app, l'analyse LLM ANPR de la démo ne fonctionnera pas sans clé (feature mock).
- ✅ Nettoyage : /deploy/db/ supprimé (doublon) — source de vérité = api/app/models.py + api/alembic. Compose corrigé (commande celery app.tasks.celery_app, plus de schema.sql initdb). README /deploy réécrit (Windows/WSL2 + Linux, choix techniques justifiés).
- ✅ Sandbox intacte (env pip restauré après incident d'auto-install, backend+frontend vérifiés OK).
- NB sandbox : le code démo (/app/backend, /app/frontend) utilise toujours la clé LLM pour l'ANPR mock — inchangé volontairement.

## Prochaines étapes proposées
- Tester la stack /deploy chez l'utilisateur (docker compose up) et corriger les retours
- Enrichir le frontend Vue (recherche LAPI, timeline enregistrements, cartes/plans)
- Optimisation auto ressources matérielles Phase 2 (sandbox)
- ✅ Frontend Vue /deploy : vue « Recherche LAPI » ajoutée (filtres plaque/site/liste/dates, photos, badges liste noire/blanche, garde route+nav via permission read_anpr). Build + vue-tsc OK.
- ✅ Frontend Vue /deploy : timeline 24h des enregistrements dans RecordingsView (sélecteur caméra + date, segments positionnés, hover détail, clic → URL de lecture signée). Build + vue-tsc OK.
- ✅ Bugfix VPS utilisateur (erreur ajv au build Docker frontend) : cause = ancienne copie du repo avec Dockerfile npm. Dockerfile actuel (Yarn + yarn.lock) durci avec --frozen-lockfile ; build à froid reproduit et validé par testing_agent (iteration_12, 100%). Section Dépannage ajoutée à deploy-app/README.md.

## Session 2026-07 — Passage au 100% RÉEL (plus aucune donnée factice)
- ✅ Vidéo live réelle : go2rtc (binaire persistant /app/go2rtc/go2rtc, supervisor) + proxys authentifiés /api/stream/{id}/live.mjpeg & frame.jpeg (?token=). 2 caméras démo à flux H.264 réels (mire + scène de rue). Test caméra = frame réelle + ffprobe (résolution/fps/codec). Découverte ONVIF réelle (WS-Discovery + onvif-zeep) + UI dans Caméras.
- ✅ Purge de toutes les données factices (seed.py: flag purged_fake_data_v1). Équipements réseau: ping ICMP réel (icmplib). Matériel: psutil réel, GPU réels uniquement (nvidia-smi). Dashboard timeseries: agrégations Mongo réelles.
- ✅ Enregistrement réel : recorder.py (FFmpeg segments 120s → /data/recordings, RECORDINGS_DIR env), indexation Mongo, rétention 7j, garde-fou espace disque (2 Go min), relecture <video> réelle (/api/recordings/{id}/media?token=), export ZIP (vrais MP4) + MP4 (concat FFmpeg).
- ✅ IA réelle : ai_engine.py — YOLO yolo11n CPU (événements Personne/Voiture/... avec vignettes base64, couleur réelle des véhicules par analyse HSV), détection de mouvement réelle (diff d'images, motion_pct), LAPI locale fast-alpr (modèle plaques européennes) avec vehicle_type/color associés, alertes liste noire.
- ✅ Scénarios d'alertes IA (7, configurables via GET/PUT /api/ai/alert-rules + dialog 'Règles IA' page Alertes) : intrusion_nocturne, vol_vehicule, rodeur, attroupement, vive_allure, collision (accident), enfant_route. Alertes réelles avec vignette + WebSocket + notification.
- ✅ Nouvelle page 'Événements IA' (/events) : cartes avec vignette/type/confiance/couleur/horodatage + filtres. Corrélation segments ↔ événements (mode ai/motion/continuous dans la timeline de relecture).
- ✅ Recherche véhicule : recherche auto (debounce), 13 couleurs, filtre insensible à la casse.
- ✅ deploy-app mis à jour : service go2rtc + ffmpeg dans l'image backend + vidéo démo montée.
- Incidents résolus : disque /app plein (stockage déplacé /data), ffmpeg/go2rtc effacés par reset d'env (binaires statiques persistants dans /app/bin et /app/go2rtc + PATH dans server.py), ffmpeg héritant du socket uvicorn 8001 (close_fds/start_new_session).
- Tests : iteration_13 (système réel, 13/14) et iteration_14 (couleurs + scénarios IA, 100%).

## Backlog P1/P2
- P1 : plaques make/model (modèle dédié), WebRTC faible latence dans l'UI (actuellement MJPEG), page plans de sites (frontend Vue /deploy), PTZ ONVIF réel (relais continuous move)
- P2 : SNMP UPS réel, optimisation auto CPU/GPU, refactoring routers.py en modules
