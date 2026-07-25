# Chapitre 7 — Home / Dashboard personnalisable

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `03-personas` · `20-diagnostics-intelligents`

La Home page n'est plus un tableau technique. Elle devient un **dashboard opérationnel personnalisable** que chaque utilisateur configure selon son rôle et son besoin.

---

## 7.1 Vision

Un opérateur ouvre le VMS le matin et voit **exactement** ce qui l'intéresse — pas un mur d'informations génériques. Un admin voit ses KPIs cross-site. Un installateur revient sur un site 6 mois plus tard et retrouve les widgets qu'il avait configurés.

Inspiration : Grafana dashboards, Home Assistant Lovelace, Notion pages.

---

## 7.2 Composition d'une Home

Une Home est composée de **widgets** posés sur une grille responsive (12 colonnes). Chaque widget :
- A une taille (colspan × rowspan).
- Une position (top-left auto ou drag&drop).
- Une config propre.
- Un titre éditable.

L'utilisateur peut créer **plusieurs dashboards** (onglets en haut) pour séparer les vues.

---

## 7.3 Widgets bundle core

| Widget | Description |
|---|---|
| `camera-live` | Flux live d'une caméra choisie |
| `camera-grid` | Mosaïque N×M de caméras |
| `latest-events` | Liste des N derniers événements IA |
| `latest-plates` | Liste des N dernières plaques |
| `latest-alerts` | Alertes actives ou récentes |
| `system-health` | Voyants Core/Plugins/GPU/Storage |
| `metric-gauge` | Jauge (CPU, RAM, GPU, VRAM, disk, network) |
| `metric-timeseries` | Graphique temporel N minutes |
| `cameras-status` | Liste caméras avec badge online/offline |
| `map-site` | Plan du site avec caméras positionnées |
| `weather` | Météo du site (source Open-Meteo) |
| `clock-timezones` | Horloges multi-fuseaux |
| `notes` | Bloc-notes texte markdown (partagé équipe) |
| `iframe` | Intégration iframe (Grafana, page externe) |
| `favorites` | Favoris de caméras d'un utilisateur |

**Extensibilité plugin** — un plugin peut ajouter ses propres widgets via manifest (`ui.widgets`). Exemples marketplace :
- `parking-occupation-chart` (plugin parking)
- `anpr-daily-count` (plugin fast-alpr)
- `home-assistant-state` (plugin HA integration)

---

## 7.4 Templates par persona

Templates de dashboard proposés à la première connexion selon le rôle :

### Template « Opérateur » (Sophie)
- Ligne 1 : `system-health` + `latest-alerts` (grande).
- Ligne 2 : `camera-grid` 3×3 des caméras les plus critiques.
- Ligne 3 : `latest-events` + `latest-plates`.

### Template « Admin » (Karim)
- Ligne 1 : KPIs cross-site (`metric-gauge` × 4 : CPU, GPU, Storage, Bandwidth).
- Ligne 2 : `cameras-status` (toutes) + `system-health`.
- Ligne 3 : `metric-timeseries` (événements 24h) + `latest-alerts`.

### Template « Intégrateur » (Marc)
- Ligne 1 : Chaque site en un widget `map-site` compact.
- Ligne 2 : `latest-alerts` cross-site.

### Template « Installateur » (Laëtitia)
- Vue simple : `camera-grid` 2×2 + `latest-alerts` + `latest-events` compact.

### Template « Résidentiel » (Nicolas)
- `camera-live` grand (portail).
- `weather` + `clock`.
- `latest-events` avec filtre "personne détectée".

---

## 7.5 UI d'édition

Mode édition activé par bouton `[✏ Éditer]` :
- Chaque widget devient déplaçable (drag&drop).
- Poignées de redimensionnement (coins).
- Menu `[⚙]` par widget : config, dupliquer, supprimer.
- Barre latérale « Widgets disponibles » (bundle + plugins).
- Bouton `[+ Ajouter widget]` ouvre catalogue avec preview.

Sauvegarde auto toutes les 5s en édition.

---

## 7.6 Persistence & partage

Chaque dashboard vit dans `db.dashboards` :
```json
{
  "id": "uuid",
  "name": "Ma vue nuit",
  "owner_user_id": "uuid",
  "shared_with": ["role:operator"],  // ou userIds
  "layout": [ ... ],  // grid layout par widget
  "widgets": [ ... ],
  "created_at": "...",
  "updated_at": "..."
}
```

Dashboards :
- **Personnels** (défaut) — visible par le créateur uniquement.
- **Partagés** — accessible via liens permissions (`role:X` ou `user:Y`).
- **Publics site** — accessible à tous les users du site (marqué "Épinglé").

Un admin peut définir un **dashboard par défaut** par rôle (nouveau user reçoit ce template).

---

## 7.7 Performance

- Chaque widget déclare son polling rate (défaut 5s).
- WebSocket réutilisé (chapitre 5) pour données temps-réel.
- Rendu React memoized par widget.
- Pas de re-render si data inchangée (diff via hash).

Cible : dashboard 20 widgets < 200ms first-render, < 5% CPU idle après chargement.

---

## 7.8 Tests d'acceptation

- **TA-7.1** — Créer dashboard perso avec 5 widgets < 3 min.
- **TA-7.2** — Sauvegarde auto : ajout widget → refresh page → widget présent.
- **TA-7.3** — Partage : dashboard partagé "role:operator" visible par tous les operators.
- **TA-7.4** — Plugin widget : installation `parking-manager` → widget `parking-occupation-chart` apparaît dans catalogue.

---

## Annexes

### A. Historique

| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale |
