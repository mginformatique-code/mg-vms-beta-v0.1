# 🔧 Phase B · Pipeline Hardening v0.5.6 — Rapport final

**Objet** : Basculer le hot path YOLO derrière l'abstraction `Detector` créée en Phase A. Permet enfin de swapper RT-DETR / ONNX / TensorRT sans toucher au code métier.

**Contraintes respectées** : aucune régression fonctionnelle, aucune modification UX, aucune API publique modifiée, comportement runtime identique à v0.5.6-Phase A (une seule implémentation active = `YoloDetector`).

---

## 🎯 Ce qui a changé

### 1. Enrichissement de `pipeline_v2/detector.py`

Ajout d'un **DetectorRegistry** singleton :

```python
class DetectorRegistry:
    def register(self, name: str, factory: type) -> None: ...
    def get(self, name: str) -> Detector | None: ...
    def get_active(self, cam_config) -> tuple[Detector, str, str|None]: ...
    def known(self) -> list[str]: ...

# Instance globale
registry = DetectorRegistry()
registry.register("yolov11", YoloDetector)
```

Ajout d'un **_NullDetector** : détecteur no-op qui retourne toujours `[]`. Utilisé si le YOLO n'est pas encore chargé ou si un moteur demandé échoue à s'instancier. **Ne jamais crash** — le pipeline continue silencieusement à zéro détection.

### 2. Migration de `_stage_detection` dans `camera_worker.py`

**Avant** (v0.5.5) :
```python
def _stage_detection(self, ctx):
    with _ae.YOLO_INFERENCE_LOCK:
        results = _ae._model.predict(ctx.image, ...)
    for box in results.boxes:
        cls_name = _ae._model.names[int(box.cls)]
        ...
```

**Après** (v0.5.6 Phase B) :
```python
def _stage_detection(self, ctx):
    from .detector import registry as _detector_registry
    detector, det_name, det_warning = _detector_registry.get_active(None)
    objects = detector.detect(ctx.image)   # DetectionObject[]
    ctx.metadata["detector"] = {"name": det_name, "warning": det_warning}
    inspector.set_meta(self.camera_id, detector=det_name)
    for obj in objects:
        cls_name = obj.label
        ...
```

Le pipeline **ne connaît plus YOLO**. Il demande un `Detector` au registry et consomme une `list[DetectionObject]`. Le contrat aval (dict avec `class`, `label`, `confidence`, `_crop`, `_bbox`…) reste **identique** — c'est de la compat parfaite.

### 3. Nouveau champ `ctx.metadata["detector"]`

Exposé par l'Inspector API (`GET /api/pipeline/inspector`) → chaque caméra remonte le nom du détecteur actif + warning éventuel. Prêt pour affichage UI en Phase D.

---

## ✅ Comment brancher un nouveau détecteur (RT-DETR, TensorRT…)

**Sans toucher au code du pipeline**. En 3 lignes dans le plugin :

```python
# data/plugins/rt-detr/plugin.py
from pipeline_v2.detector import registry, DetectionObject

class RTDetrDetector:
    name = "rt-detr"
    def __init__(self):
        import rtdetr  # noqa
        self._model = rtdetr.load("rtdetr-l.onnx")

    def detect(self, frame_bgr) -> list[DetectionObject]:
        raw = self._model(frame_bgr)
        return [
            DetectionObject(
                bbox=(r.x1, r.y1, r.x2, r.y2),
                label=r.label,
                confidence=r.score,
                class_id=r.class_id,
            )
            for r in raw
        ]

# Au chargement du plugin (plugin_loader) :
registry.register("rt-detr", RTDetrDetector)
```

Puis, en Phase C : `cam.pipeline_config = {"detector": "rt-detr", ...}` → le pipeline utilise RT-DETR pour **cette caméra uniquement**, YOLO pour les autres.

Aujourd'hui (Phase B), la sélection est globale (`registry._default = "yolov11"`). La lecture de la config par caméra est marquée `# TODO Phase C` explicitement dans le code.

---

## 🧪 Tests

**Nouveaux tests Phase B** (`test_v056b_detector_registry.py`) — **10/10 verts** :

| Test | Vérifie |
|---|---|
| `test_registry_has_yolov11_by_default` | YOLOv11 enregistré au boot |
| `test_registry_get_returns_singleton` | Une seule instance par nom |
| `test_registry_get_unknown_returns_none` | Détecteur inconnu → None |
| `test_registry_can_register_third_party_detector` | Extension plugin-friendly (MockDetector via Protocol) |
| `test_registry_get_active_returns_triple` | Contrat `(Detector, str, warning|None)` |
| `test_null_detector_never_crashes` | Fallback anti-crash |
| `test_camera_worker_uses_registry` | Import et appel présents |
| `test_camera_worker_no_direct_predict_call` | `_model.predict` disparu de `_stage_detection` |
| `test_ctx_metadata_detector_key` | `ctx.metadata["detector"]` renseigné |
| `test_detection_dict_format_preserved` | Toutes les clés critiques (class, label, confidence, thumbnail, _crop, vehicle_color, _bbox) conservées |

**Non-régression suite complète** :

- **27/27 tests v0.5.6** (Phase A + B) verts
- **111/111 tests** suite pipeline / multi-plugin / v0.5.x verts
- Les 27 tests `test_iter*_rtsp_*.py` qui échouent sont **pré-existants** (infra caméra physique / go2rtc live streams absents dans l'env preview) et **sans lien** avec Phase B.

---

## 📁 Fichiers modifiés

- `backend/pipeline_v2/detector.py` (+107 lignes : `DetectorRegistry`, `_NullDetector`, instance globale `registry`)
- `backend/pipeline_v2/camera_worker.py` (`_stage_detection` migré vers `registry.get_active()` + `detector.detect()`)

## 📁 Fichier ajouté

- `backend/tests/test_v056b_detector_registry.py` — 10 tests dédiés.

---

## 🚦 Prêt pour Phase C

**Pré-requis validés** :
- Interface `Detector` stable et documentée.
- Registry opérationnel avec ajout dynamique de plugins.
- Pipeline ne dépend plus de YOLO à l'appel — seule l'implémentation `YoloDetector` en dépend.
- Le champ `cam_config` est déjà présent dans la signature `get_active(cam_config)` — il suffit de lire `cam_config["pipeline_config"]["detector"]` en Phase C.

**Phase C — Configuration par caméra** (`pipeline_config` sur `Camera`) est maintenant débloquée. Chaque caméra pourra choisir :
- son detector (`yolov11`, `rt-detr`, `tensorrt`…)
- son tracker (`bytetrack`, `botsort`…)
- ses moteurs ANPR (`fast-alpr`, `paddle-ocr`…)
- son mode de fusion (`hierarchical`, `highest`, `majority`…)

… sans modifier une seule ligne de code métier.
