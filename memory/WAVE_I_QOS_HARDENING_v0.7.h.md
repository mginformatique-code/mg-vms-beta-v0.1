# v0.7.h · Wave I — QoS & Production Hardening (delta réel) · Rapport

**Périmètre livré** : le noyau vérifiable en 1 vague — Quality Score,
Reliability Score, Alertes automatiques Ops Center, Audit Mongo.
**Non livré ici (session dédiée requise)** : virtualisation listes UI,
tests de panne réseau/Mongo down, monitoring 24 h simulé, recrop
automatique avec plusieurs marges.

---

## 1. OCR Quality Score (Axe QoS)

`pipeline_v2/plate_quality.py::CropQuality.score_100` — propriété
calculée `int(round(score * 100))`. Exposée par `to_dict()`.

- Le score composite existant (0.5×sharpness + 0.3×contrast + 0.2×skew)
  est désormais lisible en 0-100 dans l'UI et les événements
- Score < 60 → `should_enhance = True` → pipeline applique deskew /
  CLAHE / unsharp automatiquement avant OCR (Wave C déjà en place)
- Score < 20 → `skip = True` → OCR non lancé (économie CPU)

Test dédié `TestQualityScore100`.

---

## 2. OCR Engine Reliability (apprentissage online)

Nouveau module `pipeline_v2/engine_reliability.py` (110 lignes).

### Modèle

Pour chaque couple `(camera_id, engine_name)` :
- `reads_total` — compteur cumulé
- `reads_recent_ok` — deque(100) de True/False
- `time_sum_ms / time_count` — moyenne d'inference

### Fonctions publiques

```python
record_engine_reading(camera_id, engine, *, success: bool, time_ms=0)
reliability_mult(camera_id, engine) -> float   # 0.5 – 1.5
snapshot() -> dict                              # exposition API
reset()                                         # tests
```

### Logique

- Neutre (mult = 1.0) tant que `< 10` lectures — évite l'over-fitting
  au boot
- Ensuite : `mult = 0.5 + rolling_accuracy * 1.0` → 0.5 si 0 %,
  1.5 si 100 %
- **À intégrer plus tard** dans la fusion pondérée
  (`anpr_tracker.best_reading`) : `weight = engine_weight(name) *
  reliability_mult(cam, name)`. Cette v0.7.h expose la data et
  l'endpoint, l'intégration dans la fusion sera livrée en v0.7.i pour
  garantir zéro régression sur les tests fusion existants.

### Endpoint

```
GET /api/diagnostics/engine-reliability     (permission view_live)
```

Retourne `{cam_id: {engine_name: {reads_total, rolling_accuracy,
avg_time_ms, reliability_mult}}}`.

Tests : 4 verts (neutre <10, boost à 1.5 sur succès, chute à 0.5 sur
échecs, snapshot structuré).

---

## 3. Alertes QoS automatiques → Ops Center

Nouveau module `pipeline_v2/qos_alerts.py` (170 lignes).

### Surveillance permanente

Un `asyncio.create_task(qos_watcher_loop())` lancé depuis `server.py`
scan toutes les **15 s** le snapshot de l'`inspector` + system info.

### Seuils SLA par défaut

| Métrique | Défaut | Sévérité |
|----------|:-:|:-:|
| `pipeline_total_ms` | 200 | warning |
| `yolo_ms` (p95) | 50 | warning |
| `tracking_ms` (p95) | 5 | info |
| `anpr_ms` (p95) | 120 | warning |
| `fps_min` | 5 | info |
| `ram_percent` | 85 | warning |
| `gpu_vram_percent` | 90 | warning |

Configurables via `PUT /api/diagnostics/qos-thresholds` (technician),
persistés dans `settings.qos_thresholds`.

### Anti-flap 30 s

Une même `(camera_id, kind)` d'alerte n'est ré-émise qu'après 30 s —
évite le spam Ops Center quand une caméra est constamment lente.

### Format événement inséré dans `events`

```json
{
  "type": "qos_alert",
  "kind": "pipeline_slow" | "yolo_slow" | "anpr_slow" | "fps_low" |
          "ram_high" | "gpu_vram_high",
  "severity": "info" | "warning" | "critical",
  "camera_id": "demo-cam-002",
  "message": "Pipeline total dépasse 200 ms (avg 60 s = 250.7 ms)",
  "details": {...},
  "timestamp": "...",
  "resolved": false
}
```

### Preuve live

Après 20 s de fonctionnement en preview CPU-only, 6 alertes émises :

```
[warning] yolo_slow · demo-cam-002 · Étage yolo p95 = 232.0 ms > seuil 50 ms
[warning] pipeline_slow · demo-cam-002 · Pipeline total dépasse 200 ms (avg 60 s = 250.7 ms)
[   info] fps_low · demo-cam-002 · FPS faible : 0.43 < 5.0
```

Tous les événements sont **visibles dans Operations Center** (via l'UI
Events existante — filtre `type=qos_alert`).

Tests : 4 verts (defaults, détection slow, ok sous seuils, endpoints).

---

## 4. Audit MongoDB

Nouveau script `backend/stress/mongo_audit.py` (140 lignes).

### Usage

```bash
cd /app/backend && source .env && python stress/mongo_audit.py
```

Produit :
- Rapport console : collections + count + size + indexes
- JSON persistant : `/app/memory/MONGO_AUDIT_v0.7.h.json`

### Détections

Pour chaque collection critique (cameras, events, plates, recordings,
audit_logs, users, sessions, tls_certificates) :

- **`missing_index`** — index attendu absent (warning)
- **`missing_ttl`** — TTL attendu absent (info) — events 90j,
  audit_logs 180j, sessions 30j
- **`large_no_time_index`** — collection > 100k docs sans index
  temporel (warning)

### Preuve

Passé sur la base preview : **17 recommandations** trouvées

- 5 index manquants sur `events`, 5 sur `plates`/`recordings`
- 2 index manquants sur `cameras.id / .status`
- 3 TTL à mettre en place (events 90j, audit_logs 180j, sessions 30j)
- 2 index sur `tls_certificates.id / .active` (nouvelle collection Wave G)

Ces recommandations sont **actionables** — l'intégrateur peut les
créer en ligne sans downtime :

```javascript
db.events.createIndex({timestamp: 1}, {expireAfterSeconds: 7776000})
db.plates.createIndex({camera_id: 1, timestamp: -1})
// etc.
```

Test dédié : `TestMongoAuditScript`.

---

## 5. Fichiers

| Fichier | +/- | Nature |
|---------|:-:|--------|
| `backend/pipeline_v2/plate_quality.py` | +8 / -0 | `score_100` property |
| `backend/pipeline_v2/engine_reliability.py` (nouveau) | +110 | Reliability tracking |
| `backend/pipeline_v2/qos_alerts.py` (nouveau) | +170 | Watcher + seuils + anti-flap |
| `backend/server.py` | +3 / 0 | Launch qos_watcher_loop |
| `backend/routes/health_dashboard.py` | +40 / 0 | 3 endpoints |
| `backend/stress/mongo_audit.py` (nouveau) | +140 | Audit indexes/TTL |
| `backend/tests/test_v07h_qos_hardening.py` (nouveau) | +105 | 10 tests |
| **TOTAL** | **~580 lignes** | |

Zéro modification API existante. **10 nouveaux tests verts, total 136/136.**

---

## 6. Backlog v0.7.i (à demander en session dédiée)

- Intégrer `reliability_mult` dans `anpr_tracker.best_reading`
  (nécessite mise à jour tests fusion existants — délicat)
- Recrop automatique multi-marges si Quality Score < 60 (nouvelle
  boucle de retry côté `_stage_anpr`)
- Virtualisation React (`react-window`) sur pages Vehicles / Events /
  Cameras pour tenir 100 000+ éléments
- Frontend ErrorBoundary **par section** (isole chaque tab plutôt que
  la racine seule)
- Stress-test panne : Mongo down / go2rtc down / caméra reboot →
  vérification que le backend redémarre proprement
- Job cron 24 h : simulation en preview avec logs perf p95/p99 par heure
- Création automatique des indexes Mongo au premier boot (bootstrap)
