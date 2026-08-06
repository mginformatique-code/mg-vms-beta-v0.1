"""Pipeline v2 · TrackingStage — UN SEUL tracker par caméra, source unique de TrackID.

Les plugins de tracking (bytetrack / botsort / deepsort / ocsort / strongsort)
ne sont PLUS des pipelines indépendants : ils deviennent des choix
d'implémentation du TrackingStage. Le pool instancie UN tracker par caméra
(isolation stricte — aucun état partagé entre caméras) et produit l'unique
ensemble de TrackID consommé par tous les stages/plugins aval.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("pipeline_v2.tracking")

# Plugins tracker connus → convertis en implémentations du TrackingStage.
KNOWN_TRACKER_PLUGINS = ("bytetrack", "botsort", "deepsort", "ocsort", "strongsort")
# Algorithmes réellement implémentés par le stage core.
SUPPORTED_ALGOS = {"bytetrack", "botsort"}


def resolve_algo(enabled_plugins: Optional[list]) -> tuple[str, str, Optional[str]]:
    """Retourne (algo_demandé, algo_effectif, warning_ou_None).

    v0.5.6 P0-3 · Le fallback silencieux vers ByteTrack était trompeur pour
    l'opérateur. Désormais :

    * Aucun tracker plugin activé (whitelist standard) → bytetrack (défaut
      historique) sans warning : c'est le comportement documenté.
    * Un tracker plugin explicitement demandé mais non implémenté (deepsort,
      ocsort, strongsort) → on continue avec bytetrack MAIS on retourne un
      message d'avertissement clair qui sera loggué + exposé côté API
      (`inspector`) pour surfacer l'écart dans l'UI et éviter que
      l'opérateur croie que DeepSORT tourne alors que ByteTrack est actif.
    """
    requested = "bytetrack"
    for name in (enabled_plugins or []):
        if name in KNOWN_TRACKER_PLUGINS:
            requested = name
            break
    if requested in SUPPORTED_ALGOS:
        return requested, requested, None
    # Tracker demandé mais pas implémenté par le core → warning explicite.
    warning = (
        f"Tracker '{requested}' non implémenté par le core "
        f"(implémentés: {sorted(SUPPORTED_ALGOS)}). "
        f"Fallback vers 'bytetrack'. Retirez ce plugin de la whitelist "
        f"ou activez un tracker supporté pour supprimer cet avertissement."
    )
    logger.warning("[Tracker] %s", warning)
    return requested, "bytetrack", warning


class TrackerPool:
    """Un tracker par caméra — instances jamais partagées entre caméras."""

    def __init__(self):
        # camera_id -> {"algo": str, "tracker": obj}
        self._instances: dict[str, dict] = {}

    def reset(self, camera_id: Optional[str] = None) -> None:
        if camera_id:
            self._instances.pop(camera_id, None)
        else:
            self._instances.clear()

    def describe(self) -> dict:
        return {cid: {"algo": inst["algo"]} for cid, inst in self._instances.items()}

    def _get_tracker(self, camera_id: str, algo: str, cfg: dict):
        inst = self._instances.get(camera_id)
        if inst and inst["algo"] == algo:
            return inst["tracker"]
        tracker = self._create(algo, cfg)
        if tracker is None and algo != "bytetrack":
            algo, tracker = "bytetrack", self._create("bytetrack", cfg)
        self._instances[camera_id] = {"algo": algo, "tracker": tracker}
        return tracker

    def _create(self, algo: str, cfg: dict):
        try:
            if algo == "botsort":
                from types import SimpleNamespace
                from ultralytics.trackers.bot_sort import BOTSORT
                args = SimpleNamespace(
                    track_high_thresh=float(cfg.get("track_thresh", 0.25)) + 0.25,
                    track_low_thresh=0.1,
                    new_track_thresh=0.6,
                    track_buffer=int(cfg.get("track_buffer", 60)),
                    match_thresh=float(cfg.get("match_thresh", 0.85)),
                    gmc_method="sparseOptFlow",
                    proximity_thresh=0.5,
                    appearance_thresh=0.25,
                    with_reid=False,
                    fuse_score=True,
                )
                return BOTSORT(args, frame_rate=25)
            import supervision as sv
            return sv.ByteTrack(
                track_activation_threshold=float(cfg.get("track_thresh", 0.25)),
                lost_track_buffer=int(cfg.get("track_buffer", 60)),
                minimum_matching_threshold=float(cfg.get("match_thresh", 0.85)),
            )
        except Exception as e:
            logger.warning("tracker %s init failed: %s", algo, e)
            return None

    def update(self, camera_id: str, ctx, cfg: dict,
               enabled_plugins: Optional[list] = None) -> dict:
        """Met à jour le tracker UNIQUE de la caméra et attache les track_id.

        Modifie ``ctx.detections`` en place (champ ``track_id``) et remplit
        ``ctx.tracks``. Retourne des métadonnées ({algo, tracked}).
        """
        requested, effective, warning = resolve_algo(enabled_plugins)
        meta = {"algo_requested": requested, "algo_effective": effective, "tracked": 0}
        if warning:
            meta["warning"] = warning
        detections = ctx.detections
        if not detections:
            return meta
        tracker = self._get_tracker(camera_id, effective, cfg)
        if tracker is None:
            return meta
        try:
            import numpy as np
            xyxy = np.array([d["_bbox"] for d in detections], dtype=float)
            confs = np.array([d["confidence"] for d in detections], dtype=float)
            class_ids = np.array([hash(d["class"]) % 1000 for d in detections], dtype=int)
            if effective == "botsort":
                tracks_map = self._update_ultralytics(tracker, xyxy, confs, class_ids, ctx)
            else:
                tracks_map = self._update_supervision(tracker, xyxy, confs, class_ids)
        except Exception:
            logger.exception("tracking update failed (%s) — cycle sans tracks", effective)
            return meta

        for d in detections:
            d["track_id"] = tracks_map.get(tuple(d["_bbox"]))
        ctx.tracks = [
            {"track_id": d["track_id"], "label": d["class"],
             "confidence": d["confidence"], "bbox": tuple(d["_bbox"])}
            for d in detections if d.get("track_id") is not None
        ]
        meta["tracked"] = len(ctx.tracks)
        return meta

    @staticmethod
    def _update_supervision(tracker, xyxy, confs, class_ids) -> dict:
        import supervision as sv
        sv_dets = sv.Detections(xyxy=xyxy, confidence=confs, class_id=class_ids)
        tracked = tracker.update_with_detections(sv_dets)
        out = {}
        for i, tid in enumerate(tracked.tracker_id if tracked.tracker_id is not None else []):
            if tid is None:
                continue
            out[tuple(int(v) for v in tracked.xyxy[i])] = int(tid)
        return out

    @staticmethod
    def _update_ultralytics(tracker, xyxy, confs, class_ids, ctx) -> dict:
        import numpy as np
        import torch
        from ultralytics.engine.results import Boxes
        rows = np.concatenate(
            [xyxy, confs.reshape(-1, 1), class_ids.reshape(-1, 1)], axis=1
        ).astype(np.float32)
        orig_shape = (ctx.height or 480, ctx.width or 640)
        boxes = Boxes(torch.from_numpy(rows), orig_shape)

        class _MockResults:
            def __init__(self, b, s):
                self.boxes = b
                self.orig_shape = s
                self.conf = b.conf
                self.xywh = b.xywh
                self.cls = b.cls
                self.xyxy = b.xyxy

        tracks_arr = tracker.update(_MockResults(boxes, orig_shape), ctx.image)
        out = {}
        if tracks_arr is not None and len(tracks_arr) > 0:
            for t in tracks_arr:
                out[tuple(int(v) for v in t[:4])] = int(t[4])
        return out


# Singleton — source unique de tracking pour tout le backend
tracker_pool = TrackerPool()
