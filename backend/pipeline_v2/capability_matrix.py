"""v0.5.7 · Universal Camera API — Capability Matrix & Driver Health.

Services d'agrégation en lecture seule pour l'observabilité de la flotte.

Aucune I/O caméra directe. Les données sont lues depuis :

  - ``cameras.capabilities``          (rempli par ``CameraDeviceService.discover``)
  - ``cameras.last_validation``       (rempli par ``DriverValidator.run_and_persist``)
  - ``cameras.driver`` / ``vendor``   (persisté par le service)
  - ``MANIFEST`` de chaque classe driver (déclaration statique).

Ces services alimentent :

  - ``GET /api/devices/matrix?group=vendor|driver|model|camera``
  - ``GET /api/devices/drivers/health``
"""
from __future__ import annotations

import logging
from statistics import mean
from typing import Any, Iterable, Optional

from drivers import list_supported_vendors, get_driver

logger = logging.getLogger("pipeline_v2.capability_matrix")


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════
def _bool_capability_keys(caps: dict) -> Iterable[str]:
    """Itère sur les clefs à valeur booléenne d'un dict de capabilities."""
    for k, v in caps.items():
        if isinstance(v, bool):
            yield k


def _merge_or(dst: dict[str, bool], src: dict) -> None:
    """OR-merge de flags booléens : dst[k] = dst[k] OR src[k]."""
    for k in _bool_capability_keys(src):
        dst[k] = bool(dst.get(k, False) or src.get(k, False))


# ═════════════════════════════════════════════════════════════════════════
# Capability Matrix
# ═════════════════════════════════════════════════════════════════════════
async def build_capability_matrix(group: str = "vendor") -> dict:
    """Construit la matrice de capacités de la flotte, groupée par ``group``.

    ``group`` ∈ {``vendor``, ``driver``, ``model``, ``camera``}.

    Retour : ``{group_key: {capability_flag: bool, ...}, ...}``.
    """
    group = (group or "vendor").lower()
    if group not in ("vendor", "driver", "model", "camera"):
        raise ValueError(f"invalid group '{group}' (vendor|driver|model|camera)")

    cameras = await _load_cameras()
    matrix: dict[str, dict[str, bool]] = {}

    for cam in cameras:
        caps = cam.get("capabilities") or {}
        if not isinstance(caps, dict) or not caps:
            continue
        key = _resolve_group_key(cam, group)
        if key is None:
            continue
        bucket = matrix.setdefault(key, {})
        if group == "camera":
            # Une caméra → ses capacités telles quelles (booléens uniquement).
            for k in _bool_capability_keys(caps):
                bucket[k] = bool(caps.get(k))
        else:
            _merge_or(bucket, caps)
    return matrix


def _resolve_group_key(cam: dict, group: str) -> Optional[str]:
    if group == "vendor":
        return (cam.get("vendor") or (cam.get("device_info") or {}).get("manufacturer") or "unknown").lower()
    if group == "driver":
        return (cam.get("driver") or cam.get("vendor") or "unknown").lower()
    if group == "model":
        return ((cam.get("device_info") or {}).get("model") or cam.get("model") or "unknown")
    if group == "camera":
        return cam.get("id") or cam.get("_id")
    return None


# ═════════════════════════════════════════════════════════════════════════
# Driver Health
# ═════════════════════════════════════════════════════════════════════════
async def build_driver_health() -> dict[str, dict[str, Any]]:
    """Agrège manifests + stats runtime pour chaque driver connu du registry.

    Retour :

        {
          "reolink": {
            "manifest": {...},
            "cameras_count": 12,
            "validations_count": 8,
            "last_validation_at": "2026-02-…",
            "avg_score": 87
          },
          ...
        }
    """
    cameras = await _load_cameras()
    by_driver: dict[str, list[dict]] = {}
    for cam in cameras:
        dname = (cam.get("driver") or cam.get("vendor") or "unknown").lower()
        by_driver.setdefault(dname, []).append(cam)

    out: dict[str, dict[str, Any]] = {}
    for vendor in list_supported_vendors():
        cls = get_driver(vendor)
        manifest = getattr(cls, "MANIFEST", None) if cls else None
        cams = by_driver.get(vendor.lower(), [])
        validations = [c.get("last_validation") for c in cams if c.get("last_validation")]
        scores = [v.get("score") for v in validations if isinstance(v, dict) and isinstance(v.get("score"), int)]
        last_ts = _latest_ts([v.get("finished_at") for v in validations if isinstance(v, dict)])

        out[vendor.lower()] = {
            "manifest": manifest or {"driver": vendor, "status": "unknown"},
            "cameras_count": len(cams),
            "validations_count": len(validations),
            "last_validation_at": last_ts,
            "avg_score": int(round(mean(scores))) if scores else None,
        }
    return out


def _latest_ts(values: list) -> Optional[str]:
    values = [v for v in values if isinstance(v, str)]
    if not values:
        return None
    try:
        return max(values)
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════
# Accès Mongo isolé (facile à mocker en test)
# ═════════════════════════════════════════════════════════════════════════
async def _load_cameras() -> list[dict]:
    try:
        from database import db
        docs = await db.cameras.find({}, {"_id": 0}).to_list(length=None)
        return list(docs or [])
    except Exception as e:
        logger.warning("capability_matrix._load_cameras failed: %s", e)
        return []


__all__ = ["build_capability_matrix", "build_driver_health"]
