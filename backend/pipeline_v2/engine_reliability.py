"""v0.7.h · Wave I · Axe QoS · OCR Engine Reliability (learning online).

Suit la fiabilité de chaque moteur OCR **par caméra** :
  * consecutive_success / consecutive_fail
  * rolling accuracy sur 100 dernières lectures
  * temps moyen d'inference

Retourne un `reliability_weight` dynamique (0.5 – 1.5) qui multiplie le
poids statique de `plate_quality.engine_weight`. Un moteur qui rate
constamment sur une caméra donnée voit son influence baisser
progressivement. Un moteur qui domine voit son influence augmenter.

Aucune persistance disque — la mémoire est volatile (reset à chaque
redémarrage backend). Suffisant pour l'apprentissage online.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque


MAX_HISTORY = 100
BASE_WEIGHT = 1.0
MIN_MULT = 0.5
MAX_MULT = 1.5


@dataclass
class EngineRecord:
    reads_total: int = 0
    reads_recent_ok: Deque[bool] = field(default_factory=lambda: deque(maxlen=MAX_HISTORY))
    time_sum_ms: float = 0.0
    time_count: int = 0

    def record(self, ok: bool, time_ms: float = 0.0) -> None:
        self.reads_total += 1
        self.reads_recent_ok.append(bool(ok))
        if time_ms > 0:
            self.time_sum_ms += time_ms
            self.time_count += 1

    @property
    def rolling_accuracy(self) -> float:
        if not self.reads_recent_ok:
            return 0.5   # neutre au démarrage
        return sum(1 for x in self.reads_recent_ok if x) / len(self.reads_recent_ok)

    @property
    def avg_time_ms(self) -> float:
        return self.time_sum_ms / self.time_count if self.time_count else 0.0

    @property
    def reliability_mult(self) -> float:
        """Multiplicateur 0.5-1.5 sur le poids fusion (0.5 si accuracy=0,
        1.0 si accuracy=0.5, 1.5 si accuracy=1.0). Neutre tant que <10 lectures."""
        if len(self.reads_recent_ok) < 10:
            return 1.0
        acc = self.rolling_accuracy
        return MIN_MULT + (MAX_MULT - MIN_MULT) * acc

    def to_dict(self) -> dict:
        return {
            "reads_total": self.reads_total,
            "reads_recent": len(self.reads_recent_ok),
            "rolling_accuracy": round(self.rolling_accuracy, 3),
            "avg_time_ms": round(self.avg_time_ms, 2),
            "reliability_mult": round(self.reliability_mult, 3),
        }


# Structure : {(camera_id, engine_name): EngineRecord}
_records: dict[tuple, EngineRecord] = defaultdict(EngineRecord)


def record_engine_reading(camera_id: str, engine: str, *,
                            success: bool, time_ms: float = 0.0) -> None:
    _records[(camera_id, (engine or "").lower())].record(success, time_ms)


def reliability_mult(camera_id: str, engine: str) -> float:
    return _records[(camera_id, (engine or "").lower())].reliability_mult


def snapshot() -> dict:
    """Renvoie l'état complet des reliability scores pour exposition API."""
    out: dict = defaultdict(dict)
    for (cam, eng), rec in _records.items():
        out[cam][eng] = rec.to_dict()
    return dict(out)


def reset() -> None:
    _records.clear()
