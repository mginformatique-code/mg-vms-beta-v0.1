# Chapitre 18 — Snapshots

> **Version** : v1.0 · **Date** : 2026-07-24

Capture d'image instantanée d'une caméra. Cascade de fallbacks pour garantir un snapshot même sous conditions dégradées.

## 18.1 Cascade de sources

Ordre de priorité pour obtenir un snapshot :
1. **Snapshot ONVIF** — endpoint `GetSnapshotUri` officiel caméra.
2. **Snapshot HTTP** — endpoint `/cgi-bin/snapshot.cgi` (Hikvision, Dahua) si détecté.
3. **Frame RTSP** — extraction 1 frame via go2rtc `frame.jpeg` (uniquement démo/exception, cf. ADR-04).
4. **Dernière image cache** — dernier frame reçu en RAM (`frame_source.get_latest_frame`).
5. **Placeholder** — image "Snapshot indisponible" si tout échoue.

## 18.2 Modes

- **Live** — pris à la demande (cliqué depuis UI).
- **Périodique** — cronjob par caméra (défaut : 5 min pour caméras critiques).
- **Sur événement** — trigger IA / alerte.
- **Timelapse** — série de snapshots pour générer video accélérée.

## 18.3 UI

- Bouton "Snapshot" sur chaque cellule mur vidéo.
- Bouton "Pause" pour geler un flux temporairement.
- Bouton "Actualiser" pour forcer nouveau snapshot.
- Preview modal + boutons [Télécharger] [Partager (lien signé 24h)] [Envoyer email].

## 18.4 Format

- JPEG qualité 85 par défaut.
- Résolution flux HD si dispo.
- EXIF metadata : camera name, timestamp, GPS (si site géolocalisé).
- Signature HMAC en EXIF pour intégrité (v3.1+).

## 18.5 Tests

- TA-18.1 : Cascade — caméra ONVIF snapshot OK.
- TA-18.2 : Fallback dernier frame quand caméra offline.
- TA-18.3 : Placeholder affiché si tout échoue.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
