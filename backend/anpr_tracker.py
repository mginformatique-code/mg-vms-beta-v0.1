"""MG-VMS v0.3 — Accumulateur ANPR par track ByteTrack.

**Contexte** : L'ancien ANPR image-par-image émettait un événement dès
qu'une plaque était lue (avec un cache de 8s par ``(camera_id, plate_text)``
pour éviter les doublons). Résultat :

- **Véhicules stationnés** : OK, la première lecture nette suffit.
- **Véhicules en mouvement** : ~1 seule tentative de lecture (au 1er passage
  dans le champ) → si l'image est floue ou l'angle mauvais, plaque perdue.

**Nouveau design v0.3** — accumulateur par ``track_id`` ByteTrack :

1. Chaque véhicule détecté a un ``track_id`` stable (ByteTrack).
2. À chaque frame où on tente une lecture, on **ajoute la lecture au tracker**
   (``record_reading``).
3. Le tracker maintient une machine à états par véhicule :

   ::

       ENTERED  → PRESENT (>= min_readings)  → LEFT (track disparu N cycles)
                                    │
                                    └─→ émet ÉVÉNEMENT UNIQUE :
                                        meilleur reading (consensus + confiance)

4. **Anti-doublons** : un seul événement par véhicule tant qu'il reste dans
   la scène ; nouvel événement si le véhicule est vraiment sorti ET revient
   (nouveau ``track_id``).

Cette architecture retrouve la fiabilité de l'ancienne version sur véhicules
en mouvement (plusieurs tentatives OCR par voiture) **sans spammer** les
véhicules stationnés (1 seul événement à l'entrée).
"""
from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("anpr-tracker")

# ──────────────────────────────────────────────────────────────────────
# Paramètres par défaut — override via env / config runtime
# ──────────────────────────────────────────────────────────────────────
DEFAULT_MIN_READINGS = 1          # nb min de lectures avant émission
DEFAULT_LOST_CYCLES = 4           # nb de cycles sans re-voir le track avant "LEFT"
DEFAULT_MIN_CONFIDENCE = 0.55     # OCR retenu pour consensus
DEFAULT_MAX_TRACK_AGE_SEC = 600   # purge tracks orphelins > 10 min


@dataclass
class PlateReading:
    """Une tentative OCR sur une frame donnée."""
    plate: str
    confidence: float
    ts: float
    plate_crop: str = ""      # data URI JPEG
    vehicle_crop: str = ""
    vehicle_type: str = ""
    vehicle_color: str = ""
    engine: str = "fast-alpr"


@dataclass
class TrackedVehicle:
    """État d'un véhicule suivi (1 instance par ``track_id`` ByteTrack)."""
    track_id: int
    camera_id: str
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    readings: list = field(default_factory=list)  # list[PlateReading]
    state: str = "ENTERED"        # ENTERED → PRESENT → LEFT
    event_emitted: bool = False   # True quand l'événement principal a été émis
    lost_cycles: int = 0          # cycles consécutifs sans re-voir le track

    def add_reading(self, r: PlateReading) -> None:
        self.readings.append(r)
        self.last_seen = r.ts
        self.lost_cycles = 0

    def best_reading(self) -> Optional[PlateReading]:
        """Sélectionne la meilleure lecture : consensus + confiance max.

        Algorithme :
          1. Groupe les lectures par ``plate`` (texte normalisé).
          2. Choisit le texte le plus fréquent (consensus).
          3. Dans ce groupe, retourne la lecture avec la meilleure confiance
             et un crop non-vide.
        """
        if not self.readings:
            return None
        # 1. Consensus par texte
        texts = [r.plate for r in self.readings if r.plate]
        if not texts:
            return None
        top_text, _ = Counter(texts).most_common(1)[0]
        # 2. Meilleure lecture pour ce texte
        same = [r for r in self.readings if r.plate == top_text]
        # Priorité : plate_crop non-vide, puis confidence max
        same.sort(key=lambda r: (bool(r.plate_crop), r.confidence), reverse=True)
        return same[0]


class AnprTracker:
    """Accumulateur ANPR global (singleton).

    Cycle de vie :
      - ``record_reading(camera_id, track_id, reading)`` : ajoute une lecture.
      - ``tick_missing(camera_id, seen_track_ids)`` : appelé à chaque cycle
        IA pour incrémenter les compteurs "lost" des tracks non revus.
      - ``pop_ready_events(camera_id)`` : récupère les événements à émettre
        (véhicules qui viennent d'atteindre l'état "PRESENT" ou "LEFT" avec
        des readings valides).
    """

    def __init__(
        self,
        min_readings: int = DEFAULT_MIN_READINGS,
        lost_cycles: int = DEFAULT_LOST_CYCLES,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ):
        self.min_readings = min_readings
        self.lost_cycles = lost_cycles
        self.min_confidence = min_confidence
        # Structure : {camera_id: {track_id: TrackedVehicle}}
        self._tracks: dict[str, dict[int, TrackedVehicle]] = defaultdict(dict)
        # File d'événements prêts (véhicules dont l'état vient de basculer)
        self._pending_events: list[dict] = []

    # ── Configuration à chaud ────────────────────────────────────────
    def configure(self, **kw) -> None:
        if "min_readings" in kw:
            self.min_readings = max(1, int(kw["min_readings"]))
        if "lost_cycles" in kw:
            self.lost_cycles = max(1, int(kw["lost_cycles"]))
        if "min_confidence" in kw:
            self.min_confidence = max(0.0, min(1.0, float(kw["min_confidence"])))

    # ── Ingestion des lectures ───────────────────────────────────────
    def record_reading(self, camera_id: str, track_id: Optional[int],
                       reading: PlateReading) -> bool:
        """Enregistre une lecture OCR pour un véhicule tracké.

        Retourne ``True`` si un événement métier doit être émis MAINTENANT
        (première lecture consensuelle du véhicule).

        Si ``track_id is None`` (ByteTrack désactivé ou pas de tracking pour
        cette détection), on utilise le texte OCR comme identifiant fallback
        pour rester compatible avec l'ancien comportement.
        """
        if reading.confidence < self.min_confidence:
            return False
        # Fallback quand pas de track_id : on utilise le texte OCR pour
        # regrouper (comportement dégradé mais fonctionnel)
        tid = track_id if track_id is not None else -abs(hash(reading.plate)) % 10_000_000

        cam_tracks = self._tracks[camera_id]
        tv = cam_tracks.get(tid)
        if tv is None:
            tv = TrackedVehicle(track_id=tid, camera_id=camera_id)
            cam_tracks[tid] = tv
        tv.add_reading(reading)

        # Émettre l'événement dès la 1ère lecture consensuelle (min_readings)
        if not tv.event_emitted and len(tv.readings) >= self.min_readings:
            best = tv.best_reading()
            if best is not None:
                tv.state = "PRESENT"
                tv.event_emitted = True
                self._pending_events.append({
                    "camera_id": camera_id,
                    "track_id": tid,
                    "state": "ENTRY",
                    "best": best,
                    "readings_count": len(tv.readings),
                    "duration_ms": int((tv.last_seen - tv.first_seen) * 1000),
                })
                logger.info(
                    "anpr_tracker: ENTRY cam=%s track=%s plate=%s conf=%.2f readings=%d",
                    camera_id, tid, best.plate, best.confidence, len(tv.readings),
                )
                return True
        return False

    # ── Cycles IA : marque les tracks non revus ───────────────────────
    def tick_missing(self, camera_id: str, seen_track_ids: set) -> None:
        """Appelé après chaque cycle IA — incrémente ``lost_cycles`` pour
        tous les tracks connus mais non revus, et bascule à ``LEFT`` ceux
        qui ont dépassé le seuil ``lost_cycles``.
        """
        cam_tracks = self._tracks.get(camera_id)
        if not cam_tracks:
            return
        now = time.time()
        to_forget: list[int] = []
        for tid, tv in cam_tracks.items():
            if tid in seen_track_ids:
                continue
            tv.lost_cycles += 1
            if tv.state != "LEFT" and tv.lost_cycles >= self.lost_cycles:
                tv.state = "LEFT"
                if tv.event_emitted:
                    best = tv.best_reading()
                    if best is not None:
                        self._pending_events.append({
                            "camera_id": camera_id,
                            "track_id": tid,
                            "state": "EXIT",
                            "best": best,
                            "readings_count": len(tv.readings),
                            "duration_ms": int((tv.last_seen - tv.first_seen) * 1000),
                        })
                        logger.info(
                            "anpr_tracker: EXIT cam=%s track=%s plate=%s duration=%.1fs",
                            camera_id, tid, best.plate,
                            tv.last_seen - tv.first_seen,
                        )
                # Purge après émission EXIT (ou immédiate si jamais émis)
                to_forget.append(tid)
            # Purge des tracks orphelins (jamais mis à jour depuis longtemps)
            elif (now - tv.last_seen) > DEFAULT_MAX_TRACK_AGE_SEC:
                to_forget.append(tid)
        for tid in to_forget:
            cam_tracks.pop(tid, None)

    # ── Consommation des événements ──────────────────────────────────
    def pop_ready_events(self, camera_id: Optional[str] = None) -> list[dict]:
        """Vide et retourne les événements en attente.

        Si ``camera_id`` est fourni, ne retourne que ceux de cette caméra.
        """
        if camera_id is None:
            evts, self._pending_events = self._pending_events, []
            return evts
        keep, out = [], []
        for e in self._pending_events:
            (out if e["camera_id"] == camera_id else keep).append(e)
        self._pending_events = keep
        return out

    # ── Introspection (debug / monitoring) ───────────────────────────
    def snapshot(self) -> dict:
        return {
            "config": {
                "min_readings": self.min_readings,
                "lost_cycles": self.lost_cycles,
                "min_confidence": self.min_confidence,
            },
            "cameras": {
                cid: [
                    {
                        "track_id": tv.track_id,
                        "state": tv.state,
                        "readings": len(tv.readings),
                        "lost_cycles": tv.lost_cycles,
                        "first_seen": tv.first_seen,
                        "last_seen": tv.last_seen,
                        "event_emitted": tv.event_emitted,
                        "best_plate": (tv.best_reading().plate
                                       if tv.best_reading() else None),
                    }
                    for tv in tracks.values()
                ]
                for cid, tracks in self._tracks.items()
            },
        }

    def reset_camera(self, camera_id: str) -> None:
        self._tracks.pop(camera_id, None)


# Singleton global
anpr_tracker = AnprTracker()
