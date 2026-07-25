"""Plugin Tracking — ByteTrack (implémentation réelle via ultralytics.trackers)."""
from __future__ import annotations
import time
import numpy as np
from plugin_manager.interfaces import Tracker, Frame, TrackingResult, Track


class ByteTrackPlugin(Tracker):
    """ByteTrack — utilise toutes les détections (haute + basse conf) pour un tracking robuste."""

    name = "bytetrack"
    version = "1.0.0"

    def __init__(self):
        self._tracker = None
        self._frame_id = 0

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install ultralytics")
            return
        self._init_tracker()
        self._ctx.set_state("ready")

    def _init_tracker(self):
        """Instancie le BYTETracker avec les paramètres de la config."""
        from types import SimpleNamespace
        from ultralytics.trackers.byte_tracker import BYTETracker
        cfg = self._ctx.config or {}
        args = SimpleNamespace(
            track_high_thresh=float(cfg.get("track_high_thresh", 0.5)),
            track_low_thresh=float(cfg.get("track_low_thresh", 0.1)),
            new_track_thresh=float(cfg.get("new_track_thresh", 0.6)),
            track_buffer=int(cfg.get("max_age_frames", 30)),
            match_thresh=float(cfg.get("iou_threshold", 0.8)),
            fuse_score=True,
        )
        try:
            self._tracker = BYTETracker(args, frame_rate=int(cfg.get("frame_rate", 25)))
            self._frame_id = 0
        except Exception as e:
            self._ctx.log.warning(f"bytetrack init failed: {e}")
            self._tracker = None

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def track(self, frame: Frame, detections: list) -> TrackingResult:
        if self._tracker is None:
            return TrackingResult(tracks=[], timing_ms=0)

        t0 = time.perf_counter()
        # Convertit les Detection[] vers le format numpy attendu par BYTETracker :
        # [x1, y1, x2, y2, conf, cls]
        if not detections:
            self._frame_id += 1
            return TrackingResult(tracks=[], timing_ms=int((time.perf_counter() - t0) * 1000))

        # Map label → cls_id (stable via hash pour PoC)
        cls_map: dict = {}
        def _cls_id(label):
            if label not in cls_map:
                cls_map[label] = len(cls_map)
            return cls_map[label]

        rows = []
        for d in detections:
            x1, y1, x2, y2 = d.bbox
            rows.append([float(x1), float(y1), float(x2), float(y2),
                         float(d.confidence), float(_cls_id(d.label))])
        dets_arr = np.array(rows, dtype=np.float32)

        # Construit le "results" object attendu par BYTETracker.update
        # (adaptateur inspiré de ultralytics.trackers.utils.matching)
        try:
            from ultralytics.engine.results import Boxes
            import torch
            boxes_tensor = torch.from_numpy(dets_arr[:, :6])  # xyxy + conf + cls
            orig_shape = (frame.height or 480, frame.width or 640)
            boxes = Boxes(boxes_tensor, orig_shape)

            # Emballage minimal type "Results"
            class _MockResults:
                def __init__(self, boxes, orig_shape):
                    self.boxes = boxes
                    self.orig_shape = orig_shape
                    self.conf = boxes.conf
                    self.xywh = boxes.xywh
                    self.cls = boxes.cls
                    self.xyxy = boxes.xyxy

            mock = _MockResults(boxes, orig_shape)
            # BYTETracker.update signature moderne : (results, image)
            tracks_arr = self._tracker.update(mock, None)
            self._frame_id += 1
        except Exception as e:
            self._ctx.log.warning(f"bytetrack update failed: {e}")
            return TrackingResult(tracks=[], timing_ms=int((time.perf_counter() - t0) * 1000))

        # tracks_arr : ndarray [n, 8] → [x1,y1,x2,y2, id, conf, cls, idx]
        inv_cls = {v: k for k, v in cls_map.items()}
        out = []
        if tracks_arr is not None and len(tracks_arr) > 0:
            for t in tracks_arr:
                cls_id = int(t[6]) if len(t) > 6 else 0
                out.append(Track(
                    track_id=str(int(t[4])),
                    label=inv_cls.get(cls_id, "?"),
                    confidence=float(t[5]) if len(t) > 5 else 0.0,
                    bbox=(float(t[0]), float(t[1]), float(t[2]), float(t[3])),
                    age=1,
                ))
        return TrackingResult(tracks=out, timing_ms=int((time.perf_counter() - t0) * 1000))

    async def on_unload(self) -> None:
        self._tracker = None
