"""Retail Suspicious Behavior — comportement suspect en zone commerce.

Phase 1 du chantier anti-vol MG-VMS. Détecte, par personne trackée :
  1a. la présence prolongée (dwell-time) dans une zone (rayon) ;
  1b. les passages répétés dans cette zone sur une fenêtre glissante ;
  1c. (optionnel, désactivé par défaut) une trajectoire erratique.

S'appuie uniquement sur les tracks déjà produits par le cœur IA (YOLO +
TrackerPool, `precomputed_tracks`) — aucun modèle IA dédié n'est requis pour
ce scénario (voir plan Phase 1). Contrairement à une première hypothèse, il
n'est PAS nécessaire d'avoir les plugins `yolo-detection`/`bytetrack` dans
`enabled_plugins` : la détection/le tracking sont core, gérés par
`detect_enabled` sur la caméra, indépendamment de ce plugin. Seul ce plugin
lui-même doit être dans `enabled_plugins` pour que `consume()` soit appelé.

Un plugin est un singleton partagé par toutes les caméras qui l'activent
(sa config est globale, pas par caméra) — tout l'état interne est donc
indexé par `(camera_id, track_id)`, jamais par `track_id` seul, pour ne
pas mélanger deux caméras dont les track_id ByteTrack redémarrent à 1.
"""
from __future__ import annotations

import time
from collections import deque

from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult

DEFAULT_ZONE_CFG = {
    "polygon": None,  # None/vide = frame entière
    "dwell_warning_s": 60,
    "dwell_critical_s": 180,
    "visits_threshold": 3,
    "visits_window_s": 300,
    "erratic_path_enabled": False,
}

RE_ALERT_COOLDOWN_S = 60  # ré-émission d'un même type d'event pour un même track
POSITIONS_WINDOW_S = 60   # fenêtre d'historique de position (pour 1c)
# Grâce avant de purger un track absent de `pipeline.tracks` sur UNE frame —
# ByteTrack peut perdre puis retrouver le même track_id sur 1-2 frames (occlusion,
# mouvement rapide) ; sans ce délai, `total_dwell_s`/`visit_ends` étaient remis à
# zéro à la moindre absence d'une frame, empêchant en pratique le dwell-time et
# les passages répétés de jamais s'accumuler sur un flux réel.
TRACK_PURGE_GRACE_S = 5


def _point_in_polygon(pt, poly):
    """Ray-casting — pt et poly en coordonnées relatives 0..1."""
    x, y = pt
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def _new_track_state():
    return {
        "inside_since": None,
        "total_dwell_s": 0.0,
        "visit_ends": [],       # timestamps de fin de visite (fenêtre glissante)
        "positions": deque(),   # (ts, cx, cy) en pixels, pour 1c
        "last_seen": 0.0,
        "last_alert_at": {},    # event_type -> timestamp du dernier envoi
    }


class RetailSuspiciousBehaviorPlugin(PipelineConsumer):
    name = "retail-suspicious-behavior"
    version = "1.0.0"

    def __init__(self):
        self._tracks: dict[tuple, dict] = {}
        self._zones: dict[str, dict] = {}

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._zones = dict((ctx.config or {}).get("zones") or {})
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._zones = dict((new_config or {}).get("zones") or {})
        self._ctx.set_state("ready")

    def _zone_cfg(self, camera_id: str) -> dict:
        cfg = dict(DEFAULT_ZONE_CFG)
        cfg.update(self._zones.get(camera_id) or {})
        return cfg

    def _try_alert(self, st: dict, ev_type: str, now: float) -> bool:
        """True si ce type d'event n'a pas été émis pour ce track depuis
        RE_ALERT_COOLDOWN_S — évite de renvoyer le même event à chaque frame
        tant que la condition reste vraie."""
        last = st["last_alert_at"].get(ev_type, 0.0)
        if now - last < RE_ALERT_COOLDOWN_S:
            return False
        st["last_alert_at"][ev_type] = now
        return True

    def _check_erratic_path(self, track_id: str, camera_id: str, st: dict, now: float):
        pts = list(st["positions"])
        if len(pts) < 5:
            return None
        path_len = 0.0
        for (_, x0, y0), (_, x1, y1) in zip(pts, pts[1:]):
            path_len += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        (_, sx, sy), (_, ex, ey) = pts[0], pts[-1]
        direct = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
        if path_len < 40:  # trop peu de mouvement pour juger (px)
            return None
        ratio = direct / (path_len + 1e-6)
        if ratio >= 0.25:
            return None
        if not self._try_alert(st, "retail.erratic_path", now):
            return None
        return {
            "type": "retail.erratic_path",
            "severity": "warning",
            "message": f"Trajectoire erratique — track {track_id}",
            "data": {"track_id": track_id, "camera_id": camera_id, "path_ratio": round(ratio, 2)},
        }

    def live_state(self, camera_id: str) -> dict:
        """État courant par track pour cette caméra — lu par l'overlay live du
        Camera Center (`GET /api/plugins/retail-suspicious-behavior/state/{camera_id}`,
        ou injecté dans le broadcast `ai_detections`). Snapshot en mémoire du
        cycle en cours, pas une source persistée — pas de garantie de
        fraîcheur au-delà du cycle IA courant."""
        now = time.time()
        cfg = self._zone_cfg(camera_id)
        out = {}
        for (cid, tid), st in self._tracks.items():
            if cid != camera_id:
                continue
            dwell = (now - st["inside_since"]) if st["inside_since"] is not None else 0.0
            out[tid] = {
                "dwell_s": int(dwell),
                "visits": len(st["visit_ends"]),
                "loitering": dwell >= cfg["dwell_warning_s"],
                "critical": dwell >= cfg["dwell_critical_s"],
                "repeated_visits": len(st["visit_ends"]) >= cfg["visits_threshold"],
            }
        return out

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        now = time.time()
        cfg = self._zone_cfg(frame.camera_id)
        polygon = cfg.get("polygon") or None
        events = []
        seen = set()

        for t in pipeline.tracks:
            if t.label != "person":
                continue
            key = (frame.camera_id, t.track_id)
            seen.add(key)
            st = self._tracks.setdefault(key, _new_track_state())
            st["last_seen"] = now

            x1, y1, x2, y2 = t.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if polygon and frame.width and frame.height:
                inside = _point_in_polygon((cx / frame.width, cy / frame.height), polygon)
            else:
                inside = True  # pas de polygone configuré = frame entière

            st["positions"].append((now, cx, cy))
            while st["positions"] and now - st["positions"][0][0] > POSITIONS_WINDOW_S:
                st["positions"].popleft()

            if inside:
                if st["inside_since"] is None:
                    st["inside_since"] = now
                dwell = now - st["inside_since"]

                if dwell >= cfg["dwell_warning_s"] and self._try_alert(st, "retail.loitering", now):
                    severity = "critical" if dwell >= cfg["dwell_critical_s"] else "warning"
                    events.append({
                        "type": "retail.loitering",
                        "severity": severity,
                        "message": f"Présence prolongée ({int(dwell)}s) — track {t.track_id}",
                        "data": {"track_id": t.track_id, "camera_id": frame.camera_id, "dwell_s": int(dwell)},
                    })

                if cfg.get("erratic_path_enabled"):
                    ev = self._check_erratic_path(t.track_id, frame.camera_id, st, now)
                    if ev:
                        events.append(ev)
            else:
                if st["inside_since"] is not None:
                    st["total_dwell_s"] += now - st["inside_since"]
                    st["visit_ends"].append(now)
                    st["inside_since"] = None

                window = cfg["visits_window_s"]
                st["visit_ends"] = [ts for ts in st["visit_ends"] if now - ts <= window]
                if len(st["visit_ends"]) >= cfg["visits_threshold"] and self._try_alert(st, "retail.repeated_visits", now):
                    events.append({
                        "type": "retail.repeated_visits",
                        "severity": "warning",
                        "message": f"Passages répétés ({len(st['visit_ends'])} en {window}s) — track {t.track_id}",
                        "data": {
                            "track_id": t.track_id, "camera_id": frame.camera_id,
                            "visits": len(st["visit_ends"]), "window_s": window,
                        },
                    })

        # Purge des tracks disparus (même caméra uniquement — ne touche pas
        # l'état des autres caméras partageant ce même singleton). Grâce de
        # TRACK_PURGE_GRACE_S avant purge réelle (voir constante ci-dessus).
        for key in list(self._tracks.keys()):
            if key[0] == frame.camera_id and key not in seen:
                if now - self._tracks[key]["last_seen"] > TRACK_PURGE_GRACE_S:
                    self._tracks.pop(key, None)

        return events

    async def on_unload(self) -> None:
        pass
