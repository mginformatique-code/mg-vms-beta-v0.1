"""Focused verification for iter28 ANPR lazy thumbnail performance regression.

This is a test artifact only; it does not modify product code.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


BACKEND = Path("/app/backend")
sys.path.insert(0, str(BACKEND))
for key in ("MONGO_URL", "DB_NAME", "JWT_SECRET"):
    if not os.environ.get(key):
        env_path = BACKEND / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith(key + "="):
                    os.environ[key] = line.split("=", 1)[1].strip().strip('"').strip("'")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import ai_engine as AI  # noqa: E402


def record(results, name, passed, detail=""):
    results.append({"name": name, "passed": bool(passed), "detail": detail})


async def main():
    results = []

    # 1) Direct contract: _analyze_frame returns numpy image and no eager frame_thumb.
    img = np.zeros((720, 1280, 3), dtype="uint8")
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    old_load, old_model, old_alpr = AI._load_models, AI._model, AI._alpr
    try:
        AI._load_models = MagicMock()
        AI._model = MagicMock()
        AI._model.predict = MagicMock(return_value=[MagicMock(boxes=[])])
        AI._alpr = None
        r = AI._analyze_frame("iter28-test", buf.tobytes())
        record(
            results,
            "_analyze_frame_no_eager_frame_thumb",
            "_img_bgr" in r and "frame_thumb" not in r,
            f"has_img_bgr={'_img_bgr' in r}, has_frame_thumb={'frame_thumb' in r}",
        )
    finally:
        AI._load_models, AI._model, AI._alpr = old_load, old_model, old_alpr

    # 2) Helper contract: memoized, None-safe, HD output.
    original_jpeg = AI._jpeg_data_uri
    try:
        wrapped = MagicMock(wraps=original_jpeg)
        AI._jpeg_data_uri = wrapped
        result = {"_img_bgr": np.full((720, 1280, 3), 128, dtype="uint8")}
        t1 = AI._ensure_frame_thumb(result)
        t2 = AI._ensure_frame_thumb(result)
        record(results, "_ensure_frame_thumb_memoized", t1 == t2 and wrapped.call_count == 1, f"call_count={wrapped.call_count}")
        none_result = {"_img_bgr": None}
        record(results, "_ensure_frame_thumb_none_safe", AI._ensure_frame_thumb(none_result) is None, f"frame_thumb={none_result.get('frame_thumb')!r}")
        hd_result = {"_img_bgr": np.full((1080, 1920, 3), 128, dtype="uint8")}
        thumb = AI._ensure_frame_thumb(hd_result)
        decoded = Image.open(io.BytesIO(base64.b64decode(thumb.split(",", 1)[1])))
        record(results, "_ensure_frame_thumb_hd_1280", decoded.size == (1280, 720), f"size={decoded.size}")
    finally:
        AI._jpeg_data_uri = original_jpeg

    # 3) Full pipeline edge: no-event scenario evaluation must not force thumbnail encoding.
    # This currently exposes the remaining user-visible performance regression if it fails.
    old_is_armed = AI._is_armed
    old_rules = AI._get_scenario_rules
    old_ensure = AI._ensure_frame_thumb
    try:
        AI._is_armed = AsyncMock(return_value=True)
        AI._get_scenario_rules = AsyncMock(return_value=AI.DEFAULT_SCENARIOS)
        AI._ensure_frame_thumb = MagicMock(return_value="thumb")
        await AI._evaluate_scenarios(
            {"id": "demo-cam-002", "name": "Caméra Démo Trafic", "site_id": "", "site_name": ""},
            {"detections": [], "motion_pct": 0.0},
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        record(
            results,
            "_evaluate_scenarios_no_event_no_thumbnail_encode",
            AI._ensure_frame_thumb.call_count == 0,
            f"ensure_frame_thumb_call_count={AI._ensure_frame_thumb.call_count} (expected 0 when no scenario/event is emitted)",
        )
    finally:
        AI._is_armed = old_is_armed
        AI._get_scenario_rules = old_rules
        AI._ensure_frame_thumb = old_ensure

    print(json.dumps({"results": results}, indent=2))
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())