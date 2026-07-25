# Chapitre 24 — Marketplace de plugins

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `11-plateforme-plugins` · `23-api-publique`

Ce chapitre définit le **Marketplace** — catalogue public officiel de plugins MG-VMS. Il est le pendant communautaire du chapitre 11 (Plateforme de plugins).

---

## 24.1 Vision

Le Marketplace est **le hub de l'écosystème MG-VMS**. Comme Docker Hub, npm ou Home Assistant Community Store, il permet à des dizaines/centaines de développeurs de publier des plugins, et aux utilisateurs de les installer en 1 clic.

**Objectifs** :
- Baisse de la barrière d'installation (« installer YOLO » = 1 clic vs « clone repo + build Docker + config ».
- Communauté vibrante (200+ plugins à 12 mois).
- Confiance graduée (badges Officiel / Verified / Community).
- Fondation économique pour dev tiers (v3.5+ plugins payants).

---

## 24.2 Architecture

### 24.2.1 Composants

```
                    Internet
                       │
   ┌───────────────────┼─────────────────────┐
   │                   │                     │
   ▼                   ▼                     ▼
plugins.mg-vms.io    api.plugins.mg-vms.io    cdn.plugins.mg-vms.io
  (Frontend web)     (API REST catalogue)     (téléchargements .mgplugin)
                       │
                       ▼
                    Registry DB
                    (PostgreSQL — plugins metadata)
                       │
                       ▼
                   Storage (S3)
                    (fichiers .mgplugin signés)
```

- **Frontend web** — catalogue navigable, screenshots, ratings, commentaires.
- **API REST** — endpoint public consommé par le Plugin Manager MG-VMS.
- **CDN** — distribution des packages `.mgplugin` (zip + signature GPG).
- **Registry DB** — métadonnées, versions, stats, ratings, review status.

### 24.2.2 Format `.mgplugin`

Un package `.mgplugin` est un **ZIP signé GPG** contenant :

```
plugin.mgplugin
├── manifest.yaml           # (obligatoire)
├── plugin.py               # (ou plugin.js selon runtime)
├── requirements.txt
├── models/
├── config/schema.json
├── ui/
├── docs/
├── LICENSE
└── manifest.yaml.asc       # signature GPG détachée
```

Nommage : `<name>-<version>.mgplugin` (ex. `yolo-detection-1.4.2.mgplugin`).

---

## 24.3 Badges & niveaux de confiance

Chaque plugin est classé selon son niveau de review :

| Badge | Signification | Vérification |
|---|---|---|
| ⭐ **Officiel** | Édité par l'équipe MG-VMS | Code review interne, tests CI complets, support commercial possible |
| ✅ **Verified** | Auteur vérifié, plugin reviewé | Identité auteur (signature GPG, historique GitHub), audit sécurité, tests CI OK |
| 🌐 **Community** | Contribution communautaire | Metadata validée automatiquement, signature GPG optionnelle |
| ⚠️ **Beta** | Version pré-release | Non-production, warning permanent UI |
| 🚫 **Retired** | Plugin retiré (désuet ou problème) | Marqué retiré, installation refusée, alerte utilisateurs existants |

**Politique** : les plugins avec accès `admin` ou `camera.ptz.control` doivent être **Verified** minimum. Les Community ont sandbox container forcé (ADR-17).

---

## 24.4 Publication d'un plugin

### 24.4.1 Prérequis développeur

- Compte Marketplace (email + 2FA).
- Clé GPG publiée sur son profil (ou clé signée par MG-VMS).
- Repo GitHub public du plugin (pour audit code).
- Manifest valide + tests + docs.

### 24.4.2 Processus

```bash
# 1. Initialisation
mgvms-cli plugin init --template=frame-analyzer my-plugin
cd my-plugin
# ... développement ...

# 2. Test local
mgvms-cli plugin test  # exécute les tests + validation manifest

# 3. Build package
mgvms-cli plugin build --sign-with=my-key.gpg
# produit : my-plugin-1.0.0.mgplugin + .asc

# 4. Publish
mgvms-cli plugin publish my-plugin-1.0.0.mgplugin
# → upload sur Marketplace, opens PR pour review
```

### 24.4.3 Review process

1. **Automated checks** (< 5 min) :
   - Manifest schema valide.
   - Signature GPG valide.
   - Aucun dep bloqué (blacklist packages malveillants connus).
   - Tests CI passent (containerisé avec MG-VMS de référence).
   - Scan sécurité (Trivy, Bandit pour Python).
2. **Manual review** (verified/officiel uniquement, 2-5 jours) :
   - Lecture du code publié.
   - Vérification identité auteur.
   - Test manuel sur banc de test.
3. **Publication** :
   - Push sur Registry.
   - Distribution CDN.
   - Notification email au dev.
4. **Post-publication** :
   - Monitoring stats (installations, crashes remontés).
   - Rapport hebdomadaire au dev.

### 24.4.4 Mise à jour

- Version SemVer (`major.minor.patch`).
- Compat range dans manifest (`mgvms_core: ">=3.0.0,<4.0.0"`).
- Changelog obligatoire.
- Migration automatique config si champ renommé (schema `migrations[]` dans manifest).

---

## 24.5 Consommation depuis MG-VMS

### 24.5.1 UI /plugins onglet « Catalogue »

L'utilisateur voit :
- Barre de recherche + filtres (catégorie, badge, note, langue).
- Liste des plugins triée par pertinence (installations + note + fraîcheur).
- Détail par plugin : screenshots, README, changelog, dépendances, prix (si payant).
- Bouton **[Installer]** — téléchargement + vérification signature + install en < 30 s.

### 24.5.2 Registry miroir (air-gap)

Environnements sans internet peuvent utiliser un miroir local via env `MGVMS_PLUGIN_REGISTRY_URL=https://registry-mirror.local`.

`mgvms-cli registry sync` permet à un admin de synchroniser un miroir local à partir du Marketplace officiel.

### 24.5.3 API publique (extrait)

```
GET https://api.plugins.mg-vms.io/v1/plugins?category=ai&search=yolo
GET https://api.plugins.mg-vms.io/v1/plugins/yolo-detection
GET https://api.plugins.mg-vms.io/v1/plugins/yolo-detection/versions
GET https://api.plugins.mg-vms.io/v1/plugins/yolo-detection/versions/1.4.2/download
POST https://api.plugins.mg-vms.io/v1/plugins/yolo-detection/ratings  (auth)
```

---

## 24.6 Modèle économique

### 24.6.1 Plugins gratuits (défaut)

Majorité du catalogue. Publication et consommation gratuites. Coût pour MG-VMS = bande passante CDN + storage (mutualisés).

### 24.6.2 Plugins freemium

Plugin gratuit + service backend payant (ex. Plate Recognizer cloud avec quota API).

Le paiement est géré côté fournisseur du service. MG-VMS n'intervient pas.

### 24.6.3 Plugins payants (v3.5+)

Modèle license key :
- Utilisateur achète une clé sur le Marketplace.
- Clé validée par le plugin au chargement (`ctx.license.check()`).
- Serveur licence hébergé par MG-VMS (validation cryptographique offline possible via signatures).

Revenue share : 70% dev / 30% MG-VMS (aligned Apple App Store / Google Play).

### 24.6.4 Anti-abus

- Un plugin qui exfiltre des données caméra sans consentement → retrait immédiat + ban dev.
- Un plugin qui contient des malwares → retrait + notification légale.
- Rating fraudeur (fausses reviews) → suppression rating + warning dev.

---

## 24.7 Sécurité communautaire

### 24.7.1 Signalement

Chaque plugin a un bouton **[Signaler un problème]** ouvrant un formulaire :
- Type : bug, sécurité, mauvais comportement, spam.
- Description.
- Preuves (logs, screenshots).

Traité par l'équipe modération MG-VMS sous 48h.

### 24.7.2 CVE & vulnerabilities

Une vulnérabilité critique dans un plugin déclenche :
1. Alerte immédiate CVE Marketplace.
2. Notification aux utilisateurs ayant installé le plugin (via MG-VMS push).
3. Recommandation MàJ ou désinstallation.
4. Publication d'un post mortem après correction.

### 24.7.3 Deprecation

Un plugin peut être marqué `deprecated` par son auteur (successor disponible) ou par MG-VMS (auteur inactif > 12 mois + issues critiques non résolues).

Behavior :
- L'installation reste possible avec warning.
- Les utilisateurs existants reçoivent une notif.
- Après 6 mois de deprecated → `retired` (installation bloquée).

---

## 24.8 Métriques Marketplace

**Cibles à 12 mois post-v3.0** :
- Plugins publiés : ≥ 200 total (dont ≥ 20 Officiel, ≥ 50 Verified).
- Installations cumulées : ≥ 10 000.
- Développeurs actifs : ≥ 30.
- Note moyenne : ≥ 4.0/5.
- Temps médian review Verified : ≤ 5 jours.
- Taux de plugins retirés pour raison sécurité : ≤ 2%.

---

## 24.9 ADR

### ADR-24 — Registry PostgreSQL au lieu de Git

**Contexte** : deux approches (base SQL comme Docker Hub, ou repo Git comme Homebrew).
**Décision** : PostgreSQL — permet requêtes riches (search, filters, stats), gestion utilisateurs propre.
**Conséquences** : infra hébergée par MG-VMS, backup responsable.

### ADR-25 — Signature GPG obligatoire pour Verified+, optionnelle Community

**Contexte** : sécurité supply chain.
**Décision** : plugins Community peuvent être non-signés (barrière basse), mais sandbox container forcé. Verified et Officiel signés obligatoirement.
**Conséquences** : équilibre ouverture communauté / sécurité.

---

## Annexes

### A. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : architecture Marketplace · 5 badges · processus publication + review · modèle éco · sécurité · 2 ADR |
