# Chapitre 14 — PTZ

> **Version** : v1.0 · **Date** : 2026-07-24

Contrôle Pan / Tilt / Zoom des caméras compatibles. Base intégrée au core, fonctions avancées via plugin `ptz-advanced`.

---

## 14.1 Base core

- **Joystick UI** : commandes pan/tilt/zoom via clavier flèches, souris drag ou joystick physique (via WebHID API).
- **Preset positions** : sauvegarde de N positions par caméra, rappel en 1 clic.
- **Vitesse** : slider (1-10).
- **Home** : bouton retour position par défaut.
- **Auto-focus / Auto-iris** : toggles selon capacité ONVIF.

Protocoles supportés core : ONVIF PTZ (majoritaire). Autres protocoles (Pelco-D, Visca, etc.) via plugin `ptz-protocols-legacy`.

---

## 14.2 Plugin `ptz-advanced` (v3.1+)

Fonctions avancées :
- **Tours** — séquence de presets avec durée par preset (surveillance patrouille).
- **Calendrier** — activation/désactivation tours selon planning (jour/nuit, jours ouvrés).
- **Tracking IA** — suivi automatique d'un objet détecté (personne, véhicule). Le plugin appelle `ptz.follow(bbox)` en boucle.
- **Zoom automatique** — zoom sur un objet d'intérêt (plaque, visage).
- **Retour auto** — après inactivité, retour position home après N min.

---

## 14.3 Permissions

- `manage_ptz` — permet joystick + presets.
- `manage_ptz_tours` — permet création/suppression tours.
- Chaque commande PTZ est **auditée** (R09) avec user, caméra, commande, résultat.

## 14.4 Tests

- TA-14.1 : Envoi commande pan → caméra bouge en < 500ms.
- TA-14.2 : Preset 3 sauvegardé + rappelé → position identique.
- TA-14.3 : Tour 5 presets × 30s → cycle stable 5 min.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
