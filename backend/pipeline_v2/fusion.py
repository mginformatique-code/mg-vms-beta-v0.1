"""Pipeline v2 · Fusion Engine — 6 stratégies configurables par caméra.

Combine les résultats de plusieurs providers ANPR (ou détecteurs) en UN
seul résultat "fusionné" jugé le meilleur selon la stratégie configurée.

Stratégies supportées :
    - ``highest_confidence`` : garde le reading avec la meilleure confiance
    - ``majority_vote``      : consensus par texte (majoritaire l'emporte)
    - ``weighted_vote``      : vote pondéré par ``weights[provider]``
    - ``cascade``            : essaie providers dans l'ordre, s'arrête au 1er
                               qui dépasse ``min_confidence``
    - ``first_success``      : tout premier résultat non-vide gagne (rapidité)
    - ``best_latency``       : le plus rapide (utile pour SLA temps réel)

Config par caméra (dict passé au moteur) :
    {
        "strategy": "weighted_vote",
        "min_confidence": 0.6,
        "weights": {"fast-alpr": 1.0, "google-vision": 1.2, "openalpr": 0.9},
        "order": ["fast-alpr", "openalpr", "google-vision"]  # pour cascade
    }
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Optional

from .interfaces import PlateResult


VALID_STRATEGIES = (
    "highest_confidence", "majority_vote", "weighted_vote",
    "cascade", "first_success", "best_latency",
)


class FusionEngine:
    """Fusion multi-providers pour plate recognition.

    Le même moteur peut être adapté à la fusion multi-détecteurs si besoin
    (protocole identique : liste de résultats → 1 résultat consensuel).
    """

    def __init__(self, strategy: str = "highest_confidence",
                 min_confidence: float = 0.5,
                 weights: Optional[dict[str, float]] = None,
                 order: Optional[list[str]] = None):
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"Strategy inconnue: {strategy}. "
                             f"Valides: {VALID_STRATEGIES}")
        self.strategy = strategy
        self.min_confidence = float(min_confidence)
        self.weights = weights or {}
        self.order = order or []

    def configure(self, **kw) -> None:
        if "strategy" in kw and kw["strategy"] in VALID_STRATEGIES:
            self.strategy = kw["strategy"]
        if "min_confidence" in kw:
            self.min_confidence = float(kw["min_confidence"])
        if "weights" in kw:
            self.weights = dict(kw["weights"] or {})
        if "order" in kw:
            self.order = list(kw["order"] or [])

    def fuse(self, readings: list[PlateResult]) -> Optional[PlateResult]:
        """Applique la stratégie et retourne le meilleur PlateResult (ou None)."""
        readings = [r for r in readings if r and r.plate
                    and r.confidence >= self.min_confidence]
        if not readings:
            return None

        if self.strategy == "highest_confidence":
            return max(readings, key=lambda r: r.confidence)

        if self.strategy == "first_success":
            return readings[0]

        if self.strategy == "best_latency":
            # processing_time_ms=0 est ambiguous → filtre les non renseignés
            timed = [r for r in readings if r.processing_time_ms > 0]
            pool = timed or readings
            return min(pool, key=lambda r: r.processing_time_ms)

        if self.strategy == "majority_vote":
            counts = Counter(r.plate for r in readings)
            top_text, _ = counts.most_common(1)[0]
            same = [r for r in readings if r.plate == top_text]
            # Boost la confidence de la fusion : moyenne des winners + bonus consensus
            avg_conf = sum(r.confidence for r in same) / len(same)
            best = max(same, key=lambda r: r.confidence)
            fused = _clone(best)
            fused.confidence = min(0.99, avg_conf + 0.03 * (len(same) - 1))
            fused.provider = "fusion:majority_vote"
            return fused

        if self.strategy == "weighted_vote":
            scores: dict[str, float] = defaultdict(float)
            best_by_text: dict[str, PlateResult] = {}
            for r in readings:
                w = self.weights.get(r.provider, 1.0)
                scores[r.plate] += w * r.confidence
                if r.plate not in best_by_text or best_by_text[r.plate].confidence < r.confidence:
                    best_by_text[r.plate] = r
            top_text = max(scores.items(), key=lambda kv: kv[1])[0]
            fused = _clone(best_by_text[top_text])
            fused.confidence = min(0.99, scores[top_text] /
                                   max(1.0, sum(self.weights.get(r.provider, 1.0) for r in readings)))
            fused.provider = "fusion:weighted_vote"
            return fused

        if self.strategy == "cascade":
            # Tri par ordre déclaré ; retourne le 1er qui dépasse min_confidence
            ordered = self.order or [r.provider for r in readings]
            by_provider = defaultdict(list)
            for r in readings:
                by_provider[r.provider].append(r)
            for prov in ordered:
                rs = by_provider.get(prov, [])
                if not rs:
                    continue
                best = max(rs, key=lambda r: r.confidence)
                if best.confidence >= self.min_confidence:
                    return best
            # Aucun n'a passé le seuil → fallback highest
            return max(readings, key=lambda r: r.confidence)

        # Sécurité (ne devrait pas arriver)
        return max(readings, key=lambda r: r.confidence)


def _clone(r: PlateResult) -> PlateResult:
    return PlateResult(
        plate=r.plate, confidence=r.confidence, bbox=r.bbox,
        country=r.country, processing_time_ms=r.processing_time_ms,
        provider=r.provider, raw_text=r.raw_text,
        vehicle_type=r.vehicle_type, vehicle_color=r.vehicle_color,
        track_id=r.track_id, extras=dict(r.extras),
    )
