# 🔧 Phase B suite · Pipeline Hardening v0.5.6 — Abstraction OCR core

**Objet** : Abstraire `fast-alpr` derrière une interface `PlateRecognizer` (même pattern que `Detector`) pour permettre la vraie substitution du moteur OCR core sans toucher au code du pipeline.

**Contraintes respectées** : aucune régression fonctionnelle, aucune modification UX, aucune API publique modifiée, comportement runtime identique.

---

## 🎯 Nouveau module `pipeline_v2/plate_recognizer.py`

### Interface

```python
@dataclass
class PlateOcrResult:
    text: str                                     # Texte brut de la plaque
    confidence: float                             # [0, 1]
    bbox_in_roi: tuple[float, float, float, float]   # x1, y1, x2, y2 relatifs au crop véhicule

@runtime_checkable
class PlateRecognizer(Protocol):
    name: str
    def recognize(self, vehicle_crop_bgr) -> list[PlateOcrResult]: ...
```

### Implémentation par défaut

```python
class FastAlprRecognizer:
    name = "fast-alpr"

    def recognize(self, vehicle_crop_bgr):
        with _ae.ALPR_INFERENCE_LOCK:              # P0-1 encapsulé
            raw = list(_ae._alpr.predict(vehicle_crop_bgr))
        return [PlateOcrResult(text=..., confidence=..., bbox_in_roi=(...))
                for r in raw if r.ocr and r.ocr.text]
```

Le lock global P0-1 vit désormais **dans le recognizer** — le pipeline
n'a plus rien à sérialiser lui-même.

### Registry

```python
class PlateRecognizerRegistry:
    def register(self, name: str, factory: type) -> None: ...
    def get(self, name: str) -> PlateRecognizer | None: ...
    def get_active(self, cam_config) -> tuple[PlateRecognizer, str, str|None]: ...
    def known(self) -> list[str]: ...

plate_registry = PlateRecognizerRegistry()
plate_registry.register("fast-alpr", FastAlprRecognizer)
```

Un `_NullPlateRecognizer` retourne toujours `[]` (fallback anti-crash si le default n'est pas chargé).

---

## 🔄 Migration `_stage_anpr` dans `camera_worker.py`

**Avant** (v0.5.6 Phase A) :
```python
with _ae.ALPR_INFERENCE_LOCK:
    alpr_results = list(_ae._alpr.predict(roi.crop))
for r in alpr_results:
    if not r.ocr or not r.ocr.text: continue
    bb = r.detection.bounding_box
    ...  # bb.x1, bb.y1, bb.x2, bb.y2, r.ocr.text, r.ocr.confidence
```

**Après** (v0.5.6 Phase B suite) :
```python
from .plate_recognizer import plate_registry as _plate_registry
_ocr, _ocr_name, _ocr_warning = _plate_registry.get_active(None)
ctx.metadata["ocr_core"] = {"name": _ocr_name, "warning": _ocr_warning}

ocr_results = _ocr.recognize(roi.crop)          # list[PlateOcrResult]
for r in ocr_results:
    bx1, by1, bx2, by2 = r.bbox_in_roi
    plate_text = (r.text or "").upper().strip()
    # ... suite identique
    ctx.plates.append({..., "engine": _ocr_name, ...})   # nom depuis le registry
```

Le pipeline **ne connaît plus** `fast-alpr` — il consomme un contrat abstrait.

---

## 🔌 Comment brancher un nouveau moteur OCR (PaddleOCR, cloud, custom)

Une seule ligne dans le plugin loader :

```python
# data/plugins/paddle-ocr/plugin.py
from pipeline_v2.plate_recognizer import plate_registry, PlateOcrResult

class PaddleOcrRecognizer:
    name = "paddle-ocr"
    def __init__(self):
        from paddleocr import PaddleOCR
        self._model = PaddleOCR(lang="en")

    def recognize(self, vehicle_crop_bgr):
        raw = self._model.ocr(vehicle_crop_bgr)
        return [
            PlateOcrResult(text=line[1][0], confidence=line[1][1],
                          bbox_in_roi=(line[0][0][0], line[0][0][1],
                                       line[0][2][0], line[0][2][1]))
            for line in raw[0] or []
        ]

# Au chargement (plugin_loader) :
plate_registry.register("paddle-ocr", PaddleOcrRecognizer)
```

Puis en Phase C : `cam.pipeline_config = {"anpr": ["paddle-ocr", "fast-alpr"], ...}` → PaddleOCR devient le moteur core pour cette caméra, fast-alpr un moteur additionnel pour la fusion.

---

## 🧪 Tests

**Nouveaux tests Phase B suite** (`test_v056b_ocr_abstraction.py`) — **13/13 verts** :

| Test | Vérifie |
|---|---|
| `test_plate_registry_has_fastalpr_by_default` | fast-alpr enregistré au boot |
| `test_plate_registry_get_returns_singleton` | Une seule instance par nom |
| `test_plate_registry_get_unknown_returns_none` | OCR inconnu → None |
| `test_plate_registry_can_register_third_party_ocr` | Extension plugin-friendly (MockOcr via Protocol) |
| `test_plate_registry_get_active_returns_triple` | Contrat `(rec, name, warning)` |
| `test_null_plate_recognizer_never_crashes` | Fallback anti-crash |
| `test_camera_worker_uses_plate_registry` | Import + appel au registry |
| `test_camera_worker_no_direct_alpr_predict_call` | `_alpr.predict` disparu de `_stage_anpr` |
| `test_ctx_metadata_ocr_core_key` | `ctx.metadata["ocr_core"]` renseigné |
| `test_plates_dict_format_preserved` | Clés critiques conservées (plate/confidence/plate_crop/vehicle_crop/vehicle_type/vehicle_color/engine/track_id/_owner_bbox) |
| `test_fastalpr_recognizer_returns_empty_without_alpr` | Anti-crash si `_ae._alpr` = None |
| `test_plate_ocr_result_fields` | Dataclass PlateOcrResult |

**Total Phase A + B + B-suite** : 39/39 verts.
**Non-régression suite complète** : 123/123 tests v0.5.x + pipeline + multi-plugin verts.

---

## 📁 Fichiers modifiés

- `backend/pipeline_v2/camera_worker.py` (`_stage_anpr` migré vers `plate_registry.get_active()` + `_ocr.recognize()`, engine dynamique)
- `backend/pipeline_v2/plate_recognizer.py` **(nouveau, +141 lignes)** — `PlateOcrResult`, `PlateRecognizer` Protocol, `FastAlprRecognizer`, `PlateRecognizerRegistry`, `_NullPlateRecognizer`, instance globale `plate_registry`

## 📁 Fichier ajouté

- `backend/tests/test_v056b_ocr_abstraction.py` — 13 tests dédiés.

---

## 🚦 Détection + Tracking + OCR core : tous abstraits

À l'issue de la Phase B + B suite, les 3 briques cœur du pipeline IA sont pluggables :

| Brique | Interface | Registry | Default |
|---|---|---|---|
| Détecteur | `Detector` Protocol | `pipeline_v2.detector.registry` | `yolov11` |
| Tracker | `resolve_algo` + warning | `pipeline_v2.tracking` (built-in) | `bytetrack` |
| OCR core | `PlateRecognizer` Protocol | `pipeline_v2.plate_recognizer.plate_registry` | `fast-alpr` |

Chacun expose :
- Un contrat sémantique (dataclass) indépendant du moteur.
- Un registry avec `get_active(cam_config)` — argument `cam_config` prêt pour Phase C.
- Un `_Null*` de secours qui ne crash jamais.
- Une métadonnée exposée dans `ctx.metadata` remontée par l'Inspector.

**Phase C — Configuration par caméra** peut maintenant se limiter à :
1. Ajouter le champ `pipeline_config` sur `Camera`.
2. Migration auto : chaque cam existante hérite `{detector: "yolov11", tracker: "bytetrack", anpr: ["fast-alpr"], fusion: "hierarchical"}`.
3. Remplacer les 3 `TODO Phase C` par une lecture de `cam_config["pipeline_config"]`.

Aucun code métier ne bougera.
