# Chapitre 9 — Recherche unifiée

> **Version** : v1.0 · **Date** : 2026-07-24

Un seul champ de recherche global dans le header — accessible via `Ctrl+K` (raccourci universel). Cherche à travers **toutes les ressources** : caméras, plaques, événements, alertes, utilisateurs, plugins, docs.

---

## 9.1 Portée de la recherche

- Caméras (nom, IP, site).
- Plaques ANPR (fuzzy).
- Événements IA (label, camera, période).
- Alertes (sévérité, message).
- Utilisateurs (nom, email).
- Plugins (nom, catégorie).
- Sites (nom, adresse).
- Docs (contenu chapitres cahier des charges publiés).

## 9.2 UI

Popup type Spotlight / Command Palette :

```
🔍  [rechercher_______________]  Ctrl+K
   ─────────────────────────────────
   Récents
   • AB-123-CD (plaque, 3 hits)
   • Entrée principale (caméra)
   ─────────────────────────────────
   Résultats (12)
   📷 Caméra "Parking Nord"          → /cameras/uuid
   🚗 Plaque AB-123-CD (24 passages)  → /plates/AB123CD
   🚨 Alerte "blacklist" 14:32        → /alerts/uuid
   📖 Doc "Chapitre 6 Mode Installateur" → /docs/06
   ...
```

- Filtres inline : `type:camera`, `date:today`, `severity:critical`.
- Résultats groupés par type, triés par pertinence.
- Sélection clavier ↑↓ + Enter.

## 9.3 Backend

Index consolidé via requête multi-collection Mongo avec `$search` (Atlas) ou implémentation MongoDB text index natif.

Réponse en < 300ms P95 pour 100k documents.

## 9.4 Tests

- TA-9.1 : Ctrl+K ouvre la palette < 100ms.
- TA-9.2 : Query "AB-123" → plaques matching en < 300ms.
- TA-9.3 : Filtre `type:camera` restreint aux caméras uniquement.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
