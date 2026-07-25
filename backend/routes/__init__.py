"""MG-VMS routes/ — modularisation `routers.py` (ADR-01 · chantier C roadmap v2.30).

**Statut v2.30 (Preview NG)** : structure du package posée. Les endpoints
`/api/plugins/*` fonctionnels vivent temporairement dans `routers.py` en
attendant l'extraction complète prévue en v3.0.

**Plan de refonte v3.0** :

Chaque domaine devient un module dédié avec son propre `APIRouter`,
enregistré dans `server.py`. Cible : chaque fichier < 300 lignes.

    routes/
    ├── __init__.py          (ce fichier — index de la refonte)
    ├── auth.py              (~ 150 lignes)
    ├── cameras.py           (~ 250 lignes)
    ├── streams.py           (~ 200 lignes)
    ├── events.py            (~ 100 lignes)
    ├── alerts.py            (~ 80 lignes)
    ├── plates.py            (~ 150 lignes)
    ├── ai_config.py         (~ 120 lignes)
    ├── diagnostics.py       (~ 280 lignes ← candidat prochain sprint)
    ├── users.py             (~ 100 lignes)
    ├── sites.py             (~ 80 lignes)
    ├── plugins.py           (~ 60 lignes)
    ├── system.py            (~ 100 lignes)
    ├── dashboard.py         (~ 80 lignes)
    └── notifications.py     (~ 100 lignes)

**Ordre de refonte recommandé** (par risque croissant) :
1. `diagnostics.py` (déjà bien isolé, peu de dépendances croisées)
2. `plugins.py` + résoudre conflit avec l'ancien `plugins.py` racine
3. `users.py`, `sites.py`, `alerts.py` (CRUD simples)
4. `cameras.py`, `streams.py` (le plus critique — nécessite testing agent complet)
5. `ai_config.py`, `events.py`, `plates.py`

**Contrat de migration** : chaque extraction est une PR séparée avec :
- Tests de non-régression (chapitre 5 §5.11 tests d'acceptation).
- Preserving URLs (pas de breaking).
- Un tag Git `refactor/routes-<domaine>`.
"""
