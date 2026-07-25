# Chapitre 8 — Mur vidéo

> **Version** : v1.0 · **Date** : 2026-07-24

Le Mur vidéo est l'écran de surveillance principal pour les opérateurs. Layouts illimités, drag&drop, favoris, murs spécialisés (IA, LAPI, PTZ, Parking).

---

## 8.1 Vision

Un opérateur configure ses murs une fois, y revient chaque prise de poste. Zéro friction : le mur charge en < 2s, les flux s'affichent en < 3s, le basculement SD↔HD est instantané au double-clic.

Support multi-écrans natif : Sophie peut ouvrir 6 murs sur 6 écrans simultanément.

---

## 8.2 Layouts

### 8.2.1 Grilles prédéfinies

- 1×1 (single), 2×2, 3×3, 4×4, 5×5, 6×6, 8×8.
- Layouts spéciaux : 1+5 (une grande + 5 petites), 1+7, 1+12, 2+8, 3+9.

### 8.2.2 Layouts custom

L'utilisateur peut dessiner sa grille : chaque cellule est un rectangle librement placé sur une grille 32×18 (16:9 fine). Ex : 1 caméra 16×9 en haut, 4 caméras 4×5 en bas.

### 8.2.3 Cellules

Chaque cellule contient :
- Un flux caméra (mode direct WebRTC) ou un widget (map, panneau alertes, message).
- Un overlay optionnel (nom caméra, timestamp, badge status, détections IA).
- Double-clic = plein écran de la cellule (bascule HD auto).

---

## 8.3 Modes de mur spécialisés

- **Mur Live standard** — pure video.
- **Mur IA** — cellules avec overlays détections temps-réel (bbox, labels).
- **Mur LAPI** — cellules + panneau latéral avec dernières plaques détectées.
- **Mur PTZ** — cellules réservées caméras PTZ + joystick embedded.
- **Mur Parking** — cellules + carte occupation temps-réel.

Ces variantes sont soit built-in soit des widgets tirés du bundle plugins.

---

## 8.4 Fonctionnalités

- **Drag&drop** — assigner une caméra à une cellule.
- **Favoris** — un mur peut être sauvegardé comme favori (raccourci sidebar).
- **Cycling** — un mur peut cycler entre N configurations toutes les X secondes (utile écrans publics).
- **Push d'alerte** — quand une alerte critique arrive, la caméra concernée peut prendre le focus (option activable).
- **Multi-écran** — Ctrl+E ouvre le mur dans une nouvelle fenêtre (déplaçable sur autre écran).
- **Enregistrement mur** — bouton `[⏺ Enregistrer]` capture le mur en local (webm) 30s.

---

## 8.5 Performances

Contraintes :
- WebRTC par cellule (H.264 pass-through).
- Fallback MJPEG si ICE échoue.
- SD par défaut pour cellules petites (< 400px). HD pour cellules grandes.
- Bascule SD↔HD automatique selon la taille de rendu (rebindings dynamiques WebRTC).

Cible : mur 16 cellules SD sur laptop moyen (i5 8th gen) < 40% CPU, GPU décodage.

---

## 8.6 Tests d'acceptation

- TA-8.1 : Mur 3×3 charge et affiche 9 caméras en < 3s.
- TA-8.2 : Double-clic cellule → HD passe en < 1s.
- TA-8.3 : Push alerte : caméra en alerte critique → focus auto activé.
- TA-8.4 : Cycling 3 layouts × 10s = bascule fluide sans coupure flux.

---

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
