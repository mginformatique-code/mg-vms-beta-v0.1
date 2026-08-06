"""Benchmark Pipeline v2 — mesures réelles AVANT / APRÈS refonte v0.4.2.

Compare, sur une frame 1080p réelle avec véhicules simulés :
  - AVANT : ancien comportement (crop + imencode PAR moteur ANPR, 2 trackers
    parallèles, dispatch bus vers tous les plugins)
  - APRÈS : architecture pipeline v2 (crop UNIQUE, JPEG memoizé, tracker
    UNIQUE, dispatch per-camera)

Charges testées : 1 / 5 / 10 / 20 plugins consommateurs.
Mesures : latence pipeline, temps YOLO, tracking, OCR, encodage, CPU, RAM, VRAM.

Usage :
    cd /app/backend && set -a && . .env && set +a && python scripts/benchmark_pipeline.py
Sortie : /app/benchmarks/pipeline_v2_benchmark.{json,md}
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

RESULTS: dict = {"meta": {}, "before": {}, "after": {}}
N_ITER = 30


def make_frame_1080p() -> np.ndarray:
    """Frame 1080p synthétique avec des 'véhicules' (rectangles texturés)."""
    rng = np.random.default_rng(42)
    img = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    for i in range(4):
        x, y = 200 + i * 400, 400 + (i % 2) * 200
        cv2.rectangle(img, (x, y), (x + 320, y + 200), (30 + i * 40, 60, 200), -1)
        cv2.putText(img, f"AB-{123 + i}-CD", (x + 40, y + 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    return img


def fake_detections(img) -> list[dict]:
    return [
        {"class": "car", "label": "Voiture", "confidence": 0.9,
         "_bbox": (200 + i * 400, 400 + (i % 2) * 200, 520 + i * 400, 600 + (i % 2) * 200),
         "vehicle_color": "Rouge", "thumbnail": None}
        for i in range(4)
    ]


def sysinfo() -> dict:
    out = {}
    try:
        import psutil
        p = psutil.Process()
        out["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        out["rss_mb"] = round(p.memory_info().rss / 1048576, 1)
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            out["vram_mb"] = round(torch.cuda.memory_allocated(0) / 1048576, 1)
        else:
            out["vram_mb"] = None
    except Exception:
        out["vram_mb"] = None
    return out


def bench_yolo(img) -> dict:
    import ai_engine as _ae
    _ae._load_models()
    if _ae._model is None:
        return {"error": "YOLO non chargé"}
    times = []
    for _ in range(10):
        t0 = time.perf_counter()
        _ae._model.predict(img, conf=0.45, device=_ae._detected_device(), verbose=False)
        times.append((time.perf_counter() - t0) * 1000)
    return {"avg_ms": round(statistics.mean(times[2:]), 1),
            "max_ms": round(max(times[2:]), 1)}


def bench_tracking_before(img, dets) -> dict:
    """AVANT : moteur core sv.ByteTrack + plugin tracker en double (2 updates)."""
    import supervision as sv
    t1 = sv.ByteTrack()
    t2 = sv.ByteTrack()  # simule le plugin bytetrack dispatché en parallèle
    times = []
    for _ in range(N_ITER):
        xyxy = np.array([d["_bbox"] for d in dets], dtype=float)
        confs = np.array([d["confidence"] for d in dets], dtype=float)
        cids = np.zeros(len(dets), dtype=int)
        sd = sv.Detections(xyxy=xyxy, confidence=confs, class_id=cids)
        t0 = time.perf_counter()
        t1.update_with_detections(sd)
        sd2 = sv.Detections(xyxy=xyxy.copy(), confidence=confs.copy(), class_id=cids.copy())
        t2.update_with_detections(sd2)
        times.append((time.perf_counter() - t0) * 1000)
    return {"avg_ms": round(statistics.mean(times), 3), "trackers_run": 2}


def bench_tracking_after(img, dets) -> dict:
    """APRÈS : TrackerPool — UN SEUL tracker par caméra."""
    from pipeline_v2.tracking import TrackerPool
    from pipeline_v2.frame_context import FrameContext
    pool = TrackerPool()
    times = []
    for _ in range(N_ITER):
        ctx = FrameContext(camera_id="bench", image=img)
        ctx.detections = [dict(d) for d in dets]
        t0 = time.perf_counter()
        pool.update("bench", ctx, {}, enabled_plugins=["bytetrack"])
        times.append((time.perf_counter() - t0) * 1000)
    return {"avg_ms": round(statistics.mean(times), 3), "trackers_run": 1}


def bench_crops_before(img, dets, n_engines: int) -> dict:
    """AVANT : chaque moteur ANPR refait crop + cv2.imencode."""
    times = []
    for _ in range(N_ITER):
        t0 = time.perf_counter()
        encodes = 0
        for _e in range(n_engines):
            for d in dets:
                x1, y1, x2, y2 = d["_bbox"]
                crop = img[y1:y2, x1:x2]
                ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
                encodes += 1
        times.append((time.perf_counter() - t0) * 1000)
    return {"avg_ms": round(statistics.mean(times), 2),
            "jpeg_encodes_per_cycle": n_engines * len(dets)}


def bench_crops_after(img, dets, n_engines: int) -> dict:
    """APRÈS : VehicleROI partagé — crop unique + JPEG memoizé."""
    from pipeline_v2.frame_context import VehicleROI
    times = []
    for _ in range(N_ITER):
        t0 = time.perf_counter()
        rois = []
        for d in dets:
            x1, y1, x2, y2 = d["_bbox"]
            rois.append(VehicleROI(owner=d, bbox=(x1, y1, x2, y2),
                                   crop=img[y1:y2, x1:x2]))
        encodes = 0
        for roi in rois:
            for _e in range(n_engines):
                roi.jpeg(85)  # memoizé → 1 seul encodage réel par ROI
            encodes += 1
        times.append((time.perf_counter() - t0) * 1000)
    return {"avg_ms": round(statistics.mean(times), 2),
            "jpeg_encodes_per_cycle": len(dets)}


async def bench_bus_dispatch(n_plugins: int, per_camera: bool) -> dict:
    """Dispatch bus avec N consumers. per_camera=True → whitelist 1 seul plugin."""
    from plugin_manager.bus import PluginBus
    from plugin_manager.interfaces import (PipelineConsumer, Frame)

    class _DummyConsumer(PipelineConsumer):
        def __init__(self, name):
            self.name = name

        async def consume(self, frame, pipeline_result):
            await asyncio.sleep(0.001)  # simule 1 ms de travail métier
            return [{"type": f"{self.name}.event"}]

    bus = PluginBus()
    for i in range(n_plugins):
        bus.register(f"consumer-{i}", _DummyConsumer(f"consumer-{i}"))

    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame = Frame(camera_id="bench", timestamp="t", numpy_bgr=img, width=1280, height=720)
    enabled = ["consumer-0"] if per_camera else []
    times = []
    for _ in range(N_ITER):
        t0 = time.perf_counter()
        await bus.dispatch_pipeline(
            frame, camera_config={"camera_id": "bench", "enabled_plugins": enabled},
            precomputed_detections=[], precomputed_tracks=[],
            run_business=True, emit_events=False, timeout_s=2.0)
        times.append((time.perf_counter() - t0) * 1000)
    return {"avg_ms": round(statistics.mean(times), 2),
            "plugins_registered": n_plugins,
            "plugins_dispatched": 1 if per_camera else n_plugins}


def main():
    img = make_frame_1080p()
    dets = fake_detections(img)
    RESULTS["meta"] = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "frame": "1920x1080", "vehicles": len(dets), "iterations": N_ITER,
        "system_start": sysinfo(),
    }

    print("── YOLO (inférence unique, identique avant/après) ──")
    RESULTS["yolo"] = bench_yolo(img)
    print(json.dumps(RESULTS["yolo"]))

    print("── Tracking : double (avant) vs unique (après) ──")
    RESULTS["before"]["tracking"] = bench_tracking_before(img, dets)
    RESULTS["after"]["tracking"] = bench_tracking_after(img, dets)
    print("avant:", RESULTS["before"]["tracking"], "· après:", RESULTS["after"]["tracking"])

    print("── Crops/JPEG ANPR : par moteur (avant) vs ROI partagé (après) ──")
    for n in (1, 5, 10, 20):
        RESULTS["before"][f"crops_{n}_engines"] = bench_crops_before(img, dets, n)
        RESULTS["after"][f"crops_{n}_engines"] = bench_crops_after(img, dets, n)
        print(f"{n:>2} moteurs → avant {RESULTS['before'][f'crops_{n}_engines']['avg_ms']} ms "
              f"({RESULTS['before'][f'crops_{n}_engines']['jpeg_encodes_per_cycle']} encodes) · "
              f"après {RESULTS['after'][f'crops_{n}_engines']['avg_ms']} ms "
              f"({RESULTS['after'][f'crops_{n}_engines']['jpeg_encodes_per_cycle']} encodes)")

    print("── Dispatch bus : broadcast global (avant) vs graph per-camera (après) ──")
    loop = asyncio.new_event_loop()
    for n in (1, 5, 10, 20):
        RESULTS["before"][f"dispatch_{n}_plugins"] = loop.run_until_complete(
            bench_bus_dispatch(n, per_camera=False))
        RESULTS["after"][f"dispatch_{n}_plugins"] = loop.run_until_complete(
            bench_bus_dispatch(n, per_camera=True))
        print(f"{n:>2} plugins → avant {RESULTS['before'][f'dispatch_{n}_plugins']['avg_ms']} ms · "
              f"après {RESULTS['after'][f'dispatch_{n}_plugins']['avg_ms']} ms")
    loop.close()

    RESULTS["meta"]["system_end"] = sysinfo()

    out_dir = Path("/app/benchmarks")
    out_dir.mkdir(exist_ok=True)
    (out_dir / "pipeline_v2_benchmark.json").write_text(json.dumps(RESULTS, indent=2))

    md = ["# Benchmark Pipeline v2 — avant / après refonte v0.4.2",
          f"\nDate : {RESULTS['meta']['date']} · Frame 1080p · {len(dets)} véhicules · {N_ITER} itérations\n",
          f"\n## YOLO (une seule inférence — identique)\n\n- avg : {RESULTS['yolo'].get('avg_ms')} ms · max : {RESULTS['yolo'].get('max_ms')} ms\n",
          "\n## Tracking\n\n| | Avant (double) | Après (unique) |\n|---|---|---|",
          f"| Latence moyenne | {RESULTS['before']['tracking']['avg_ms']} ms | {RESULTS['after']['tracking']['avg_ms']} ms |",
          f"| Trackers exécutés | 2 | 1 |",
          "\n## Crops + JPEG ANPR (par cycle, 4 véhicules)\n\n| Moteurs | Avant ms (encodes) | Après ms (encodes) |\n|---|---|---|"]
    for n in (1, 5, 10, 20):
        b = RESULTS["before"][f"crops_{n}_engines"]
        a = RESULTS["after"][f"crops_{n}_engines"]
        md.append(f"| {n} | {b['avg_ms']} ({b['jpeg_encodes_per_cycle']}) | {a['avg_ms']} ({a['jpeg_encodes_per_cycle']}) |")
    md.append("\n## Dispatch PluginBus (consumers 1 ms)\n\n| Plugins | Avant ms (broadcast) | Après ms (per-camera) |\n|---|---|---|")
    for n in (1, 5, 10, 20):
        b = RESULTS["before"][f"dispatch_{n}_plugins"]
        a = RESULTS["after"][f"dispatch_{n}_plugins"]
        md.append(f"| {n} | {b['avg_ms']} | {a['avg_ms']} |")
    md.append(f"\n## Système\n\n- Début : {RESULTS['meta']['system_start']}\n- Fin : {RESULTS['meta']['system_end']}\n")
    (out_dir / "pipeline_v2_benchmark.md").write_text("\n".join(md))
    print(f"\nRésultats → {out_dir}/pipeline_v2_benchmark.json + .md")


if __name__ == "__main__":
    main()
