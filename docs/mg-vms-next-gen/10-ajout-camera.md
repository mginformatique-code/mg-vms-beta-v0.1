# Chapitre 10 — Assistant d'ajout de caméra

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `06-mode-installateur` · `11-plateforme-plugins`

Wizard dédié pour ajouter une caméra en post-installation (bouton **[+ Ajouter caméra]** dans `/cameras`).

---

## 10.1 Parcours (7 étapes, ~ 3 minutes)

### Étape 1 — Mode de découverte
- ○ Découverte ONVIF automatique (LAN)
- ○ Ajout manuel (RTSP URL)
- ○ Sélection depuis fichier import (CSV batch)

### Étape 2 — Découverte / saisie
Si ONVIF : scan et sélection caméra. Si manuel : formulaire URL + credentials. Si CSV : upload puis mapping colonnes.

### Étape 3 — Test connectivité
- ffprobe validation URL RTSP.
- Détection auto codec, résolution, fps.
- Preview snapshot < 5s.

### Étape 4 — Choix des flux
- Flux HD (principal) : sélection profil ONVIF.
- Flux SD (secondaire) : sélection profil ONVIF.
- Transport : TCP (défaut) ou UDP.

### Étape 5 — Configuration
- Nom (auto-suggéré + éditable).
- Site (dropdown si multi-site).
- Codec (auto-détecté + override).
- Bascule SD/HD auto (défaut : selon taille cellule).

### Étape 6 — Plugins IA (dynamique)
Liste des plugins FrameAnalyzer installés + PlateRecognizer + Face + Smoke + Fire + PPE. Cases à cocher par plugin. Config par plugin possible (mini-formulaire schema).

### Étape 7 — Zones & scénarios
- Dessin de zones sur snapshot (si plugins `zone-analytics` ou `parking-manager` cochés).
- Choix scénarios (crossline, intrusion, loitering, counting).
- Calendrier d'armement.

### Bilan
Résumé + test end-to-end (2-3 frames analysées) + confirmation.

---

## 10.2 Réutilisable

L'assistant partage sa logique avec le Mode Installateur (chapitre 6 Étape 4/5). Les composants React sont mutualisés.

---

## 10.3 Tests

- TA-10.1 : Ajout caméra ONVIF en < 3 min.
- TA-10.2 : Ajout batch CSV 10 caméras en < 2 min.
- TA-10.3 : Test connectivité échec → warning avec cause probable, option [Ignorer] [Retenter].

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
