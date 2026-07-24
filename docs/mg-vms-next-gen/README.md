# MG-VMS Next Generation — Cahier des charges

> **Statut du document** : en cours de rédaction (v0.1)
> **Dernière mise à jour** : 2026-07-24
> **Version cible du produit** : MG-VMS v3.0
> **Version actuelle du produit** : MG-VMS v2.22.0

Ce dépôt contient le cahier des charges officiel de **MG-VMS Next Generation**, la nouvelle génération du Video Management System MG. Il constitue la **référence unique** pour toute décision produit, architecture, UX et développement.

## Positionnement

MG-VMS NG vise à rivaliser avec **Milestone XProtect · Nx Witness · Genetec Security Center · Avigilon · Digifort · Luxriot** sur les axes suivants :

- **Stabilité** — aucune panne cascade (caméra, GPU, module IA) ne doit dégrader l'ensemble du système.
- **Performances** — pipeline vidéo GPU (NVDEC/NVENC/scale_cuda) direct, WebRTC bas-latence, IA modulaire indépendante.
- **Simplicité d'usage** — mode Installateur 10-15 min, dashboard personnalisable, diagnostics en langage humain.
- **Modularité** — chaque composant remplaçable (moteur vidéo, storage, IA, notifications).
- **IA intégrée** — YOLO, ANPR, Face, Smoke, Fire, PPE, Counting, Loitering, CrossLine, Zone.
- **Extensibilité** — API REST/WS/MQTT/Webhook + SDK + Marketplace de plugins.

## Philosophie

Chaque fonctionnalité doit satisfaire **trois critères non-négociables** :

1. **Simple pour l'utilisateur** — un opérateur non-technicien doit pouvoir utiliser 90% des fonctions.
2. **Modulaire pour le développeur** — chaque service isolable, testable, remplaçable.
3. **Stable en production** — aucun bug d'un composant ne fait tomber les autres (bulkheads).

## Sommaire

### Partie I — Fondations
- `01-vision-positionnement.md` — *à rédiger*
- **`02-philosophie-principes.md`** — ✅ **v1 rédigé** (2026-07-24)
- `03-personas.md` — *à rédiger*
- **`04-architecture-cible.md`** — ✅ **v1 rédigé et validé** (2026-07-24, Traefik 3, Fernet env, single-node v3.0)
- `05-contrats-interfaces.md` — *à rédiger*

### Partie II — Expérience utilisateur transverse
- `06-mode-installateur.md` — *à rédiger*
- `07-home-dashboard.md` — *à rédiger*
- `08-mur-video.md` — *à rédiger*
- `09-recherche-unifiee.md` — *à rédiger*

### Partie III — Modules fonctionnels
- `10-ajout-camera.md`
- `11-moteur-ia-modulaire.md`
- `12-lapi-anpr.md`
- `13-parking.md`
- `14-ptz.md`
- `15-automatisation.md`
- `16-storage-manager.md`
- `17-gpu-manager.md`
- `18-snapshots.md`
- `19-zones.md`
- `20-diagnostics-intelligents.md`
- `21-rapports.md`
- `22-administration-rbac.md`

### Partie IV — Écosystème
- `23-api-publique.md`
- `24-plugins-marketplace.md`
- `25-integrations-tierces.md`

### Partie V — Roadmap & Livraison
- `26-roadmap.md`
- `27-versioning-deprecation.md`
- `28-grille-responsabilites.md`

## Conventions du document

- **Prescriptif** — le code actuel (v2.22.0) devra s'aligner sur ce document à terme. Les écarts existants sont documentés dans chaque chapitre sous « Écart avec la v2.22.0 ».
- **Décisions d'architecture (ADR)** — chaque décision structurante est numérotée (`ADR-XX`) avec `Contexte / Décision / Conséquences / Alternatives rejetées`.
- **Diagrammes** — ASCII pour portabilité Git-friendly ; les diagrammes plus complexes (draw.io / mermaid) sont référencés en annexe.
- **Modes dégradés** — chaque composant décrit obligatoirement son comportement quand une dépendance est HS.
- **Testabilité** — chaque module décrit ses tests d'acceptation (Given / When / Then).

## Comment contribuer

Chaque chapitre est livré en session dédiée avec allers-retours détaillés. Une fois validé, un tag Git `docs/chapter-XX-v1` fige la version. Les évolutions ultérieures sont versionnées `-v2`, `-v3`.

Export PDF : `pandoc *.md -o mg-vms-next-gen.pdf --toc --number-sections`.
