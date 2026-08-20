"""Heatmap — carte de densité des positions détectées (marketing/merchandising).

Accumule les positions (centre du bbox) des objets suivis dans une grille
normalisée, et publie un instantané périodique — pas besoin de modèle
dédié, s'appuie sur les tracks déjà produits par le pipeline.
"""
from __future__ import annotations
import time
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult


class HeatmapPlugin(PipelineConsumer):
    name = "heatmap"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._labels = set(cfg.get("target_labels") or ["person"])
        self._cols = max(1, int(cfg.get("grid_cols", 20)))
        self._rows = max(1, int(cfg.get("grid_rows", 12)))
        self._snapshot_interval_s = float(cfg.get("snapshot_interval_s", 60))
        self._grid = [[0] * self._cols for _ in range(self._rows)]
        self._last_snapshot = time.time()
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._labels = set(cfg.get("target_labels") or ["person"])
        self._cols = max(1, int(cfg.get("grid_cols", 20)))
        self._rows = max(1, int(cfg.get("grid_rows", 12)))
        self._snapshot_interval_s = float(cfg.get("snapshot_interval_s", 60))
        self._grid = [[0] * self._cols for _ in range(self._rows)]
        self._last_snapshot = time.time()
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        w, h = frame.width, frame.height
        if w and h:
            items = pipeline.tracks or pipeline.detections
            for it in items:
                label = getattr(it, "label", "?")
                if label not in self._labels:
                    continue
                x1, y1, x2, y2 = it.bbox
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                col = min(self._cols - 1, max(0, int((cx / w) * self._cols)))
                row = min(self._rows - 1, max(0, int((cy / h) * self._rows)))
                self._grid[row][col] += 1

        events = []
        now = time.time()
        if now - self._last_snapshot >= self._snapshot_interval_s:
            total = sum(sum(r) for r in self._grid)
            if total > 0:
                events.append({
                    "type": "heatmap.snapshot",
                    "severity": "info",
                    "message": f"Heatmap : {total} détection(s) accumulée(s) sur {self._snapshot_interval_s:.0f}s",
                    "data": {"grid": self._grid, "cols": self._cols, "rows": self._rows, "total": total},
                })
            self._grid = [[0] * self._cols for _ in range(self._rows)]
            self._last_snapshot = now
        return events

    async def on_unload(self) -> None:
        pass
