#!/usr/bin/env python3
"""Local code-level repro for v0.4.1 ANPR whitelist crash path."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
sys.path.insert(0, "/app/backend")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import ai_engine  # noqa: E402


def main():
    # Avoid heavyweight model loading; this isolates the whitelist skip branch.
    ai_engine._load_models = lambda: None
    ai_engine._model = None
    ai_engine._alpr = None
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", img)
    assert ok
    try:
        result = ai_engine._analyze_frame("demo-cam-002", encoded.tobytes(), ["yolo-detection", "bytetrack"])
        print(json.dumps({"ok": True, "result_keys": sorted(result.keys()), "timings": result.get("timings")}, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "exception_type": type(exc).__name__, "exception": str(exc)}, indent=2))
        raise


if __name__ == "__main__":
    main()