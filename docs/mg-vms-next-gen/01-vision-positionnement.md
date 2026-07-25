# Chapitre 1 — Vision & positionnement

> **Version** : v1.0 · **Date** : 2026-07-24 · **Statut** : brouillon en cours de validation
> **Auteur** : équipe MG-VMS · **Chapitres liés** : `02-philosophie-principes` · `11-plateforme-plugins` · `26-roadmap`

Ce chapitre ouvre le cahier des charges. Il définit **qui est MG-VMS Next Generation, pour qui, contre quoi, et pourquoi maintenant**. Il est le socle argumentaire de toutes les décisions produits ultérieures.

---

## 1.1 En une phrase

> **MG-VMS Next Generation est la première plateforme open-source professionnelle de vidéosurveillance à architecture 100% plugins — un noyau minimal robuste + un écosystème extensible — qui allie la stabilité de Milestone, la modularité de Home Assistant et l'ouverture de Frigate.**

---

## 1.2 Le marché aujourd'hui

Le marché du VMS professionnel se divise en trois catégories, chacune avec ses limites structurelles :

### 1.2.1 Les monolithes propriétaires (Milestone, Genetec, Avigilon, Digifort)

- **Force** — matures, fonctionnels, écosystème caméra vaste, support commercial.
- **Faiblesses** — coût de licence élevé (500-2000 € par caméra), enfermement propriétaire, installation lourde (4-8 h par site), moteurs IA verrouillés, protocoles fermés, extensibilité limitée.
- **Public** — grands comptes, sites critiques (aéroports, prisons, casinos).

### 1.2.2 Les VMS grand public / SOHO (Synology Surveillance Station, Reolink NVR, Ubiquiti UniFi Video)

- **Force** — prix accessible ou inclus dans le matériel, installation rapide, UI moderne.
- **Faiblesses** — fonctionnalités limitées (peu ou pas d'IA sérieuse), plafond de scalabilité (~ 8-32 caméras), aucune ouverture développeur, dépendance à un écosystème hardware.
- **Public** — particuliers, TPE, petits commerces.

### 1.2.3 Les initiatives open-source (Frigate NVR, ZoneMinder, Shinobi, Bluecherry)

- **Force** — gratuits, communautés actives, personnalisables.
- **Faiblesses** — souvent monolithiques (Frigate ajoute une architecture plugin partielle en 2024-2025), stabilité aléatoire, UI moins polie, courbe d'apprentissage abrupte, peu ou pas de support pro.
- **Public** — passionnés, homelabbers, quelques intégrateurs.

**Le trou dans le marché** : personne ne propose une **plateforme open-source professionnelle** à architecture réellement extensible, qui offre à la fois la stabilité d'un Milestone, la modularité d'un Home Assistant et un modèle économique viable pour les intégrateurs.

---

## 1.3 La proposition MG-VMS NG

### 1.3.1 Trois piliers de différenciation

**1. Architecture plateforme 100% plugin (chapitre 11).**
MG-VMS n'est pas *un logiciel qui accepte des plugins*, c'est *une plateforme dont tout est plugin sauf le noyau*. Cette différence n'est pas cosmétique : elle change le contrat produit avec l'écosystème.

**2. Stabilité indus. de niveau Milestone, ouverture de Home Assistant.**
Chaque plugin est isolé (sandbox in-process / sub-process / container selon confiance). Le crash d'un plugin ne fait jamais tomber le VMS. Les mises à jour se font plugin par plugin sans rebooter le core.

**3. Mode Installateur 10-15 min (chapitre 6).**
De zéro à site pleinement opérationnel en moins d'un quart d'heure. Personne d'autre ne propose ça sur le marché professionnel. C'est notre atout terrain irréductible pour les intégrateurs.

### 1.3.2 Ce que MG-VMS NG N'EST PAS

Pour éviter les malentendus :

- **Ce n'est pas Frigate++** — Frigate est un excellent produit de détection embarquée, mais son modèle reste centré sur l'inférence GPU locale. MG-VMS embrasse un spectre plus large (multi-ANPR, parking, automatisation, domotique, multi-site).
- **Ce n'est pas un remplaçant plug-and-play de Milestone** — nous ne cherchons pas à cocher toutes les cases enterprise (federation multi-site cluster, cartographie 3D avancée, SDK C# legacy). Nous visons le meilleur rapport qualité/prix/liberté.
- **Ce n'est pas un projet mono-caméra domestique** — l'architecture est pensée pour tenir 200 caméras 2Mpx par serveur (§4.12), pas 2 caméras résidentielles (même si ce cas fonctionne).
- **Ce n'est pas une plateforme SaaS** — MG-VMS s'auto-héberge. Aucun composant critique ne dépend d'un cloud externe. Les plugins cloud (Plate Recognizer, Google Vision) sont optionnels et remplaçables.

---

## 1.4 Segments cibles

### 1.4.1 Segment principal — Intégrateurs indépendants

**Profil** : PME de 5-30 personnes, pose 200 à 2000 caméras/an chez des clients variés (industriels, collectivités, résidentiels haut de gamme).

**Pain points** :
- Le coût des licences Milestone/Genetec grignote la marge.
- L'installation prend une journée par site (temps facturé au client, mais fatigue et erreurs).
- Difficulté à intégrer des besoins spécifiques client (protocoles domotique, notifications sur-mesure).

**Value proposition MG-VMS** :
- Zéro licence. Marge accrue.
- Installation en 15 min ⇒ +40% de sites/semaine par technicien.
- Écriture de plugins custom pour clients premium ⇒ valeur ajoutée + revenus récurrents.

### 1.4.2 Segment secondaire — Grands comptes industriels avec besoins spécifiques

**Profil** : sites industriels 50-500 caméras, DSI interne, contraintes légales/RGPD/OT (OT = Operational Technology).

**Pain points** :
- Les VMS propriétaires empêchent l'intégration profonde avec leur SI (ERP, SCADA, GTB).
- Les moteurs IA fournis sont génériques, pas adaptés à leur activité (fumée sur ligne de peinture, PPE sur atelier).
- Coûts de licence sur grand parc explosifs.

**Value proposition MG-VMS** :
- Open source auditable, souveraineté logicielle.
- Plugins custom internes (leur DSI écrit ce dont elle a besoin).
- Coût prédictible (support/maintenance uniquement).

### 1.4.3 Segment tertiaire — Passionnés / homelab

**Profil** : particuliers techniques, chaînes YouTube tech, admins réseau à la maison.

**Pain points** :
- Frigate est bien mais monolithique et parfois instable.
- Home Assistant a une intégration VMS pauvre.
- Synology Surveillance Station est cher (licences par caméra).

**Value proposition MG-VMS** :
- Open source et gratuit.
- Plugins Home Assistant natifs (MQTT + intégration bidirectionnelle).
- UI moderne, mobile-friendly.

**Note** : ce segment n'est **pas** notre priorité produit mais il est stratégique — il produit l'écosystème (plugins communautaires, contenu YouTube, avis, retours qualité).

### 1.4.4 Ce que nous ne visons pas

- **Le segment enterprise ultra-critique** (aéroports internationaux, prisons de haute sécurité). Nous n'aurons ni la certification, ni la garantie, ni le support 24/7 attendu à ce niveau.
- **Le segment ultra-résidentiel one-camera** (particulier avec 1 caméra Xiaomi). Trop lourd pour ce cas, la concurrence Reolink/eufy est mieux adaptée.

---

## 1.5 Analyse concurrentielle synthétique

| Critère | Milestone | Genetec | Nx Witness | Frigate | Synology | **MG-VMS NG** |
|---|---|---|---|---|---|---|
| Open source | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ |
| Coût licence par caméra | €€€ | €€€ | €€ | Gratuit | €€ (matériel) | **Gratuit** |
| Architecture plugins vraie | ⚠ SDK complexe | ⚠ SDK propriétaire | ❌ | ⚠ v0.14+ partiel | ❌ | ✅ **100% plugin** |
| Mode Installateur < 20 min | ❌ 4-8h | ❌ 6-12h | ⚠ 2-4h | ⚠ 1-2h | ⚠ 30-60 min | ✅ **10-15 min** |
| Multi-ANPR (moteurs simultanés) | ❌ | ❌ | ❌ | ⚠ | ❌ | ✅ **Natif** |
| Diagnostics « voyant rouge orphelin » | ❌ | ⚠ | ❌ | ❌ | ❌ | ✅ **R02 formalisé** |
| Stabilité 24/7 industrielle | ✅ | ✅ | ✅ | ⚠ | ✅ | ✅ **Cible v3.0** |
| Modules IA (Face, PPE, Smoke, Fire) | ✅ | ✅ | ⚠ | ⚠ | ❌ | ✅ **Marketplace** |
| Intégrations domotique (HA, MQTT) | ⚠ payantes | ⚠ | ❌ | ✅ MQTT | ⚠ limité | ✅ **Plugins natifs** |
| Marketplace développeur | ❌ | ❌ | ❌ | ⚠ communauté | ❌ | ✅ **v3.1** |
| SDK multi-langages | ⚠ C# | ⚠ | ⚠ | Python | ❌ | ✅ **Py/JS/Go/Rust** |
| Auto-hébergement | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 1.6 Modèle économique

### 1.6.1 Le noyau reste **libre et gratuit**

MG-VMS Core + les 6 plugins officiels bundlés (yolo-detection, fast-alpr, notifications SMTP/Discord/Telegram, zone-analytics) sont sous licence **Apache 2.0**. Toujours. Sans exception.

### 1.6.2 Sources de revenus (pour financer la structure MG-VMS)

- **Support & maintenance** — contrats annuels pour intégrateurs et grands comptes (SLA, patch priorisés).
- **Formations & certifications** — parcours « MG-VMS Installateur Certifié » (2 jours), « MG-VMS Développeur Plugins » (3 jours).
- **Plugins premium officiels** — quelques plugins avancés payants (ex. moteur ANPR haute précision entraîné maison, module analytics BI, connecteur ERP SAP). Marginal, jamais bloquant.
- **Marketplace commission** — v3.5+, revenue share sur plugins tiers payants (30/70 dev/MG-VMS).
- **Cloud managed (optionnel)** — v4.0+, offre hébergée pour intégrateurs qui ne veulent pas gérer l'infra client.

### 1.6.3 Ce que nous ne ferons **jamais**

- Rendre le noyau propriétaire ou fermé.
- Introduire une clé de licence obligatoire.
- Restreindre des fonctions core derrière un paywall.
- Vendre les données clients.

---

## 1.7 Timing — pourquoi maintenant

### 1.7.1 Convergence technologique

- **go2rtc v1.9+** — moteur RTSP/WebRTC production-ready et sans concurrent open-source à ce niveau (2024-2026).
- **NVDEC/NVENC** — accélération vidéo mainstream sur GPU consumer (RTX A2000+, ~800€), plus réservée aux serveurs pro.
- **YOLOv11 + ultralytics** — inférence IA de qualité pro accessible en 3 lignes de Python.
- **fast-alpr / PaddleOCR** — ANPR CPU-only viable, plus besoin de GPU dédié pour la plaque.
- **React 18 + Vite** — SPA moderne, performante, dev-friendly.
- **FastAPI + Motor** — backend async Python industriel.

Ces briques ont mûri en 2023-2025. Nous les fédérons.

### 1.7.2 Convergence marché

- **RGPD + souveraineté** — les collectivités et industriels français/européens sont **contraints** de choisir des solutions auditables. Nous cochons la case.
- **Fin de vie de plusieurs solutions moyennes** (Milestone Essential fin de support 2027, produits Bosch VMS descendus). Fenêtre de remplacement.
- **Prix des VMS propriétaires** — augmentations 2023-2025 (Genetec +40% licences) — clients cherchent alternatives.
- **Écosystème Home Assistant** — 500 000+ installations, communauté active, appétit pour des extensions VMS solides.

### 1.7.3 Convergence développeur

- **Open source acceptable en enterprise** — les DSI qui refusaient Linux il y a 20 ans acceptent Kubernetes aujourd'hui. Idem pour l'OSS de sécurité.
- **Culture plugins** — les développeurs sont familiers du paradigme (VS Code, Home Assistant, Grafana, Docker Hub, GitHub Actions marketplace).

---

## 1.8 Vision à 5 ans

**2026 (v3.0)** — Sortie de la plateforme. 20 plugins officiels + verified. Adoption par 100 intégrateurs pilotes.

**2027 (v3.5)** — Marketplace mature avec 200+ plugins. Multi-node cluster pour grands sites. Certifications formation. 1000 intégrateurs. 50 000 caméras déployées cumulées.

**2028 (v4.0)** — MG-VMS devient une référence dans l'écosystème francophone open-source. Version SaaS optionnelle. Intégrations natives avec les principaux ERP/SCADA. 500 000 caméras.

**2029-2030 (v5.0)** — Standard de facto en France pour l'auto-hébergement pro. Communauté internationale (traductions 10+ langues). Écosystème de 1000+ plugins. Ouverture à des marchés adjacents (analyse vidéo trafic urbain, IoT industriel).

---

## 1.9 Risques identifiés

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Concurrence copie l'architecture plugin | Moyenne | Fort | Avance technologique + communauté + Marketplace lock-in doux |
| Bug critique dans le Plugin Manager | Faible | Fort | Test coverage ≥ 80% du Core, ADR-17 sandboxing, R01 non-cascade |
| Adoption lente intégrateurs | Moyenne | Fort | Mode Installateur 15 min = ROI immédiat, formations certifiantes |
| Fragmentation communauté plugins | Faible | Moyen | Marketplace curée, badges Officiel/Verified, review process |
| Modèle éco insuffisant | Moyenne | Moyen | Diversification revenus (support/formations/premium), lean structure |
| Attaque supply chain plugins tiers | Faible | Fort | Signature GPG, review Marketplace, sandbox container par défaut |
| Frigate accélère et devient hégémonique OSS | Moyenne | Fort | Différenciation via multi-ANPR, mode Installateur, Marketplace pro |

---

## 1.10 Notre nord magnétique

Une seule question guide toutes nos décisions :

> **« Un intégrateur qui ouvre MG-VMS pour la première fois doit avoir un site opérationnel en 15 minutes, une plateforme extensible pour ses 20 prochaines années de métier, et une confiance absolue dans la stabilité pendant que sa marge triple. »**

Chaque feature qui rend cette phrase plus vraie est bonne. Chaque feature qui la rend moins vraie est mauvaise, quelle que soit la beauté technique.

---

## Annexes

### A. Références externes

- Milestone XProtect — https://www.milestonesys.com
- Genetec Security Center — https://www.genetec.com
- Frigate NVR — https://github.com/blakeblackshear/frigate
- Home Assistant — https://www.home-assistant.io (référence architecture plugin)
- Grafana — https://grafana.com (référence marketplace plugins)

### B. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : positionnement, 3 segments cibles, tableau concurrentiel, modèle éco, vision 5 ans, 7 risques |
