# Chapitre 19 — Zones (éditeur)

> **Version** : v1.0 · **Date** : 2026-07-24

Éditeur visuel de zones (polygones) sur images caméras. Utilisé par `zone-analytics`, `parking-manager`, `face-recognition`, etc.

## 19.1 Fonctionnalités éditeur

- Dessin polygone (clics successifs, double-clic pour fermer).
- Rectangle rapide (drag).
- Ligne (pour CrossLine).
- **Zoom / pan** sur snapshot (haute-résolution).
- **Magnétisme** — snap grid 8×8 pixels (optionnel).
- **Grille** — overlay grille visible (assist visuel).
- **Copie / collage** — copier une zone d'une caméra à une autre (utile caméras jumelles).
- **Import / export** — JSON polygones portables.
- **Prévisualisation IA** — overlay des détections courantes sur le snapshot édité.
- **Test temps-réel** — jouer 30s de flux + voir zones actives.

## 19.2 Modèle

```json
{
  "id": "uuid",
  "camera_id": "uuid",
  "name": "Zone parking employés",
  "type": "polygon|rectangle|line",
  "points": [[x1, y1], [x2, y2], ...],
  "color": "#00E5FF",
  "used_by": ["plugin_name.scenario_id"]  // références par plugins
}
```

## 19.3 UI

Éditeur plein écran embed dans les pages plugin qui en ont besoin. Composant React réutilisable `<ZoneEditor camera={cam} zones={zones} onChange={...} />`.

## 19.4 Tests

- TA-19.1 : Dessin polygone 5 sommets → sauvegarde OK.
- TA-19.2 : Copie zone A → B, adaptation ratio résolution.
- TA-19.3 : Prévisualisation IA affiche détections dans/hors zone.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
