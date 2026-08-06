# Benchmark Pipeline v2 — avant / après refonte v0.4.2

Date : 2026-08-06 11:57:42 · Frame 1080p · 4 véhicules · 30 itérations


## YOLO (une seule inférence — identique)

- avg : 338.4 ms · max : 402.8 ms


## Tracking

| | Avant (double) | Après (unique) |
|---|---|---|
| Latence moyenne | 0.919 ms | 0.37 ms |
| Trackers exécutés | 2 | 1 |

## Crops + JPEG ANPR (par cycle, 4 véhicules)

| Moteurs | Avant ms (encodes) | Après ms (encodes) |
|---|---|---|
| 1 | 1.01 (4) | 0.75 (4) |
| 5 | 3.68 (20) | 0.74 (4) |
| 10 | 7.33 (40) | 0.74 (4) |
| 20 | 14.66 (80) | 0.75 (4) |

## Dispatch PluginBus (consumers 1 ms · latence par frame)

| Plugins | Baseline · tous activés (ms) | Cible · 1 seul activé (ms) | Facteur |
|---|---|---|---|
| 1 | 1.1 | 1.09 | ×1.0 |
| 5 | 1.17 | 1.09 | ×1.1 |
| 10 | 1.23 | 1.1 | ×1.1 |
| 20 | 1.42 | 1.11 | ×1.3 |
| 30 | 1.57 | 1.13 | ×1.4 |
| 50 | 1.91 | 1.11 | ×1.7 |

## Fermeture stricte fail-safe (v0.4.3 · P1)

Registered : 10 · Appels réels avec `enabled_plugins ∈ {[], null, absent}` : **0** (attendu 0)

*Preuve que le comportement fail-open a bien été éliminé.*

## Système

- Début : {'cpu_percent': 6.3, 'rss_mb': 58.0, 'vram_mb': None}
- Fin : {'cpu_percent': 1.9, 'rss_mb': 894.1, 'vram_mb': None}
- GPU : **non mesuré** (environnement cloud sans GPU · benchmarks GPU différés RTX A2000)
- VRAM : **N/A**
