# Chapitre 13 — Plugin Parking

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `11-plateforme-plugins` · `12-modules-ia-officiels` · `15-plugin-automation`

Le plugin `parking-manager` gère le comptage, l'occupation et la surveillance des places de parking en corrélation avec l'ANPR. Cible : centres commerciaux, entreprises, hôtels, résidences.

---

## 13.1 Vision

Un exploitant de parking doit pouvoir en 5 minutes :
- Dessiner le plan de son parking sur une image aérienne.
- Placer les zones caméra sur les places.
- Choisir les typologies (standard, PMR, VIP, borne électrique, employé).
- Voir en temps-réel l'occupation, l'historique, la corrélation LAPI.

---

## 13.2 Modèle de données

### 13.2.1 Parking

```json
{
  "id": "uuid",
  "name": "Parking P1 - Entrée principale",
  "site_id": "uuid",
  "capacity_total": 148,
  "map_image_url": "...",
  "spots": [ ... ],  // références vers db.plugin_data.parking.spots
  "counting_enabled": true,
  "occupancy_alert_threshold": 90  // % pour trigger event
}
```

### 13.2.2 Spot (place)

```json
{
  "id": "uuid",
  "parking_id": "uuid",
  "label": "A-12",
  "type": "standard|pmr|vip|reserved|electric|employee",
  "polygon": [[x, y], [x, y], ...],  // relatif au plan
  "camera_id": "uuid",              // caméra surveillante
  "camera_zone": [[x, y], ...],     // polygone dans le frame caméra
  "current_state": "free|occupied|reserved",
  "current_plate": null,             // dernière plaque détectée
  "last_state_change": "..."
}
```

### 13.2.3 Événement occupation

```json
{
  "id": "uuid",
  "parking_id": "uuid",
  "spot_id": "uuid",
  "action": "enter|exit",
  "timestamp": "...",
  "plate": "AB-123-CD",
  "duration_sec": 3720,  // si exit
  "camera_snapshot_url": "..."
}
```

---

## 13.3 Fonctionnalités

### 13.3.1 Éditeur de plan

Upload d'une image aérienne (schéma ou photo drone). L'admin dessine :
- Le contour global du parking (polygone).
- Les places (rectangles ou polygones).
- Les zones de circulation (allées).

Puis associe chaque place à une caméra + zone dans le frame caméra.

### 13.3.2 Détection occupation

Deux modes selon plugins IA installés :

**Mode YOLO** — le plugin `yolo-detection` détecte les véhicules dans les zones. Une place est occupée si un véhicule est dans son polygone > 30s.

**Mode LAPI** — le plugin ANPR lit la plaque à l'entrée/sortie. Corrélation avec la caméra qui a filmé la place occupée → attribution auto.

Les 2 modes combinés = fiabilité maximale (mode LAPI donne la plaque, YOLO confirme la présence physique).

### 13.3.3 Vue temps-réel

```
┌────────────────────────────────────────────────────────────┐
│ Parking P1 — 128/148 occupé (86%)                          │
│                                                             │
│ [🗺 Plan interactif]                                        │
│                                                             │
│  🟢 Libre : 20    🔴 Occupé : 120    🔵 PMR : 3/5           │
│  🟡 VIP : 5/10    ⚡ Électrique : 2/4                        │
│                                                             │
│ Temps moyen : 2h15                                          │
│ Rotation : 3.2 véhicules/place/jour                        │
│                                                             │
│ Recherche plaque : [_________________] [Chercher]           │
└────────────────────────────────────────────────────────────┘
```

Clic sur une place → détails (occupant, durée, historique).

### 13.3.4 Historique & statistiques

- Occupation heure par heure (graphique 24h).
- Taux d'occupation moyen par jour de semaine.
- Temps moyen de stationnement par typologie.
- Heatmap des places les plus utilisées.
- Recherche véhicule (plaque → historique de tous ses passages).
- Alerte dépassement (véhicule > N heures).

### 13.3.5 Corrélation LAPI

Quand un véhicule entre :
1. Caméra d'entrée détecte la plaque.
2. Caméra du parking détecte le véhicule sur place X.
3. Le plugin lie la plaque au spot X en < 5 min.
4. Écriture `parking_events` avec plate + spot.

Quand il sort :
- Caméra parking détecte départ.
- Caméra sortie confirme via plaque.
- Calcul durée + facturation potentielle (via plugin `parking-billing` v3.1+).

### 13.3.6 Prévisions (v3.1+)

ML léger sur historique 30 jours pour prédire l'occupation heure par heure jour+1. Utile pour :
- Affichage panneau extérieur « Complet dans 45 min à ce rythme ».
- Notification équipe si saturation attendue.
- Optimisation staff (agent de fluidification).

### 13.3.7 Rapports

Exports PDF/Excel/CSV :
- Occupation quotidienne / hebdo / mensuelle.
- Top plaques (habitués).
- Anomalies (véhicules > 24h, plaques inconnues répétées).
- Taxes ADS (Autorisation Droit de Stationner) si applicable.

---

## 13.4 UI

Onglet `/plugins/parking/{parking_id}` avec sous-onglets :
- **Plan** — vue temps-réel interactive.
- **Historique** — timeline occupation.
- **Statistiques** — graphiques + KPIs.
- **Places** — CRUD places.
- **Recherche** — véhicule par plaque.
- **Alertes** — configuration alertes dépassement.

**data-testid** : `parking-plan-{id}`, `parking-spot-{spot_id}`, `parking-stats`, `parking-search-plate`, etc.

---

## 13.5 Intégrations

### 13.5.1 Home Assistant

Publication MQTT `mgvms/{site}/parking/{id}/occupation` retained. Home Assistant lit via `mqtt_json` sensor → automation lumières, panneaux, etc.

### 13.5.2 Automation (chapitre 15)

Triggers exposés :
- `parking.spot_occupied`
- `parking.spot_freed`
- `parking.occupancy_threshold` (défaut 90%)
- `parking.overstay_detected` (véhicule > X heures)

Actions exposées :
- `parking.reserve_spot(spot_id, until)` — pour réservation VIP.
- `parking.count_available(type)` — pour affichage.

### 13.5.3 Node-RED / Grafana

Via API REST publique `/api/v1/plugins/parking/*` (chapitre 5) — plus WebSocket temps-réel.

---

## 13.6 Configuration installateur

Le plugin `parking-manager` propose un mini-wizard à l'installation :
1. Upload plan.
2. Nommage parking.
3. Association caméras.
4. Dessin des places (aide automatique via YOLO : détection véhicules → suggestion places).
5. Test occupation en direct.

---

## 13.7 Tests d'acceptation

- **TA-13.1** — Création parking + 20 places + association caméras < 10 min.
- **TA-13.2** — Détection occupation : véhicule entré → place marquée occupée en < 60s.
- **TA-13.3** — Corrélation LAPI : plaque entrée + spot occupé lié en < 5 min.
- **TA-13.4** — Trigger threshold : occupation dépasse 90% → événement bus + notification.
- **TA-13.5** — Export CSV : 24h d'événements exportables.

---

## Annexes

### A. Historique

| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale |
