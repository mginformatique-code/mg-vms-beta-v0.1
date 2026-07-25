# Chapitre 21 — Rapports

> **Version** : v1.0 · **Date** : 2026-07-24

Génération de rapports PDF, CSV, Excel, avec planification. Utilisés par Karim (rapport hebdo direction), Marc (rapport installation client), Sophie (rapport nuit).

## 21.1 Types de rapports

- **Rapport d'incidents** — période, caméra, ou site. Timeline + causes probables + snapshots.
- **Rapport LAPI** — passages plaques, statistiques, top 10 habitués, blacklist.
- **Rapport parking** — occupation, temps moyen, revenus (si billing).
- **Rapport IA** — détections par catégorie, faux positifs supposés.
- **Rapport GPU / système** — utilisation, incidents, MTBF caméras.
- **Rapport d'installation** — post-wizard (chapitre 6 §6.5).
- **Rapport RGPD** — accès données, exports, consultations vidéo (chapitre 22 §22.6).

## 21.2 Formats

- **PDF** — via WeasyPrint (chapitre 6 ADR-14). Templates HTML/CSS.
- **CSV** — BOM UTF-8, Excel-compatible (chapitre 5 §5.1.6).
- **Excel (.xlsx)** — via openpyxl, formatage cellules.
- **JSON** — pour intégration API tierce.

## 21.3 Planification

Un rapport peut être :
- **Ponctuel** — génération à la demande.
- **Planifié** — cron (quotidien 08:00, hebdo lundi 07:00, mensuel 1er du mois).
- **Livraison automatique** — email SMTP, upload SFTP, publication S3.

Interface `/rapports/schedules` :
```
📊 Rapport hebdo direction              ⏰ Lun 07:00      → 3 destinataires    [Éditer]
📊 Rapport incident quotidien           ⏰ Tous les jours 06:00  → SMTP        [Éditer]
📊 Rapport RGPD trimestriel             ⏰ 1er de chaque trimestre → S3        [Éditer]
```

## 21.4 Templates

Chaque type de rapport a un template HTML/CSS dans `/data/reports/templates/`. Modifiable par admin (éditeur intégré ou upload).

Variables Jinja2 : `{{ site.name }}`, `{{ period }}`, `{{ stats.incidents_count }}`, etc.

## 21.5 Signature

Rapports critiques (installation, RGPD) signés HMAC-SHA256 (EXIF pour PDF via QR code) — traçabilité.

## 21.6 Tests

- TA-21.1 : Génération rapport incidents 24h → PDF < 8s.
- TA-21.2 : Rapport planifié → email envoyé automatiquement.
- TA-21.3 : CSV BOM UTF-8 → LibreOffice + Excel OK.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
