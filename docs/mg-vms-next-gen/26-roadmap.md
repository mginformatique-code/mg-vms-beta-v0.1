# Chapitre 26 — Roadmap

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : tous les chapitres précédents

Ce chapitre planifie la livraison de MG-VMS Next Generation. Il traduit tous les chapitres précédents (architecture, plateforme plugins, modules, UX) en un **plan de livraison par version** avec critères de sortie et jalons.

---

## 26.1 Principes de roadmap

**Petites évolutions validées une par une** (règle utilisateur affichée dès la première session).

Chaque version majeure a :
- Une **thèse produit** en une phrase.
- Un **périmètre gelé** (aucun feature creep en cours de sprint).
- Des **critères de sortie** objectifs (tests passés, couverture, KPIs).
- Une **date cible** ± 2 mois.
- Un **plan de repli** si le calendrier glisse.

**Aucune feature n'entre dans une version sans avoir son chapitre validé** (règle R11).

---

## 26.2 Vue macro

```
                v2.22.0 (actuel)
                    │
                    │ ← consolidation ~2 mois
                    ▼
             v2.30 (Preview NG)     ← rendre v2.x forward-compatible
                    │
                    │ ← chantier plateforme ~6-9 mois
                    ▼
                v3.0 « Plateforme »   ← Q3 2026
                    │
                    │ ← Marketplace ~3 mois
                    ▼
                v3.1 « Écosystème »   ← Q4 2026
                    │
                    │ ← extensibilité + SDK avancés ~4 mois
                    ▼
                v3.2 « Multi-langages »  ← Q1 2027
                    │
                    │ ← fédération ~6 mois
                    ▼
                v3.5 « Multi-site »   ← Q3 2027
                    │
                    ▼
                v4.0 (2028+)  ← référence marché francophone
```

---

## 26.3 v2.30 — Preview NG (transition, ~2 mois)

**Thèse** : rendre l'existant compatible avec la vision v3.0 sans breaking change utilisateur.

**Périmètre** :
- ✅ Version URL `/api/v1/*` en parallèle de `/api/*` (compat 24 mois).
- ✅ Réponses d'erreur uniformisées `{error: {code, message, ...}}` en parallèle du legacy.
- ✅ Structure modulaire du backend : `routes/`, `services/`, `models/` (ADR-01).
- ✅ Chiffrement Fernet des secrets caméra (R05 / ADR-06) + migration data.
- ✅ Contrat `require_permission()` sur 100% des endpoints admin (R09).

**Critères de sortie** :
- Backend passe 100% des tests d'iteration précédente + nouveau contract test API v1.
- Aucune régression fonctionnelle vs v2.22.0.
- Documentation migration `/api → /api/v1` publiée.
- Perf identique v2.22.0 (aucune dégradation > 5%).

---

## 26.4 v3.0 « Plateforme » (~6-9 mois, cible Q3 2026)

**Thèse** : MG-VMS devient une plateforme dont tout est plugin sauf le noyau.

### 26.4.1 Périmètre core

- ✅ **Plugin Manager** complet (chapitre 11 §11.4).
  - Chargement in-process + sub-process.
  - Health monitoring par plugin.
  - Quotas CPU/RAM/GPU/disk.
  - Sandbox capabilities déclaratives.
  - UI /plugins (installés + catalogue + logs).
- ✅ **Interfaces standardisées** (chapitre 11 §11.3).
  - FrameAnalyzer, PlateRecognizer, EventConsumer, ActionProvider, TriggerProvider, StorageBackend, AuthProvider, UIExtension, DomainService, CustomPlugin.
- ✅ **SDK Python v1** (`mgvms-plugin-sdk`) publié sur PyPI.
  - Templates de projet (`mgvms-cli plugin init`).
  - Type hints complets, async natif.
- ✅ **Manifest YAML** `apiVersion: mgvms.io/v1` (ADR-18).
- ✅ **Namespace DB isolé** par plugin (ADR-19).
- ✅ **Mode Installateur** (chapitre 6) intégré :
  - 8 étapes + 2 optionnelles.
  - Rapport PDF.
  - Reprise interrompue.
- ✅ **Diagnostics intelligents** (chapitre 20) :
  - Moteur de règles + 100+ règles bundle.
  - Dialog cause probable / actions.
  - Notifications proactives.
- ✅ **Multi-ANPR** (chapitre 11 §11.6.1) : 3 modes.
- ✅ **RBAC hiérarchique** (chapitre 22) :
  - 5 rôles built-in + custom.
  - Isolation par site.
  - Audit intégral.
- ✅ **API contrats** (chapitre 5) :
  - REST /api/v1 stable.
  - WebSocket canaux + filtres + heartbeat.
  - MQTT publish/subscribe.
  - OpenAPI 3.1 auto-généré.

### 26.4.2 Plugins officiels bundle

Livrés avec le core (installables mais désinstallables) :
- ⭐ `yolo-detection` (v1.0) — YOLOv11 CPU/GPU
- ⭐ `fast-alpr` (v1.0) — ANPR CPU-ONNX
- ⭐ `smtp-notifier` (v1.0)
- ⭐ `discord-notifier` (v1.0)
- ⭐ `telegram-notifier` (v1.0)
- ⭐ `zone-analytics` (v1.0) — CrossLine, Zone, Loitering

### 26.4.3 Critères de sortie

- Test coverage core ≥ 70%.
- 100% des règles opposables R01→R16 respectées.
- Bench : 50 caméras 2 Mpx sur RTX A2000 stables 72h.
- Perf : latence WebRTC ≤ 500ms P95, latence IA ≤ 3s P95.
- MTBF simulé ≥ 30 jours (chaos testing).
- Migration test réussie depuis v2.22.0 → v3.0.

### 26.4.4 Plan de repli

Si le calendrier glisse :
- Priorité 1 (must-have) : Plugin Manager + SDK Python + 6 plugins officiels.
- Priorité 2 (peut être v3.0.1) : Mode Installateur (peut sortir en beta).
- Priorité 3 (peut être v3.0.2) : Diagnostics avancés (règles supplémentaires post-launch).

---

## 26.5 v3.1 « Écosystème » (~3 mois, cible Q4 2026)

**Thèse** : le Marketplace propulse la communauté à ≥ 30 plugins publiés.

### 26.5.1 Périmètre

- ✅ **Marketplace en ligne** (`plugins.mg-vms.io`) :
  - Frontend web + API + CDN.
  - Processus publication + review.
  - 5 badges (Officiel/Verified/Community/Beta/Retired).
- ✅ **SDK JavaScript / TypeScript** (`@mgvms/plugin-sdk`, `@mgvms/client`).
- ✅ **Webhooks sortants** (chapitre 5 §5.5).
- ✅ **Plugins tiers stratégiques** :
  - `plate-recognizer-cloud` (cloud ANPR haute précision)
  - `paddle-ocr` (OCR local alternative)
  - `openalpr` (moteur ANPR historique)
  - `face-recognition-insightface`
  - `home-assistant-integration`
  - `mqtt-integration`
  - `grafana-datasource`
  - `nodered-nodes`
  - `s3-storage`
  - `azure-storage`
  - `auth-ldap`
  - `auth-oidc-google`
  - `auth-oidc-keycloak`
- ✅ **Plugin Parking** (chapitre 13) — module métier majeur.
- ✅ **Plugin Automation** (chapitre 15) — moteur Node-RED-like.
- ✅ **Rapports PDF** (chapitre 21) — export planifiés.

### 26.5.2 Critères de sortie

- Marketplace : 20+ plugins Verified/Officiel disponibles au lancement.
- Doc développeur : tutoriels + templates + FAQ.
- 3 événements « MG-VMS Developer Days » (formation dev tiers) organisés.
- 100 intégrateurs formés certifiés.

---

## 26.6 v3.2 « Multi-langages » (~4 mois, cible Q1 2027)

**Thèse** : les plugins ne sont plus l'apanage de Python.

- ✅ **Sandbox Docker container** pour plugins tiers non-vérifiés (ADR-17).
- ✅ **SDK Go** — plugins hautes performances.
- ✅ **SDK Rust** — idem, cible IoT industriel.
- ✅ **SDK C#** — bridge écosystème Windows (migration Milestone/Genetec).
- ✅ **Plugins WASM** (Rust/AssemblyScript compilés).
- ✅ **Signature payante Verified** — badge premium avec support.

---

## 26.7 v3.5 « Multi-site » (~6 mois, cible Q3 2027)

**Thèse** : fédération multi-site pour grands comptes industriels (Karim, chapitre 3).

- ✅ **Fédération** master + noeuds.
- ✅ **Dashboards consolidés** cross-site.
- ✅ **RBAC fédéré** LDAP/OIDC unifié.
- ✅ **Trafic vidéo local** (aucun flux caméra WAN).
- ✅ **Cluster HA** MongoDB replica set (optionnel).
- ✅ **Plugins premium payants** (revenue share Marketplace).

---

## 26.8 v4.0 « Référence marché » (2028+)

**Thèse** : MG-VMS est un standard francophone open-source.

- ✅ **Version SaaS optionnelle** (hébergement MG-VMS pour intégrateurs).
- ✅ **Certifications** (formations certifiantes reconnues profession sécurité).
- ✅ **Intégrations natives ERP/SCADA** (SAP, Siemens, Schneider).
- ✅ **Communauté i18n** (10+ langues traduites).
- ✅ **Certifications légales** (CNPP, APSAD si applicable).

---

## 26.9 Backlog non-planifié

Idées valides mais sans allocation temporelle actuelle :

- **AI edge boxes** — MG-VMS embarqué sur boîtiers dédiés (Coral, Jetson Nano) avec version light.
- **VR / réalité augmentée** — casque pour opérateurs, superposition alertes.
- **Analyse prédictive** — ML sur historique événements pour prévoir incidents (occupation parking, flux clients).
- **Blockchain audit** — pour cas légaux nécessitant preuve d'intégrité vidéo.
- **Analyse comportementale** — détection de mouvements suspects (fall, agression).

Ces idées seront évaluées post-v4.0 selon retours communauté et priorités marché.

---

## 26.10 Écarts v2.22.0 → cible v3.0 (synthèse)

Rappel des chantiers majeurs du core :

| Chantier | Ampleur | Chapitre |
|---|---|---|
| Plugin Manager + SDK | 🔴 Majeur | 11 |
| Modularisation `routes/` (ADR-01) | 🟠 Moyen | 4 |
| Chiffrement Fernet secrets (R05) | 🟠 Moyen | 22 |
| URL versioning `/api/v1` | 🟢 Petit | 5 |
| Réponses erreurs uniformisées | 🟢 Petit | 5 |
| Mode Installateur (wizard) | 🔴 Majeur | 6 |
| Diagnostics moteur règles + 100 rules | 🟠 Moyen | 20 |
| RBAC hiérarchique + sites | 🟠 Moyen | 22 |
| WebSocket canaux + filtres | 🟠 Moyen | 5 |
| MQTT publish | 🟠 Moyen | 5 |
| Refactor `ai_engine` en plugins | 🟠 Moyen | 11 §11.10 |
| Refactor `notifications` en plugins | 🟢 Petit | 11 §11.10 |
| Audit log complet | 🟢 Petit | 22 |
| 2FA TOTP | 🟢 Petit | 22 |

Total estimé : ~ 6-9 mois de travail équipe 3-4 devs.

---

## 26.11 Grille de priorités (arbitre)

En cas de conflit de calendrier, l'ordre de sacrifice est :

1. **Élégance code** — refacto pour beauté, décalé.
2. **Bench absolu** — chiffres targetés, on relâche si le produit marche.
3. **Fonctionnalités périphériques** — plugins non-officiels, différables.
4. **Documentation** — comblable post-launch.
5. **Tests d'acceptation** — jamais sacrifiés.
6. **Stabilité core** — jamais sacrifiée.
7. **Sécurité** — jamais sacrifiée.

Les 3 derniers sont **inviolables**.

---

## 26.12 Métriques d'exécution roadmap

- **Vélocité** — nombre de PR mergées / semaine par dev. Cible : ≥ 3 (petites PR).
- **Cycle time** — du début d'une feature à sa release. Cible : ≤ 3 semaines pour une feature moyenne.
- **Bug reopen rate** — % de bugs marqués fermés qui reviennent. Cible : ≤ 10%.
- **Documentation freshness** — âge médian de la dernière modification par chapitre du cahier. Cible : ≤ 30 jours pour les chapitres actifs.

---

## Annexes

### A. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : 6 versions planifiées (v2.30 → v4.0) · périmètre + critères de sortie + plan de repli · backlog · grille priorités |
