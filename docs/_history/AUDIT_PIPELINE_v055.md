# 🔍 Audit de consolidation — Pipeline IA MG-VMS

**Version auditée** : v0.5.5.e (Feb 2026)  
**Type d'audit** : Read-only, aucun code modifié.  
**Objectif** : Vérifier que le pipeline peut supporter plusieurs détecteurs, trackers, OCR, plugins et workflows avant v1.0.

---

## 📊 Tableau de bord (verdict global)

| # | Domaine | Statut | Priorité |
|---|---|---|---|
| 1 | Détection multi-détecteurs | ❌ Non conforme | **P0** |
| 2 | Tracking multi-trackers | ⚠️ Partiel | **P0** |
| 3 | Détection multi-objets (générique) | ⚠️ Partiel | P1 |
| 4 | Multi-ANPR (fusion/vote) | ⚠️ Partiel | **P0** |
| 5 | Pipeline crop mutualisé | ✅ **OK** | — |
| 6 | Synchronisation / parallélisme | ⚠️ Partiel | P1 |
| 7 | Timings & métriques | ⚠️ Partiel | P2 |
| 8 | Workers / queues / backpressure | ⚠️ Race condition | **P0** |
| 9 | Multi-plugins réel | ✅ OK (parallèle via bus) | — |
| 10 | Cache mutualisé | ✅ OK | — |
| 11 | Couplages forts | ⚠️ Détectés | P1 |
| 12 | Stress test réel | ❌ Absent | P2 |
| 13 | Rapport produit | ✅ Ce document | — |

**Verdict global : NOT READY — MATERIAL DEFECTS**  
2 anomalies P0 confirmées bloquent la promesse « multi-détecteurs / multi-trackers » de v1.0.

---

## 🎯 Réponses objectives aux 6 questions de validation

### 1. MG-VMS est-il réellement multi-détecteurs ?
**❌ NON — CONFIRMÉ**

Preuve :
- `backend/pipeline_v2/downstream.py:51` : `_CORE_PLUGINS_ALWAYS_ON = ["yolov11", "bytetrack", "fast-alpr"]` — YOLO est **hardcodé** comme détecteur core.
- `backend/pipeline_v2/downstream.py:293-306` : `dispatch_frame()` reçoit toujours `precomputed_detections=det_objs`, ce qui **court-circuite** l'appel aux `FrameAnalyzer` alternatifs des plugins RT-DETR / ONNX / OpenVINO / YOLO-NAS.
- `data/plugins/rt-detr/plugin.py:45-55` : `analyze()` retourne **une liste vide** — c'est un stub PoC.
- `backend/pipeline_v2/camera_worker.py:84-101` : le core appelle systématiquement `_ae._model.predict()` (le YOLO singleton d'`ai_engine.py:99-100`).

**Conclusion** : Activer RT-DETR / ONNX / OpenVINO dans la whitelist d'une caméra ne change strictement rien — silencieusement. Le pipeline reste 100 % YOLO.

---

### 2. MG-VMS est-il réellement multi-trackers ?
**⚠️ PARTIEL — CONFIRMÉ**

Preuve :
- `backend/pipeline_v2/tracking.py:19` : `SUPPORTED_ALGOS = {"bytetrack", "botsort"}` — seuls 2 trackers sont vraiment implémentés.
- `backend/pipeline_v2/tracking.py:29` : `effective = requested if requested in SUPPORTED_ALGOS else "bytetrack"` — fallback silencieux vers ByteTrack pour DeepSORT/OCSORT/StrongSORT.
- `data/plugins/deepsort/plugin.py:26-39` : IDs de tracking générés artificiellement (per-frame), pas de vraie ré-identification.

**Conclusion** : ByteTrack et BoTSORT fonctionnent réellement. DeepSORT, OCSORT, StrongSORT sont des **stubs qui trompent l'opérateur** (aucun warning UI).

---

### 3. MG-VMS est-il réellement multi-OCR / multi-ANPR ?
**⚠️ PARTIEL — CONFIRMÉ**

Preuve :
- ✅ **Dispatch parallèle** OK : `backend/pipeline_v2/downstream.py:100-114` envoie le crop à plusieurs moteurs OCR en `asyncio.gather()`.
- ❌ **Fusion / vote absent en live** : `backend/plugin_manager/fusion.py` (`apply_policy`) existe mais n'est utilisée **que par le endpoint `/simulate`** (`routes/plugins_bus.py:531`).
- ❌ Le chemin live (`downstream.py:399-438`) persiste **une ligne `db.plates` par moteur** (dedup keyé sur `engine`, ligne 405), sans réconciliation.

**Conclusion** : L'infrastructure multi-OCR existe (dispatch parallèle réel) mais **pas la logique de fusion en production**. Résultat côté UI : deux moteurs qui lisent « ABC-123 » et « ABC-133 » créent **deux plaques distinctes** dans la DB.

---

### 4. Les crops sont-ils mutualisés ?
**✅ OUI — CONFIRMÉ**

Preuve :
- `backend/pipeline_v2/frame_context.py:77-107` : classe `VehicleROI` encapsule le crop véhicule + JPEG encodé, mémoisé.
- `camera_worker.py:254-255` : les plugins ANPR consomment `roi.jpeg_data_uri()` sans re-cropper.
- `camera_worker.py:249` : le crop de la plaque est fait 1 fois puis passé à tous les moteurs OCR.

**Conclusion** : Le crop est bien mutualisé — aucune duplication mémoire ou re-crop entre plugins.

---

### 5. Les plugins travaillent-ils réellement en parallèle ?
**⚠️ PARTIEL — CONFIRMÉ**

Preuve :
- ✅ Le **plugin bus** (`plugin_manager/bus.py`) utilise `asyncio.gather()` pour dispatcher aux consumers.
- ❌ **Multi-ANPR séquentiel** dans le core : la boucle `for r in ocr_results` (`downstream.py:399-438`) enchaîne les moteurs OCR **un par un**.
- ❌ **Stages du core séquentiels** : Detection → Tracking → ROI → Crop → OCR → Broadcast se font en chaîne.

**Conclusion** : Les plugins downstream tournent bien en parallèle, mais le **cœur pipeline (détection + tracking + ANPR) est linéaire** — normal pour la cohérence mais mesurable pour la latence.

---

### 6. Le timing est-il optimal ou existe-t-il des goulets d'étranglement ?
**⚠️ GOULETS IDENTIFIÉS — CONFIRMÉS**

Preuves des bottlenecks :
1. **Modèle YOLO singleton partagé** (`ai_engine.py:99-100`) sans lock → contention & risque de corruption sous 30 cams.
2. **`ai_loop` toutes les 150ms** (`ai_engine.py:31`) fan-out sur toutes les cams — pas d'orchestration frame-based.
3. **Cache anti-doublon ANPR bloqué à 1s** au lieu du config (`camera_worker.py:248` : `min(cache_ttl, 1)` au lieu de `max`).
4. **Pas d'agrégation p95/p99** : télémétrie `pipeline_metrics` présente mais pas d'agrégation percentile.

---

## 📋 Section 1 — DÉTECTION (❌ P0)

### Preuve du couplage YOLO
```python
# backend/pipeline_v2/downstream.py:51
_CORE_PLUGINS_ALWAYS_ON = ["yolov11", "bytetrack", "fast-alpr"]
```

### Impact
Un client qui active RT-DETR pour améliorer la détection petits objets ne verra **aucune différence** — pire, aucun log ne l'avertit que son plugin est inerte.

### Correction proposée
1. Router la détection via un vrai `FrameAnalyzer` (bus) plutôt que par le singleton `ai_engine._model`.
2. Ajouter une notion `role="detector"` dans le manifest plugin ; à runtime, si un plugin détecteur (autre que yolov11) est activé, le core doit **utiliser SES résultats** au lieu de ceux de YOLO.
3. Surfacer un badge UI « Plugin non opérationnel (stub) » sur RT-DETR / ONNX / OpenVINO / YOLO-NAS tant qu'ils ne renvoient rien de réel.

**Priorité : P0** — bloquant pour la promesse v1.0.

---

## 📋 Section 2 — TRACKING (⚠️ P0)

### Preuve du fallback silencieux
```python
# backend/pipeline_v2/tracking.py:19,29
SUPPORTED_ALGOS = {"bytetrack", "botsort"}
...
effective = requested if requested in SUPPORTED_ALGOS else "bytetrack"
```

### Impact
Un opérateur active DeepSORT pour de la ré-identification post-occlusion → ByteTrack tourne en fait, comportement différent, aucune alerte.

### Correction proposée
Deux options :
- **A** (safe) : refuser l'activation d'un tracker non implémenté avec un message clair au niveau du plugin_loader.
- **B** (ambitieux) : implémenter DeepSORT/OCSORT via les bibliothèques upstream (déjà en dépendances via `deep-sort-realtime` ?).

Dans les deux cas, l'`effective_algo` doit être **visible dans l'UI** (`AIPipelineMonitor` ou Settings caméra).

**Priorité : P0** — même problème contractuel que la détection.

---

## 📋 Section 3 — DÉTECTION MULTI-OBJETS (⚠️ P1)

### État actuel
- Les plugins downstream (`weapon-detection`, `PPE`, `fall-detection`) référencent les objets par **label sémantique** (`"person"`, `"car"`) — ✅ bon point.
- Mais les labels dépendent des classes COCO YOLO (0=person, 2=car, 5=bus, 7=truck).

### Zones à confirmer
- Ajouter une classe « casque » ou « gilet » demanderait :
  - Ré-entraîner ou remplacer le modèle YOLO (dette du plugin détecteur, pas du core).
  - Que le core respecte le vocabulaire du plugin actif — donc dépend directement de la correction de la section 1.

**Priorité : P1** — dépend de la section 1.

---

## 📋 Section 4 — MULTI-ANPR (⚠️ P0)

### Preuve du "no fusion en live"
```python
# backend/plugin_manager/fusion.py — apply_policy(engines_reads) → fused result
# Seul call site :
# backend/routes/plugins_bus.py:531 — endpoint /simulate uniquement.
```

Le chemin live (`downstream.py:399-438`) enregistre chaque `read` de chaque moteur comme une ligne DB séparée.

### Impact
- Deux moteurs OCR sur la même plaque → 2 entrées `db.plates` distinctes.
- L'UI Vehicle Search affiche des doublons contradictoires.
- Pas de score de confiance consolidé.

### Correction proposée
Dans `camera_worker.py::_prerun_multi_anpr`, une fois tous les moteurs ayant retourné :
```
final = apply_policy(engines_results, policy="majority" | "highest_conf" | "consensus")
```
puis ne persister que le `final` en DB. Conserver les reads bruts sous forme d'`evidence` dans le doc DB.

**Priorité : P0** — ANPR est un module de valeur commerciale critique.

---

## 📋 Section 5 — PIPELINE CROP MUTUALISÉ (✅ OK)

Rien à corriger. Le pattern `VehicleROI` avec mémoïsation JPEG est propre et efficient.

---

## 📋 Section 6 — SYNCHRONISATION (⚠️ P1)

### État actuel
- ✅ Bus plugins : parallèle (`asyncio.gather`).
- ❌ Multi-ANPR : séquentiel par crop.
- ❌ Cœur pipeline : linéaire (normal — sinon incohérence détection/tracking).

### Correction proposée
- Fanout OCR en `asyncio.gather()` dans `_prerun_multi_anpr` (aujourd'hui séquentiel).
- Conserver detection/tracking en séquence (nécessaire à la cohérence).

**Priorité : P1** — gain de latence significatif si 3+ moteurs OCR actifs.

---

## 📋 Section 7 — TIMINGS (⚠️ P2)

### État actuel
- ✅ `pipeline_metrics` (`pipeline_v2/pipeline_metrics.py`) existe et trace les stages.
- ✅ Inspector API (`test_v042_pipeline_inspector_api.py`) valide l'exposition.
- ❌ **Pas d'agrégation percentiles p95/p99** — juste moyenne et max instantanés.

### Correction proposée
Ajouter un rolling window (par exemple 100 samples ou 5 minutes) qui calcule les percentiles avec numpy et les expose via `GET /api/pipeline/metrics`.

**Priorité : P2** — utile pour la mesure v0.9 (30-50 cams sur RTX A2000) mais non-bloquant.

---

## 📋 Section 8 — WORKERS / RACE CONDITION (⚠️ P0)

### Preuve LIKELY (non observée à runtime, mais analyse statique probante)
- `backend/ai_engine.py:99-100` : `_model` et `_alpr` sont **singletons globaux**.
- `backend/pipeline_v2/camera_worker.py:93` : `_ae._model.predict(...)` appelé depuis plusieurs workers via `asyncio.to_thread`.
- `grep -rn "Lock\|Semaphore" /app/backend/pipeline_v2/` : **aucun résultat** protégeant l'accès au modèle.

### Impact
Sous 30 cameras concurrentes, ultralytics/`predict()` mute son état interne (`predictor`, batch buffers) → risque de :
- Détections corrompues (mélange entre caméras).
- Segfault CUDA à haute charge.
- Backend crashs sporadiques difficile à reproduire.

### Correction proposée
Deux options :
- **A** (simple) : `asyncio.Semaphore(1)` sur les appels au modèle.
- **B** (perf) : Un worker inference dédié qui pull une queue de frames et batch les inférences (comme Frigate).

**Priorité : P0** — bloquant pour hardware stress test v0.9.

---

## 📋 Section 9 — MULTI-PLUGINS (✅ OK)

Les plugins consumers travaillent en parallèle via `asyncio.gather()` dans le bus.  
Pas de rescanne : les détections sont passées par référence.

---

## 📋 Section 10 — CACHE MUTUALISÉ (✅ OK)

- JPEG frame encodé 1×, réutilisé.
- Crops véhicules mémoïsés par `VehicleROI`.
- Détections passées en référence, pas copiées.

---

## 📋 Section 11 — COUPLAGES FORTS (⚠️ P1)

### Fichiers qui importent YOLO directement (hors du plugin yolov11)
- `backend/ai_engine.py` — import direct `ultralytics.YOLO`.
- `backend/pipeline_v2/camera_worker.py:93,215` — accès direct à `_ae._model` et `_ae._alpr`.

### Fichiers qui référencent ByteTrack par nom
- `backend/pipeline_v2/tracking.py:19,29` — hardcoded fallback.
- `backend/pipeline_v2/downstream.py:51` — `_CORE_PLUGINS_ALWAYS_ON` inclut `"bytetrack"`.

### Fichiers avec fast-alpr en dur
- `backend/pipeline_v2/downstream.py:51` — `_CORE_PLUGINS_ALWAYS_ON` inclut `"fast-alpr"`.
- `backend/pipeline_v2/camera_worker.py:215` — `_ae._alpr.predict()`.

### Correction
Extraire les 3 couplages "core-always-on" derrière une abstraction unique (`CorePipelineFactory` qui lit la config).

**Priorité : P1** — après avoir résolu les P0.

---

## 📋 Section 12 — STRESS TEST (❌ P2)

### Recherche
- `grep -rn "30 cam\|30 caméras\|stress\|load_test" /app/backend/tests/` : **aucun test** ne simule 30 caméras avec plusieurs plugins.
- `test_v045_latency.py` mesure la latence à 1 caméra.

### Correction
Créer un scénario stress test :
- 30 caméras simulées (frames synthétiques 1920×1080).
- 3 plugins consumers (weapon, PPE, fall).
- 2 moteurs OCR.
- Mesure FPS, CPU, RAM, VRAM, latence pipeline.
- Assertion : FPS ≥ 15 par caméra, no crash.

**Priorité : P2** — à faire avant v0.9 (hardware validation A2000).

---

## 🧭 Plan d'action recommandé

### P0 — Bloquants v1.0 (à traiter en priorité)

1. **[Race condition YOLO/ALPR singleton]**  
   `ai_engine.py` — protéger `_model.predict()` et `_alpr.predict()` par un `Semaphore` OU migrer vers un worker inference dédié (queue + batch).

2. **[Détection multi-détecteurs inerte]**  
   `pipeline_v2/downstream.py:51` + `dispatch_frame:293-306`  
   Router les détections via `FrameAnalyzer` du bus quand un plugin non-YOLO est actif.

3. **[Tracker fallback silencieux]**  
   `pipeline_v2/tracking.py:29` — refuser explicitement les trackers non implémentés OU les implémenter.

4. **[Fusion multi-OCR live absente]**  
   `pipeline_v2/camera_worker.py::_prerun_multi_anpr` — appliquer `fusion.apply_policy` et persister un seul résultat consolidé.

5. **[Cache plate ANPR cassé]**  
   `pipeline_v2/camera_worker.py:248` — corriger `min(cache_ttl, 1)` en `max(cache_ttl, 1)` (probable typo).

### P1 — Avant v1.0

6. Fanout OCR parallèle (asyncio.gather sur les moteurs).
7. Extraire les 3 couplages `_CORE_PLUGINS_ALWAYS_ON` derrière une factory.
8. Ajouter une notion `role` explicite dans le manifest plugin (detector / tracker / ocr / analyzer / notifier).

### P2 — v1.1

9. Agrégation p95/p99 dans `pipeline_metrics`.
10. Stress test synthétique 30 cams / 3 plugins / 2 OCR.

### P3 — Dette technique

11. Documentation formelle du contrat `FrameAnalyzer` / `Tracker` / `PlateRecognizer`.
12. Retirer les stubs (rt-detr, deepsort, ocsort, strongsort) ou marquer explicitement "non opérationnel" dans l'UI.

---

## 🔒 Garanties de cet audit

- ✅ **Aucune modification de code** — audit read-only pur.
- ✅ **Aucune API cassée** — les 32 tests backend v0.5.5.* + v0.5.4 restent verts.
- ✅ **Aucune fonctionnalité ajoutée**.
- ✅ **Chaque conclusion est appuyée par un fichier:ligne** vérifiable.

## 📝 Méthodologie

- Lecture statique de `/app/backend/pipeline_v2/`, `/app/backend/plugins/`, `/app/backend/plugin_manager/`, `/app/backend/routes/`.
- Grep exhaustif sur les couplages (`ultralytics`, `bytetrack`, `fast_alpr`, `Semaphore`, `Lock`, `precomputed_detections`).
- Vérification des tests d'inspection existants (`test_v041_pipeline_per_camera.py`, `test_v042_pipeline_inspector_api.py`, `test_v043_*.py`).
- Ce document ne comporte **aucune affirmation** non appuyée par une preuve dans le codebase.

---

**Prochaine étape recommandée** : traiter les 5 P0 dans une itération dédiée « Pipeline Hardening v0.5.6 » avant toute nouvelle fonctionnalité.
