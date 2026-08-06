"""Politiques de fusion multi-plugins (chapitre 11 §11.6.1).

Quand plusieurs plugins `PlateRecognizer` (ou `FrameAnalyzer`) sont actifs
simultanément sur la même caméra, il faut décider comment combiner leurs
résultats. Cette module implémente les 4 politiques du cahier des charges :

  - `cascade`   : appelle les plugins un par un dans l'ordre, retient le
                  premier résultat dont la confidence >= seuil. Économise le
                  quota d'un plugin cloud coûteux (mode « meilleur résultat »).
  - `highest`   : appelle tous les plugins en parallèle, retient le résultat
                  avec la plus haute confidence (mode « highest_confidence »).
  - `compare`   : appelle tous en parallèle, retourne tous les résultats côte
                  à côte pour analyse qualité (journalise les divergences).
  - `vote`      : appelle tous en parallèle, vote majoritaire caractère par
                  caractère (utile pour caméras difficiles).

Le core ne connaît aucun moteur individuellement — il applique une politique
à une liste de résultats normalisés `PlateResult` (ADR-16).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Iterable, Optional

from .interfaces import PlateResult

# Modes exposés à l'API
MODE_CASCADE = "cascade"
MODE_HIGHEST = "highest"
MODE_COMPARE = "compare"
MODE_VOTE = "vote"
# v0.5.6 P0-4 · Mode « hiérarchique » (`hybrid` dans le vocabulaire user) —
# stratégie recommandée par défaut : normalisation → majorité → confiance
# → priorité déclarée → ambigu. Ne remplace jamais silencieusement une
# lecture par une autre : si plusieurs textes distincts survivent aux
# étapes 1-4, la lecture est marquée `ambiguous=True` et TOUS les
# candidats sont conservés en `evidence` pour analyse manuelle.
MODE_HIERARCHICAL = "hierarchical"

VALID_MODES = {MODE_CASCADE, MODE_HIGHEST, MODE_COMPARE, MODE_VOTE, MODE_HIERARCHICAL}

DEFAULT_CASCADE_THRESHOLD = 0.85


def pick_highest(results: Iterable[PlateResult]) -> Optional[PlateResult]:
    """Retourne le PlateResult avec la meilleure confidence, ou None."""
    best: Optional[PlateResult] = None
    for r in results:
        if r is None or not r.text:
            continue
        if best is None or r.confidence > best.confidence:
            best = r
    return best


def vote_by_character(results: list[PlateResult]) -> Optional[PlateResult]:
    """Vote majoritaire caractère par caractère (§11.6.1 mode « fusion »).

    Aligne les plaques par longueur maximale, choisit à chaque position le
    caractère le plus fréquent. La confidence retournée est la moyenne
    pondérée des confidences des plugins qui ont voté. Le champ `engine`
    devient `fusion(<n>)`.
    """
    plates = [r for r in results if r and r.text]
    if not plates:
        return None
    max_len = max(len(p.text) for p in plates)
    voted_chars: list[str] = []
    for i in range(max_len):
        chars_at_pos = [p.text[i] for p in plates if i < len(p.text)]
        if not chars_at_pos:
            continue
        most_common = Counter(chars_at_pos).most_common(1)[0][0]
        voted_chars.append(most_common)
    avg_conf = sum(p.confidence for p in plates) / len(plates)
    return PlateResult(
        text="".join(voted_chars),
        confidence=round(avg_conf, 4),
        engine=f"fusion({len(plates)})",
        processing_ms=max(p.processing_ms for p in plates),
    )


def normalize_plate(text: str) -> str:
    """Normalise un texte de plaque pour comparaison inter-moteurs.

    v0.5.6 P0-4 — Étape 1 de la fusion hiérarchique.
    Règles :
      * Upper-case
      * Suppression des caractères non-alphanumériques (espaces, tirets, points)
      * Confusion visuelle homogène : `O`↔`0`, `I`↔`1`, `Z`↔`2` ne sont PAS
        remplacés (perte d'information) — on préfère laisser distincts et
        laisser la majorité départager si un moteur fait l'erreur.
    """
    import re
    if not text:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def hierarchical_fusion(
    results_by_engine: list[tuple[str, list[PlateResult]]],
    priority_order: Optional[list[str]] = None,
) -> tuple[Optional[PlateResult], bool]:
    """Fusion hiérarchique multi-étapes (§Phase A P0-4).

    Étape 1 · Normalisation (uppercase + alphanumérique uniquement).
    Étape 2 · Vote majoritaire — si un texte normalisé apparaît chez ≥ 2
              moteurs, il gagne immédiatement (retourne PlateResult avec la
              MEILLEURE confiance parmi les moteurs qui l'ont proposé).
    Étape 3 · Si égalité de majorité (ex : 2 moteurs pour A, 2 pour B) →
              on prend le camp avec la meilleure confiance moyenne.
    Étape 4 · Si toujours indécidable OU chaque moteur propose un texte
              différent : on utilise `priority_order` (ordre des moteurs
              tel que déclaré dans la config caméra) pour trancher.
    Étape 5 · Si aucune décision possible → retourne (best_confidence, True)
              marquant la lecture comme AMBIGÜE. Ne jamais inventer une
              plaque : on préserve TOUJOURS le meilleur candidat brut.

    Retourne (final_PlateResult | None, ambiguous: bool).
    """
    # Meilleur candidat par moteur (une seule proposition par moteur).
    top_per_engine: list[tuple[str, Optional[PlateResult]]] = [
        (name, pick_highest(plates)) for name, plates in results_by_engine
    ]
    valid = [(name, r) for name, r in top_per_engine if r and r.text]
    if not valid:
        return None, False
    if len(valid) == 1:
        return valid[0][1], False

    # Étape 1 — Normalisation.
    norm_map: dict[str, list[tuple[str, PlateResult]]] = {}
    for name, r in valid:
        n = normalize_plate(r.text)
        if not n:
            continue
        norm_map.setdefault(n, []).append((name, r))

    if not norm_map:
        return None, False

    # Étape 2 — Vote majoritaire (au moins 2 moteurs pour le même texte).
    counts = {n: len(voters) for n, voters in norm_map.items()}
    max_count = max(counts.values())
    if max_count >= 2:
        winners = [n for n, c in counts.items() if c == max_count]
        if len(winners) == 1:
            # Consensus clair. Prend la meilleure conf dans ce groupe.
            best = pick_highest([r for _n, r in norm_map[winners[0]]])
            if best:
                return replace(best, engine=f"fusion(majority×{max_count})"), False

        # Étape 3 — Égalité de majorité, on départage par confidence moy.
        best_group = max(
            winners,
            key=lambda n: sum(r.confidence for _e, r in norm_map[n]) / len(norm_map[n]),
        )
        best = pick_highest([r for _n, r in norm_map[best_group]])
        if best:
            return replace(best, engine=f"fusion(tie-break-conf)"), False

    # Étape 4 — Chaque moteur propose un texte différent : priorité déclarée.
    if priority_order:
        for eng in priority_order:
            for name, r in valid:
                if name == eng:
                    return replace(r, engine=f"fusion(priority:{eng})"), False

    # Étape 5 — Ambigu : conserve le meilleur candidat brut, drapeau levé.
    fallback = pick_highest([r for _n, r in valid])
    return (
        replace(fallback, engine=f"fusion(ambiguous)") if fallback else None,
        True,
    )


def apply_policy(
    mode: str,
    results_by_engine: list[tuple[str, list[PlateResult]]],
    threshold: float = DEFAULT_CASCADE_THRESHOLD,
) -> dict:
    """Applique une politique de fusion sur les résultats de N moteurs ANPR.

    Args:
        mode: `cascade` | `highest` | `compare` | `vote`.
        results_by_engine: liste ordonnée de (engine_name, list[PlateResult]).
            Pour `cascade`, l'ordre définit la priorité d'appel.
        threshold: seuil de confidence pour le mode cascade.

    Returns:
        {
          "mode": str,
          "final": PlateResult | None,
          "all_results": [ {engine, plates}... ],
          "divergence": bool,
        }
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Mode fusion inconnu: {mode!r}. Valides: {sorted(VALID_MODES)}")

    all_flat: list[PlateResult] = []
    for _engine, plates in results_by_engine:
        all_flat.extend(plates)

    final: Optional[PlateResult] = None
    if mode == MODE_CASCADE:
        for _engine, plates in results_by_engine:
            best = pick_highest(plates)
            if best and best.confidence >= threshold:
                final = best
                break
        if final is None:
            final = pick_highest(all_flat)  # meilleur des restes
    elif mode == MODE_HIGHEST:
        final = pick_highest(all_flat)
    elif mode == MODE_VOTE:
        # Prend le meilleur candidat de chaque moteur puis vote
        top_per_engine = [pick_highest(plates) for _e, plates in results_by_engine]
        final = vote_by_character([r for r in top_per_engine if r is not None])
    elif mode == MODE_COMPARE:
        # En mode compare on ne fixe pas de gagnant — le client décide
        final = pick_highest(all_flat)
    elif mode == MODE_HIERARCHICAL:
        final, _amb = hierarchical_fusion(results_by_engine)

    # Divergence = au moins 2 moteurs ont retourné des textes différents
    texts = {r.text for r in all_flat if r.text}
    divergence = len(texts) > 1

    return {
        "mode": mode,
        "final": final,
        "all_results": [
            {
                "engine": engine,
                "plates": [
                    {
                        "text": p.text,
                        "confidence": p.confidence,
                        "engine": p.engine or engine,
                        "processing_ms": p.processing_ms,
                        "bbox_plate": list(p.bbox_plate) if p.bbox_plate else None,
                    }
                    for p in plates
                ],
            }
            for engine, plates in results_by_engine
        ],
        "divergence": divergence,
        "threshold_used": threshold if mode == MODE_CASCADE else None,
    }
