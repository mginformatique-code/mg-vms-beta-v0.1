# Benchmark Pipeline v2 — avant / après refonte v0.4.2

Date : 2026-08-06 10:07:15 · Frame 1080p · 4 véhicules · 30 itérations


## YOLO (une seule inférence — identique)

- avg : 263.5 ms · max : 405.3 ms


## Tracking

| | Avant (double) | Après (unique) |
|---|---|---|
| Latence moyenne | 0.715 ms | 0.367 ms |
| Trackers exécutés | 2 | 1 |

## Crops + JPEG ANPR (par cycle, 4 véhicules)

| Moteurs | Avant ms (encodes) | Après ms (encodes) |
|---|---|---|
| 1 | 0.75 (4) | 0.74 (4) |
| 5 | 3.68 (20) | 0.74 (4) |
| 10 | 7.33 (40) | 0.74 (4) |
| 20 | 14.65 (80) | 0.75 (4) |

## Dispatch PluginBus (consumers 1 ms)

| Plugins | Avant ms (broadcast) | Après ms (per-camera) |
|---|---|---|
| 1 | 1.15 | 1.15 |
| 5 | 1.2 | 1.1 |
| 10 | 1.25 | 1.11 |
| 20 | 1.42 | 1.11 |

## Système

- Début : {'cpu_percent': 5.0, 'rss_mb': 55.9, 'vram_mb': None}
- Fin : {'cpu_percent': 2.5, 'rss_mb': 809.1, 'vram_mb': None}
