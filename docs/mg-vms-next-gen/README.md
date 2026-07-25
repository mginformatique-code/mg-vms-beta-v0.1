# MG-VMS Next Generation — Cahier des charges

> **Statut du document** : en cours de rédaction (v0.2 — Pivot plateforme de plugins)
> **Dernière mise à jour** : 2026-07-24
> **Version cible du produit** : MG-VMS v3.0
> **Version actuelle du produit** : MG-VMS v2.22.0

Ce dépôt contient le cahier des charges officiel de **MG-VMS Next Generation**, la nouvelle génération du Video Management System MG. Il constitue la **référence unique** pour toute décision produit, architecture, UX et développement.

## Positionnement

MG-VMS NG vise à devenir la **plateforme open-source de référence** de la vidéosurveillance moderne, en s'inspirant du modèle **Home Assistant / Grafana / VS Code** : un **noyau volontairement minimal** entouré d'un **écosystème de plugins** activables indépendamment. Concurrents ciblés : **Milestone XProtect · Nx Witness · Genetec Security Center · Avigilon · Digifort · Luxriot · Frigate**.

Différenciateurs clés :

- **Architecture plateforme** — tout est plugin sauf le noyau (R16, chapitre 11).
- **Stabilité** — le crash d'un plugin ne fait jamais tomber le VMS (bulkheads systématiques).
- **Mode Installateur 10-15 min** — de zéro à opérationnel sans naviguer dans 20 menus (chapitre 6).
- **Multi-ANPR** — plusieurs moteurs de plaque simultanés avec vote/fusion (chapitre 11 §11.6.1).
- **Diagnostics intelligents** — aucun voyant rouge orphelin, cause probable en français (R02).
- **Marketplace de plugins** — installation en 1 clic, publication communautaire.

## Philosophie

Chaque fonctionnalité doit satisfaire **trois critères non-négociables** :

1. **Simple pour l'utilisateur** — un opérateur non-technicien doit pouvoir utiliser 90% des fonctions.
2. **Modulaire pour le développeur** — chaque plugin isolable, testable, remplaçable.
3. **Stable en production** — aucun bug d'un plugin ne fait tomber les autres ni le noyau.

Formalisé en 16 règles opposables (R01→R16, chapitre 2).

## Sommaire

### Partie I — Fondations
- `01-vision-positionnement.md` — *à rédiger*
- **`02-philosophie-principes.md`** — ✅ **v1.1 rédigé et validé** (16 règles + R16 plugins)
- `03-personas.md` — *à rédiger*
- **`04-architecture-cible.md`** — ✅ **v1.1 rédigé et validé** (Traefik 3, Fernet env, single-node v3.0 + amendement plugins §4.14)
- **`05-contrats-interfaces.md`** — ✅ **v1 rédigé** (REST/WS/MQTT/Webhooks/SDK + 4 ADR)

### Partie II — Expérience utilisateur transverse
- **`06-mode-installateur.md`** — ✅ **v1 rédigé** (8 étapes · 10-15 min · rapport PDF)
- `07-home-dashboard.md` — *à rédiger* (widgets personnalisables, plan du site, favoris)
- `08-mur-video.md` — *à rédiger* (layouts illimités, drag&drop, murs spécialisés)
- `09-recherche-unifiee.md` — *à rédiger*

### Partie III — Plateforme & modules fonctionnels
- `10-ajout-camera.md` — *à rédiger* (assistant complet avec choix plugins par caméra)
- **`11-plateforme-plugins.md`** — ✅ **v1 rédigé** ⭐ **Chapitre fondateur** — Plugin Manager, 10 interfaces standardisées, SDK multi-langages, Marketplace, sandboxing, migration v2.22→v3.0, 5 ADR (15-19)
- `12-modules-ia-officiels.md` — *à rédiger* (yolo-detection, fast-alpr, face-recognition-insightface, zone-analytics… bundle v3.0)
- `13-plugin-parking.md` — *à rédiger* (plan · places · PMR/VIP · heatmap · corrélation LAPI)
- `14-ptz.md` — *à rédiger* (base core + plugin `ptz-advanced` pour tours/calendrier/tracking IA)
- `15-plugin-automation.md` — *à rédiger* (moteur type Node-RED : SI/ET/OU/ALORS)
- `16-storage-manager.md` — *à rédiger* (core local + plugins S3/Azure/GCS/NAS)
- `17-gpu-manager.md` — *à rédiger* (allocation VRAM partagée entre plugins IA)
- `18-snapshots.md` — *à rédiger*
- `19-zones.md` — *à rédiger*
- `20-diagnostics-intelligents.md` — *à rédiger* ⭐ (application R02 : cause probable en français, arbres de décision)
- `21-rapports.md` — *à rédiger* (PDF/CSV/Excel/planning)
- `22-administration-rbac.md` — *à rédiger* (base core + plugins LDAP/OIDC/AD)

### Partie IV — Écosystème
- `23-api-publique.md` — *à rédiger* (SDK Python v3.1, JS v3.1, C#/Go/Rust v3.2+)
- `24-plugins-marketplace.md` — *à rédiger* (catalogue officiel, review, publication)
- `25-integrations-tierces.md` — *à rédiger* (Home Assistant, Grafana, Node-RED, Frigate, Jeedom, KNX, BACnet…)

### Partie V — Roadmap & Livraison
- `26-roadmap.md` — *à rédiger* (v3.0 core+plugins bundle, v3.1 Marketplace, v3.2 sandboxing Docker/SDK Go/Rust)
- `27-versioning-deprecation.md` — *à rédiger*
- `28-grille-responsabilites.md` — *à rédiger*

## Chapitres livrés à date (v0.3 — 2026-07-24)

| # | Titre | Lignes | Statut |
|---|---|---|---|
| README | Index général | 99 | ✅ |
| 01 | Vision & positionnement | ~360 | ✅ v1 |
| 02 | Philosophie & principes (16 règles) | 423 | ✅ v1.1 |
| 03 | Personas (6) | ~330 | ✅ v1 |
| 04 | Architecture cible | 670 | ✅ v1.1 |
| 05 | Contrats d'interface | 672 | ✅ v1 |
| 06 | Mode Installateur | 716 | ✅ v1 |
| 07 | Home / Dashboard | ~180 | ✅ v1 |
| 08 | Mur vidéo | ~85 | ✅ v1 |
| 09 | Recherche unifiée | ~55 | ✅ v1 |
| 10 | Assistant ajout caméra | ~70 | ✅ v1 |
| **11** | **Plateforme de plugins** ⭐ | **892** | ✅ v1 |
| 12 | Modules IA officiels | ~200 | ✅ v1 |
| 13 | Plugin Parking | ~180 | ✅ v1 |
| 14 | PTZ | ~55 | ✅ v1 |
| 15 | Plugin Automation | ~200 | ✅ v1 |
| 16 | Storage Manager | ~90 | ✅ v1 |
| 17 | GPU Manager | ~80 | ✅ v1 |
| 18 | Snapshots | ~50 | ✅ v1 |
| 19 | Zones | ~55 | ✅ v1 |
| 20 | Diagnostics intelligents | ~380 | ✅ v1 |
| 21 | Rapports | ~75 | ✅ v1 |
| 22 | Administration & RBAC | ~400 | ✅ v1 |
| 23 | API publique & SDK | ~85 | ✅ v1 |
| 24 | Marketplace | ~230 | ✅ v1 |
| 25 | Intégrations tierces | ~85 | ✅ v1 |
| 26 | Roadmap | ~330 | ✅ v1 |
| 27 | Versioning & dépréciation | ~55 | ✅ v1 |
| 28 | Grille de responsabilités | ~75 | ✅ v1 |

**Total : 28 chapitres livrés · ~7500 lignes · couverture complète du cahier des charges.**

## Conventions du document

- **Prescriptif** — le code actuel (v2.22.0) devra s'aligner sur ce document à terme. Les écarts existants sont documentés dans chaque chapitre sous « Écart avec la v2.22.0 ».
- **Décisions d'architecture (ADR)** — chaque décision structurante est numérotée (`ADR-XX`) avec `Contexte / Décision / Conséquences / Alternatives rejetées`. ADR-01→ADR-19 documentés à date.
- **16 règles opposables** — invocables en revue pour refuser une PR (chapitre 2 §2.3).
- **Diagrammes** — ASCII pour portabilité Git-friendly.
- **Modes dégradés** — chaque composant décrit obligatoirement son comportement quand une dépendance est HS.
- **Testabilité** — chaque module décrit ses tests d'acceptation (Given / When / Then).

## Comment contribuer

Chaque chapitre est livré en session dédiée avec allers-retours détaillés. Une fois validé, un tag Git `docs/chapter-XX-v1` fige la version. Les évolutions ultérieures sont versionnées `-v2`, `-v3` (ou amendements `v1.1`, `v1.2` pour ajouts non-breaking).

Export PDF : `pandoc *.md -o mg-vms-next-gen.pdf --toc --number-sections`.

