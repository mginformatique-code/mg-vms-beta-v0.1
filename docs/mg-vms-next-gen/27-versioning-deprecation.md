# Chapitre 27 — Versioning & dépréciation

> **Version** : v1.0 · **Date** : 2026-07-24

## 27.1 SemVer

MG-VMS suit strictement SemVer 2.0 : `MAJOR.MINOR.PATCH`.

- **MAJOR** — breaking changes (nouvelle API `/api/v2`, refonte manifest plugins…).
- **MINOR** — features rétro-compatibles.
- **PATCH** — bug fixes, sécurité.

Les plugins suivent leur propre SemVer, indépendant du core.

## 27.2 Compatibilité

Un plugin `mgvms_core: ">=3.0.0,<4.0.0"` fonctionne sur toute version 3.x. Refus explicite en cas de mismatch (chapitre 11 §11.2.2).

## 27.3 Politique de dépréciation

- Une feature dépréciée est **d'abord marquée** dans le changelog + header HTTP `Deprecation: true`.
- Elle reste supportée **24 mois minimum**.
- Après 24 mois, retrait dans une MAJOR.
- La migration path est documentée dans le CHANGELOG.

## 27.4 LTS

- Versions **LTS** (Long Term Support) : v3.0, v4.0, v5.0.
- Chaque LTS supportée 3 ans (bug fixes + sécurité).
- Recommandé prod pour intégrateurs.

## 27.5 Beta / RC

- Beta : `3.0.0-beta.1`, `-beta.2`… — non prod.
- Release Candidate : `3.0.0-rc.1` — test final.
- Feature en beta max 6 mois (chapitre 2 AP-09).

## 27.6 Tests

- TA-27.1 : Plugin v1.x continue à fonctionner sur core v3.5.x sans changement.
- TA-27.2 : Endpoint déprécié → header `Deprecation` + `Sunset` renseigné.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
