"""Pipeline v2 · Camera State Fusion — état caméra unifié multi-signaux.

Mandat v0.8-rc6 (FEATURE FREEZE · Stabilisation Sprint 3 · P0) :

    Un état caméra ne doit JAMAIS provenir d'une source unique.
    Une caméra qui produit des frames RTSP ne peut jamais être "Offline"
    même si le probe go2rtc timeout.

Fusion de 4 signaux indépendants :

    1. signal_frame_source     — worker RTSP ffmpeg produit des frames récentes
    2. signal_pipeline_activity — inspector a des records < 30 s
    3. signal_go2rtc_stream    — go2rtc registered + bytes_recv > 0
    4. signal_tcp_reachable    — TCP port RTSP ouvert (peer alive)

Règles de fusion (par ordre de force décroissante) :

    * ONLINE  si signal_frame_source == positive       (frames fraîches)
              OU signal_pipeline_activity == positive (traite activement)
    * DEGRADED si tcp_reachable == positive mais pas de frame
              (caméra "vue" côté réseau mais pipeline pas alimenté)
    * OFFLINE  si TOUS les signaux négatifs

Aucune écriture Mongo — module PUR (utilitaire). L'appelant décide s'il
persiste ou non le résultat.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("pipeline_v2.camera_state")


@dataclass
class Signal:
    """Résultat d'un capteur individuel."""
    name: str
    positive: bool
    detail: str = ""
    measured_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"name": self.name, "positive": self.positive, "detail": self.detail}


@dataclass
class FusedState:
    """État agrégé multi-signaux."""
    camera_id: str
    status: str                  # "online" | "degraded" | "offline"
    confidence: int              # 0..100 (proportion signaux positifs)
    signals: list[Signal]
    reasons: list[str]
    computed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "status": self.status,
            "confidence": self.confidence,
            "signals": [s.to_dict() for s in self.signals],
            "reasons": self.reasons,
            "computed_at": self.computed_at,
        }


# ═════════════════════════════════════════════════════════════════════
# Capteurs individuels (chacun retourne un Signal, jamais None)
# ═════════════════════════════════════════════════════════════════════
def check_frame_source(camera_id: str, max_frame_age_sec: float = 10.0) -> Signal:
    """Le worker RTSP (frame_source.py) produit-il des frames récentes ?"""
    try:
        import frame_source as _fs
        w = _fs._workers.get(camera_id)
        if not w:
            return Signal("frame_source", False, "aucun worker actif")
        if not (w.reader_thread and w.reader_thread.is_alive()):
            return Signal("frame_source", False, "thread reader mort")
        if w.latest_ts == 0.0:
            return Signal("frame_source", False, "aucune frame encore produite")
        age = time.monotonic() - w.latest_ts
        if age > max_frame_age_sec:
            return Signal("frame_source", False,
                           f"dernière frame trop vieille ({age:.1f}s > {max_frame_age_sec}s)")
        return Signal("frame_source", True,
                       f"frame fraîche à {age:.1f}s (produced={w.frames_produced})")
    except Exception as e:
        return Signal("frame_source", False, f"erreur: {type(e).__name__}")


def check_pipeline_activity(camera_id: str, max_age_sec: float = 30.0) -> Signal:
    """L'inspector a-t-il enregistré des stages récents pour cette caméra ?"""
    try:
        from pipeline_v2.inspector import inspector
        stages = inspector._cameras.get(camera_id) or {}
        if not stages:
            return Signal("pipeline_activity", False, "inspector vide pour cette caméra")
        # Cherche le stage le plus récent (max ts dans window)
        latest_ts = 0.0
        for s in stages.values():
            if s.window:
                latest_ts = max(latest_ts, s.window[-1][0])
        if latest_ts == 0.0:
            return Signal("pipeline_activity", False, "aucun record dans window")
        age = time.time() - latest_ts
        if age > max_age_sec:
            return Signal("pipeline_activity", False,
                           f"dernier record trop vieux ({age:.1f}s)")
        return Signal("pipeline_activity", True,
                       f"stage récent à {age:.1f}s")
    except Exception as e:
        return Signal("pipeline_activity", False, f"erreur: {type(e).__name__}")


async def check_go2rtc_stream(camera_id: str) -> Signal:
    """go2rtc a-t-il le stream registered avec du trafic ?"""
    try:
        from streaming import _stream_name, _stream_bytes_recv, _probe_last_bytes
        name = _stream_name(camera_id)
        bytes_recv = await _stream_bytes_recv(name)
        if bytes_recv == 0:
            return Signal("go2rtc_stream", False, "producteur idle (0 octet)")
        prev = _probe_last_bytes.get(camera_id)
        if prev is not None and bytes_recv == prev:
            return Signal("go2rtc_stream", False,
                           "producteur gelé (bytes_recv stagne)")
        return Signal("go2rtc_stream", True,
                       f"bytes_recv={bytes_recv} (progresse)")
    except Exception as e:
        return Signal("go2rtc_stream", False, f"erreur: {type(e).__name__}")


async def check_tcp_reachable(cam: dict) -> Signal:
    """La caméra répond-elle sur son port RTSP (TCP handshake) ?"""
    try:
        from streaming import _camera_tcp_target, _tcp_check
        target = _camera_tcp_target(cam)
        if target is None:
            return Signal("tcp_reachable", False, "aucune IP connue")
        host, port = target
        ok = await asyncio.to_thread(_tcp_check, host, port, 2.0)
        if ok:
            return Signal("tcp_reachable", True, f"{host}:{port} accepte TCP")
        return Signal("tcp_reachable", False, f"{host}:{port} refuse ou timeout")
    except Exception as e:
        return Signal("tcp_reachable", False, f"erreur: {type(e).__name__}")


# ═════════════════════════════════════════════════════════════════════
# Fusion principale
# ═════════════════════════════════════════════════════════════════════
async def fuse_camera_state(cam: dict,
                             check_network: bool = True,
                             pipeline_activity: Optional[dict] = None) -> FusedState:
    """Calcule l'état caméra en fusionnant tous les signaux disponibles.

    Args:
        cam       : document caméra Mongo (dict avec au moins `id`).
        check_network : si False, saute go2rtc + TCP (utile en tests
                        offline sans réseau).
        pipeline_activity : v3.24 · signal "pipeline actif" précalculé côté
                        API via pipeline_snapshot.get_snapshot()["camera_activity"]
                        (format ``{"positive": bool, "detail": str}``). Permet
                        à l'appelant de fournir ce signal sans importer
                        pipeline_v2.inspector — utile une fois le pipeline
                        scindé en process séparé (voir pipeline_snapshot.py).
                        Si omis, repli sur l'import direct historique
                        (check_pipeline_activity) — préserve la compatibilité
                        des autres appelants/tests.
    """
    camera_id = cam["id"]
    signals: list[Signal] = []

    # Signaux locaux (rapides, pas de I/O réseau)
    signals.append(check_frame_source(camera_id))
    if pipeline_activity is not None:
        signals.append(Signal("pipeline_activity",
                               bool(pipeline_activity.get("positive")),
                               str(pipeline_activity.get("detail") or "")))
    else:
        signals.append(check_pipeline_activity(camera_id))

    # Signaux réseau (opt-out pour tests)
    if check_network:
        try:
            signals.append(await check_go2rtc_stream(camera_id))
        except Exception as e:
            signals.append(Signal("go2rtc_stream", False, f"exc: {type(e).__name__}"))
        try:
            signals.append(await check_tcp_reachable(cam))
        except Exception as e:
            signals.append(Signal("tcp_reachable", False, f"exc: {type(e).__name__}"))

    return _apply_rules(camera_id, signals)


def _apply_rules(camera_id: str, signals: list[Signal]) -> FusedState:
    """Applique les règles de décision documentées en tête de module."""
    by_name = {s.name: s for s in signals}
    fs = by_name.get("frame_source")
    pa = by_name.get("pipeline_activity")
    tcp = by_name.get("tcp_reachable")

    reasons: list[str] = []
    # ── Règle 1 : frame_source positive OU pipeline_activity positive → ONLINE
    if (fs and fs.positive) or (pa and pa.positive):
        if fs and fs.positive:
            reasons.append(f"frame_source ok · {fs.detail}")
        if pa and pa.positive:
            reasons.append(f"pipeline actif · {pa.detail}")
        status = "online"
    # ── Règle 2 : TCP OK mais aucune frame → DEGRADED
    elif tcp and tcp.positive:
        reasons.append(f"TCP joignable mais pas de frame · {tcp.detail}")
        status = "degraded"
    # ── Règle 3 : tout est négatif → OFFLINE
    else:
        for s in signals:
            if not s.positive:
                reasons.append(f"{s.name} ko · {s.detail}")
        status = "offline"

    pos = sum(1 for s in signals if s.positive)
    total = max(1, len(signals))
    confidence = int(round(100 * pos / total))
    return FusedState(camera_id=camera_id, status=status,
                       confidence=confidence, signals=signals, reasons=reasons)
