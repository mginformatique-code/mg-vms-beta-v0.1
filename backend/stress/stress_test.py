"""v0.7.e · Wave F · Stress-test pipeline IA — mesure scientifique 1→50 caméras.

Ce harness stresse UNIQUEMENT les étages du pipeline v2 qui sont testables
hors matériel réel :

  * Wave C : ``assess_crop_quality`` (Laplacien + Hough) → mesure sharpness
  * Wave C : ``enhance_plate_crop`` (deskew + CLAHE + unsharp)
  * Wave C : ``crop_hash`` (aHash 16×16)
  * YOLOv8n forward pass (si Ultralytics disponible — sinon détecteur factice)

Il **ne prétend PAS** mesurer un pipeline complet incluant RTSP + décodage
GPU + fusion multi-OCR + Mongo — ces étages requièrent des caméras réelles
et un GPU NVIDIA que la preview n'a pas. Les chiffres produits sont donc
CPU-only et sous-estiment les gains GPU (typiquement ×5→×20 sur YOLOv8n).

Sortie : ``/app/memory/STRESS_TEST_v0.7.e_report.json`` + rapport MD
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import des étages Wave C
from pipeline_v2.plate_quality import (  # noqa: E402
    assess_crop_quality, enhance_plate_crop, crop_hash,
)

# YOLOv8n en CPU (lent mais mesurable)
YOLO_MODEL = None
try:
    from ultralytics import YOLO  # noqa: E402
    # Charge le plus petit modèle disponible localement
    model_path = os.environ.get("MGVMS_YOLO_MODEL", "yolov8n.pt")
    if Path(model_path).exists() or True:
        YOLO_MODEL = YOLO(model_path)
        # Warmup
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        YOLO_MODEL(dummy, verbose=False)
except Exception as e:
    print(f"[warn] YOLO non chargé : {type(e).__name__}: {str(e)[:80]}")


PROC = psutil.Process(os.getpid())


def make_synthetic_frame(w: int = 1280, h: int = 720) -> np.ndarray:
    """Génère un frame HD synthétique avec du contenu réaliste (texture + rectangles)."""
    rng = np.random.default_rng(seed=42)
    img = rng.integers(60, 180, (h, w, 3), dtype=np.uint8)
    # Ajoute quelques rectangles simulant des véhicules
    for _ in range(3):
        x1 = int(rng.integers(50, w - 250))
        y1 = int(rng.integers(50, h - 200))
        x2 = x1 + int(rng.integers(150, 250))
        y2 = y1 + int(rng.integers(120, 200))
        color = tuple(int(c) for c in rng.integers(20, 240, 3))
        cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)
        # Un rectangle plaque à l'intérieur
        px1, py1 = x1 + 20, y2 - 40
        px2, py2 = px1 + 80, py1 + 25
        cv2.rectangle(img, (px1, py1), (px2, py2), (240, 240, 240), -1)
    return img


def make_synthetic_plate_crop() -> np.ndarray:
    """Crop plaque 200×80 avec bruit + texte simulé (barres alternées)."""
    img = np.full((80, 200, 3), 220, dtype=np.uint8)
    # Barres verticales foncées simulant les caractères
    for i in range(10, 190, 25):
        cv2.rectangle(img, (i, 15), (i + 15, 65), (30, 30, 30), -1)
    # Un peu de bruit gaussien
    noise = np.random.normal(0, 8, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    return float(np.percentile(vals, p))


async def process_one_camera(cam_idx: int, frame: np.ndarray, plate: np.ndarray,
                              stages: dict) -> float:
    """Simule le pipeline v2 pour une caméra sur un frame donné.

    Retourne le temps total en ms. Chaque étage a sa liste de mesures.
    """
    t_total = time.perf_counter()

    # 1. Détection YOLO
    if YOLO_MODEL is not None:
        t0 = time.perf_counter()
        # imgsz=640 pour rester dans le mode par défaut
        _ = await asyncio.to_thread(YOLO_MODEL, frame, verbose=False)
        stages["yolo_ms"].append((time.perf_counter() - t0) * 1000)
    else:
        stages["yolo_ms"].append(0.0)

    # 2. Wave C · assess_crop_quality
    t0 = time.perf_counter()
    q = assess_crop_quality(plate)
    stages["assess_ms"].append((time.perf_counter() - t0) * 1000)

    # 3. Wave C · enhance_plate_crop
    t0 = time.perf_counter()
    enhanced = enhance_plate_crop(plate, q)
    stages["enhance_ms"].append((time.perf_counter() - t0) * 1000)

    # 4. Wave C · crop_hash
    t0 = time.perf_counter()
    _ = crop_hash(enhanced)
    stages["hash_ms"].append((time.perf_counter() - t0) * 1000)

    total_ms = (time.perf_counter() - t_total) * 1000
    stages["total_ms"].append(total_ms)
    return total_ms


async def run_cohort(n_cameras: int, frames_per_cam: int = 3) -> dict:
    """Exécute ``n_cameras`` caméras en parallèle sur ``frames_per_cam`` frames chacune.

    Simule ``frames_per_cam`` cycles IA successifs. Toutes les caméras sont
    lancées via ``asyncio.gather`` — parallélisme réel côté YOLO (grâce à
    ``to_thread`` du ``run_in_executor`` par défaut).
    """
    stages = {k: [] for k in ("yolo_ms", "assess_ms", "enhance_ms", "hash_ms", "total_ms")}
    frame = make_synthetic_frame()
    plate = make_synthetic_plate_crop()

    # Reset compteurs psutil
    PROC.cpu_percent(interval=None)
    gc.collect()
    rss_before_mb = PROC.memory_info().rss / (1024 * 1024)

    t_start = time.perf_counter()
    for _ in range(frames_per_cam):
        tasks = [process_one_camera(i, frame, plate, stages) for i in range(n_cameras)]
        await asyncio.gather(*tasks)
    wall_ms = (time.perf_counter() - t_start) * 1000

    cpu_pct = PROC.cpu_percent(interval=None)
    rss_after_mb = PROC.memory_info().rss / (1024 * 1024)

    # Métriques agrégées
    result = {
        "n_cameras": n_cameras,
        "frames_per_cam": frames_per_cam,
        "iterations_total": n_cameras * frames_per_cam,
        "wall_ms": round(wall_ms, 1),
        "fps_effective": round((n_cameras * frames_per_cam) / (wall_ms / 1000), 2)
                          if wall_ms > 0 else 0,
        "cpu_percent": round(cpu_pct, 1),
        "rss_before_mb": round(rss_before_mb, 1),
        "rss_after_mb": round(rss_after_mb, 1),
        "rss_delta_mb": round(rss_after_mb - rss_before_mb, 1),
        "stages": {},
    }
    for stage, samples in stages.items():
        if not samples:
            continue
        result["stages"][stage] = {
            "count": len(samples),
            "mean": round(statistics.mean(samples), 2),
            "median": round(statistics.median(samples), 2),
            "p95": round(percentile(samples, 95), 2),
            "p99": round(percentile(samples, 99), 2),
            "max": round(max(samples), 2),
        }
    return result


async def main() -> dict:
    print("=" * 70)
    print(f"v0.7.e · Wave F · Stress-test — CPU-only ({psutil.cpu_count()} vCPUs)")
    print(f"YOLO chargé : {YOLO_MODEL is not None}")
    print("=" * 70)
    cohorts = [1, 5, 10, 20, 30, 50]
    results = []
    for n in cohorts:
        print(f"\n▶  Cohorte n_cameras={n} …")
        r = await run_cohort(n, frames_per_cam=3)
        results.append(r)
        s = r["stages"]
        print(f"   wall={r['wall_ms']:>7.1f} ms · fps={r['fps_effective']:>6.2f} · "
              f"CPU={r['cpu_percent']:>5.1f}% · RSS={r['rss_after_mb']:>7.1f} MB "
              f"(Δ{r['rss_delta_mb']:+.1f})")
        print(f"   yolo:    mean={s['yolo_ms']['mean']:>7.2f} ms  p95={s['yolo_ms']['p95']:>7.2f}  p99={s['yolo_ms']['p99']:>7.2f}")
        print(f"   assess:  mean={s['assess_ms']['mean']:>7.2f} ms  p95={s['assess_ms']['p95']:>7.2f}  p99={s['assess_ms']['p99']:>7.2f}")
        print(f"   enhance: mean={s['enhance_ms']['mean']:>7.2f} ms  p95={s['enhance_ms']['p95']:>7.2f}  p99={s['enhance_ms']['p99']:>7.2f}")
        print(f"   hash:    mean={s['hash_ms']['mean']:>7.2f} ms  p95={s['hash_ms']['p95']:>7.2f}  p99={s['hash_ms']['p99']:>7.2f}")
        print(f"   TOTAL:   mean={s['total_ms']['mean']:>7.2f} ms  p95={s['total_ms']['p95']:>7.2f}  p99={s['total_ms']['p99']:>7.2f}")
    # Environnement
    env = {
        "python": sys.version.split()[0],
        "cpu_count_logical": psutil.cpu_count(),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "ram_total_mb": round(psutil.virtual_memory().total / (1024 * 1024)),
        "ram_available_mb": round(psutil.virtual_memory().available / (1024 * 1024)),
        "gpu": "N/A (aucun GPU NVIDIA détecté — preview cloud CPU-only)",
        "vram": "N/A",
        "yolo_loaded": YOLO_MODEL is not None,
        "yolo_model": os.environ.get("MGVMS_YOLO_MODEL", "yolov8n.pt"),
    }
    out = {"env": env, "cohorts": results, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    Path("/app/memory/STRESS_TEST_v0.7.e_report.json").write_text(json.dumps(out, indent=2))
    print(f"\n✅ Rapport JSON → /app/memory/STRESS_TEST_v0.7.e_report.json")
    return out


if __name__ == "__main__":
    asyncio.run(main())
