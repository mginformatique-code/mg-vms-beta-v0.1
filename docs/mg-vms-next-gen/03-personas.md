# Chapitre 3 — Personas

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `01-vision-positionnement` · `06-mode-installateur` · `22-administration-rbac`

Ce chapitre définit les **six personas** qui utilisent MG-VMS Next Generation. Chaque persona est un profil-type qui guide les décisions produit : « est-ce que Marc l'intégrateur comprend cette fonction en 5 secondes ? », « est-ce que Sophie l'opératrice trouve l'alerte en 2 clics ? ». Une PR qui améliore l'expérience d'un persona sans pénaliser les autres est prioritaire.

Chaque persona a :
- Un **profil** (âge, formation, environnement de travail).
- Une **journée-type** (routines).
- Ses **frustrations** avec les VMS actuels.
- Ce que MG-VMS lui apporte de **spécifique**.
- Les **modules cœur** qu'il utilise le plus.

---

## 3.1 Marc — l'intégrateur indépendant ⭐ persona principal

**Profil** : 38 ans, patron d'une PME de 8 personnes en région (Bordeaux, Lyon, Nantes ou similaire). Ex-électricien reconverti dans la sécurité électronique. Installe et maintient 300-400 sites par an chez des clients variés : PME industrielles, commerces, écoles, résidences.

**Environnement de travail** : véhicule utilitaire aménagé, tablette Android durcie, quelques outils, câble Ethernet, POE injector. Sur site : escabeau, perceuse, testeur PoE, MG-VMS pré-installé sur mini-PC Beelink ou serveur Dell OptiPlex.

**Formation MG-VMS** : formation certifiante 2 jours (V3.0), lecture des changelogs mensuels, active sur le Discord communautaire.

**Journée-type** :
- 8h30 — arrivée client 1, montage physique 3 caméras (1h30).
- 10h — mise en service via Mode Installateur MG-VMS sur tablette (15 min).
- 10h30 — test réception client, formation opérateur 15 min, signature bon de livraison.
- 11h — départ client 2, répétition.
- 12h30 — déjeuner. Support téléphonique 20 min.
- 14h — client 3 : ajout de 5 caméras sur site existant (10 min via wizard « Ajouter caméra »).
- 16h — client 4 : intervention SAV, diagnostic caméra HS via UI /diagnostics (15 min).
- 17h30 — retour bureau, envoi facturation, sauvegarde configs clients.

**Frustrations avec les VMS actuels** :
- Milestone XProtect Corporate coûte 800€/caméra en licence — plombe la marge des chantiers < 20 caméras.
- Chaque site prend 4h à configurer, Marc facture au forfait mais y passe une journée entière.
- Quand un client demande une intégration domotique (Jeedom, MyFox, Home Assistant), il doit refuser ou bricoler un webhook fragile.
- Les mises à jour Genetec cassent régulièrement des choses. Il évite désormais.

**Ce que MG-VMS lui apporte** :
- **Zéro licence** : marge x2 à x3 sur chaque site.
- **Mode Installateur 15 min** : 4 sites/jour au lieu de 2, sans stress.
- **Plugin Manager** : intègre KNX, MQTT, Home Assistant en cochant 2 cases.
- **Rapport PDF signable** : professionnalise sa livraison client (chapitre 6 §6.5).
- **Communauté active** : questions Discord répondues en < 4h.

**Ses features cœur** :
- Mode Installateur (chapitre 6)
- Assistant d'ajout caméra (chapitre 10)
- Diagnostics avec cause probable en français (chapitre 20)
- Marketplace plugins (chapitre 24)
- Rapport PDF post-installation

**Ce qu'il ne fait jamais** : ouvrir un terminal SSH sur le serveur. Toute action = UI web. Il refuse tout produit qui exige de « modifier un fichier config.yaml ».

**Métrique de succès pour Marc** : peut passer de 2 à 4 sites/jour dans le mois qui suit la formation MG-VMS.

---

## 3.2 Sophie — l'opératrice PC sécurité

**Profil** : 32 ans, opératrice PC sécurité 24/7 dans un centre de télésurveillance mutualisé. Gère 400 caméras réparties sur 30 sites clients (industriels, hôtels, centres commerciaux). Rotation 12h/nuit sur 4 postes en parallèle.

**Environnement de travail** : mur vidéo 6 écrans 4K, deux stations avec double écran QHD, téléphone dédié, sirène d'alerte, casque audio. Interface MG-VMS en plein écran, jamais fermée.

**Formation MG-VMS** : formation 4h à l'embauche + brief mensuel sur nouvelles fonctions.

**Journée-type (nuit 22h→6h)** :
- 22h — prise de poste, brief nuit précédente, vérification des « voyants rouges » du dashboard.
- 22h-2h — surveillance passive du mur vidéo, réception d'alertes ponctuelles (LAPI blacklist, franchissement zone).
- Chaque alerte : ouvrir la scène HD, valider ou infirmer, appeler l'intervenant si confirmé, annoter l'événement.
- 2h30 — pause 30 min.
- 3h-6h — surveillance continue, générer le rapport de nuit à 5h55.

**Frustrations avec les VMS actuels** :
- Trop d'alertes fausses (fantôme, ombre, insecte) — perte de confiance, alertes ignorées à la longue.
- Interface Milestone SmartClient trop chargée, elle utilise 15% des fonctions.
- Diagnostic d'une caméra offline → besoin d'appeler la hotline technique interne, qui répond parfois en 45 min.
- Impossible de partager rapidement une preuve vidéo (WhatsApp au responsable client, elle doit filmer son écran avec son téléphone perso).

**Ce que MG-VMS lui apporte** :
- **Alertes intelligentes** — filtres par sévérité, zone temporelle, cooldown par plaque (chapitre 20).
- **Diagnostic instantané** — clic sur voyant rouge → cause probable en français. Elle diagnostique elle-même 80% des cas, appelle la hotline uniquement pour les 20% restants.
- **Export scène 30s HD** — partageable en 1 clic (lien signé + expiration 24h).
- **Interface minimaliste** — dashboard qu'elle configure elle-même (widgets favoris).

**Ses features cœur** :
- Dashboard personnalisable (chapitre 7)
- Mur vidéo (chapitre 8)
- Alertes + accusé réception (chapitre 20)
- Recherche unifiée (chapitre 9) — pour retrouver rapidement un événement récent.
- Snapshot / export 30s HD.

**Ce qu'elle ne fait jamais** : configurer une caméra, ajouter un utilisateur, modifier un scénario IA. Elle a un rôle `opérateur` sans permissions admin (chapitre 22).

**Métrique de succès pour Sophie** : ratio « alertes traitées / alertes générées » ≥ 95% (pas d'alerte ignorée) + temps médian d'ACK d'une alerte critique ≤ 30 s.

---

## 3.3 Karim — l'admin sécurité multi-site

**Profil** : 45 ans, responsable sûreté d'un groupe industriel (12 usines, 450 caméras). DSI décentralisée : chaque usine a son IT local, Karim coordonne.

**Environnement de travail** : bureau, laptop, deux écrans, téléphone dédié. Se connecte à MG-VMS depuis n'importe où (VPN d'entreprise).

**Formation MG-VMS** : formation admin 2 jours + certification annuelle.

**Journée-type** :
- 8h — revue des alertes de la nuit sur les 12 sites, priorisation.
- 9h30 — call hebdomadaire avec responsables site.
- 10h30-12h — audit d'un site : consultation des journaux ANPR, vérification des zones armées, revue des enregistrements incidents.
- 14h-16h — configuration : ajout d'un nouveau site, création de rôles pour une nouvelle recrue, mise à jour des plugins IA (test dans un site pilote avant déploiement).
- 16h30 — rapport hebdomadaire à la direction (KPI incidents, taux d'occupation parkings, alertes critiques).

**Frustrations avec les VMS actuels** :
- Chaque site a son propre VMS Milestone → 12 interfaces différentes, comptes séparés, aucun consolidé.
- Impossible de comparer les KPI entre sites (« quel site a le plus d'intrusions périmétriques ce trimestre ? »).
- Mises à jour Milestone : coordination complexe entre les 12 IT locaux, souvent report de plusieurs mois.

**Ce que MG-VMS lui apporte (v3.5+ multi-site)** :
- **Fédération** — un compte admin fédéré sur les 12 instances (via LDAP unifié, plugin auth v3.0).
- **Dashboard consolidé** — KPI cross-site en 1 seule vue (chapitre 7).
- **Roll-out plugin uniformisé** — pousser une màj plugin sur les 12 sites depuis une console centrale.
- **Audit log RGPD** — journal d'accès, exports, consultation vidéo — imprimable pour conformité (R09).

**Ses features cœur** :
- Administration RBAC multi-site (chapitre 22)
- Rapports (chapitre 21)
- Diagnostics fédérés
- Marketplace (validation des plugins avant déploiement uniforme)
- Automation cross-site (chapitre 15)

**Ses préoccupations spéciales** : RGPD, souveraineté des données, conservation des enregistrements (rétention légale par pays), séparation stricte des rôles.

**Métrique de succès pour Karim** : temps médian pour identifier un incident cross-site ≤ 5 min. Nombre d'audit RGPD réussi = 100%.

---

## 3.4 Éric — le développeur intégrateur

**Profil** : 29 ans, développeur Python/JS en freelance. Spécialisé automatisation industrielle et intégrations IoT. Consulté par intégrateurs (comme Marc) pour développer des besoins spécifiques.

**Environnement de travail** : télétravail total, laptop Linux, écran ultra-wide, licences dev. Contribue à plusieurs projets open-source, actif sur GitHub.

**Formation MG-VMS** : autoformation via docs + SDK Python, contribution communautaire.

**Journée-type** :
- 9h — check GitHub notifications, review PR sur ses plugins.
- 10h-12h — développement d'un plugin custom pour un client : « détecter les palettes non-emballées à la sortie de l'atelier peinture ». Il implémente une interface `FrameAnalyzer` en Python + entraine un YOLO custom.
- 14h-17h — tests sur son instance MG-VMS locale + push sur Marketplace en version beta.
- 17h-18h — support de ses plugins (2 clients l'ont installé, feedbacks).

**Frustrations avec les VMS actuels** :
- Milestone SDK C# fermé, cher, complexe. Une semaine pour un « Hello World ».
- Frigate — extensible mais nécessite de forker le projet et de rebuilder à chaque màj.
- Home Assistant intégration VMS : intégrations existantes sont médiocres, il doit tout coder à la main.

**Ce que MG-VMS lui apporte** :
- **SDK Python idiomatic** — un plugin YOLO fonctionne en 50 lignes (chapitre 11 §11.2.3).
- **Marketplace** — il publie son plugin, 500 utilisateurs le testent en 3 mois, il gagne en réputation.
- **Type hints complets** — développement rapide dans son IDE (autocomplete, type checking).
- **CI/CD templates** — `mgvms-cli plugin init` génère un projet prêt à l'emploi avec tests.

**Ses features cœur** :
- SDK Python + docs
- Marketplace publication (chapitre 24)
- Système d'événements + bus interne
- API REST + WebSocket (chapitre 5)
- Namespace DB isolé par plugin (ADR-19)

**Métrique de succès pour Éric** : temps « premier plugin publié » ≤ 1 semaine. Peut en vivre partiellement (revenus support / plugins payants v3.5+).

---

## 3.5 Laëtitia — l'artisan-électricien

**Profil** : 51 ans, électricien à son compte. Ne fait pas de sécurité électronique à plein temps mais accepte de poser un « petit système caméras » quand un client résidentiel/petit commerçant le demande (5-10 fois par an).

**Environnement de travail** : atelier chez elle, camionnette. Pas de formation sécurité électronique. Anglais faible.

**Formation MG-VMS** : aucune. Vidéos YouTube en français, doc utilisateur MG-VMS (traduction FR native).

**Journée-type** :
- Elle pose 4-8 caméras chez un client (résidence, petit commerce).
- MG-VMS pré-installé sur mini-PC Beelink acheté 250€.
- Elle suit le mode Installateur, coche les défauts, en 30 min le système marche.

**Frustrations avec les VMS actuels** :
- Milestone / Genetec incompréhensibles pour elle. Elle envoie ses clients à un intégrateur spécialisé, perd la marge.
- Reolink NVR fonctionne mais limité, pas de vraie IA.
- Synology : configuration disque incompréhensible pour ses clients.

**Ce que MG-VMS lui apporte** :
- **Mode Installateur en français** — elle suit les instructions à l'écran, pas besoin de comprendre le jargon technique.
- **Défauts sains** — elle valide tout sans réfléchir, ça marche.
- **Diagnostics visuels** — quand elle revient pour SAV 6 mois plus tard, un voyant rouge lui dit exactement quoi faire.

**Ses features cœur** :
- Mode Installateur (défauts partout)
- Diagnostics cause probable en français
- Rapport PDF de fin d'installation (elle l'imprime pour son client)

**Ce qu'elle ne fait jamais** : configuration avancée, plugins tiers, automatisation. Elle utilise MG-VMS comme un produit fini, pas comme une plateforme.

**Métrique de succès pour Laëtitia** : elle peut vendre + poser un système MG-VMS sans formation préalable, en gardant 100% de la marge (au lieu de sous-traiter à 50%).

---

## 3.6 Nicolas — l'utilisateur autonome / homelabber

**Profil** : 34 ans, ingénieur cybersécurité en salariat. Passionné de domotique et self-hosting. Chez lui : 6 caméras (portail, cour, garage, entrée), NVR maison sur Intel NUC. Actif sur r/homelab, r/selfhosted, Discord communautaires.

**Environnement de travail** : PC gaming maison, homelab dans un placard sous les escaliers, VLAN dédié IoT, Home Assistant central.

**Formation MG-VMS** : autodidacte, forums, GitHub issues.

**Journée-type (usage MG-VMS)** :
- Faible sollicitation quotidienne, MG-VMS tourne en fond.
- Vérifie parfois les enregistrements de la nuit.
- Reçoit des notifications Telegram (livreur détecté, voiture inconnue devant portail).
- Bricole régulièrement : nouveau plugin à tester, config Home Assistant à ajuster, dashboard Grafana à peaufiner.

**Frustrations avec les VMS actuels** :
- Frigate — bien mais monolithique, une màj peut casser toute son intégration Home Assistant.
- Shinobi — interface d'un autre âge.
- BlueIris — Windows only, non-libre.

**Ce que MG-VMS lui apporte** :
- **Écosystème plugin** — il assemble sa stack idéale (yolo + fast-alpr + face-recognition-insightface + Home Assistant + Telegram + Grafana).
- **Auto-hébergé, souverain, gratuit** — aucun cloud, aucune donnée qui sort.
- **Communauté active** — il contribue lui-même des plugins de niche (« reconnaissance des chats du quartier »).

**Ses features cœur** :
- Plugin Manager
- Marketplace communautaire
- Intégration Home Assistant + MQTT
- Docs techniques
- API + SDK Python (il code lui-même)

**Métrique de succès pour Nicolas** : sa contribution GitHub (issues, PR, plugins publiés) — c'est aussi notre indicateur de santé communautaire.

---

## 3.7 Cartographie décisions produit ↔ personas

Chaque décision produit peut se relire à travers ces 6 personas. Exemple concret :

| Décision | Marc | Sophie | Karim | Éric | Laëtitia | Nicolas |
|---|---|---|---|---|---|---|
| Mode Installateur (chapitre 6) | ⭐⭐⭐ Vital | ⚪ | ⭐ | ⚪ | ⭐⭐⭐ Vital | ⭐ |
| Multi-ANPR (§11.6.1) | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐ | ⚪ | ⭐⭐ |
| Diagnostics R02 | ⭐⭐ | ⭐⭐⭐ Vital | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐ |
| SDK Python | ⚪ | ⚪ | ⭐ | ⭐⭐⭐ Vital | ⚪ | ⭐⭐ |
| Marketplace | ⭐⭐ | ⚪ | ⭐⭐ | ⭐⭐⭐ Vital | ⚪ | ⭐⭐⭐ Vital |
| Multi-site RBAC (v3.5) | ⭐ | ⚪ | ⭐⭐⭐ Vital | ⚪ | ⚪ | ⚪ |
| Rapport PDF post-install | ⭐⭐⭐ Vital | ⚪ | ⭐ | ⚪ | ⭐⭐ | ⚪ |
| Traduction FR native | ⭐⭐ | ⭐⭐⭐ Vital | ⭐ | ⚪ | ⭐⭐⭐ Vital | ⭐ |

**Règle d'arbitrage** : une feature qui n'a **aucune** étoile pour aucun persona ne doit **pas** être développée. Chaque feature du roadmap doit justifier son existence par au moins 1 persona ⭐⭐ ou 2 persona ⭐.

---

## Annexes

### A. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : 6 personas · cartographie décisions · règle d'arbitrage |
