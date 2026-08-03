# MG-VMS — Vision Produit & Roadmap Technique (vNext)

> **Source de vérité stratégique.** Fixée par le CEO le 25 juillet 2026.
> Toute nouvelle feature/refactor doit être évaluée à travers ce prisme.

## Contexte

MG-VMS n'est plus simplement un logiciel de vidéosurveillance. Le projet
doit évoluer vers **une plateforme professionnelle de supervision vidéo
open source, moderne, modulaire et orientée automatisation**.

L'objectif n'est pas de reproduire Frigate, Blue Iris ou Milestone, mais
de construire une plateforme capable d'accueillir des plugins métier, de
l'intelligence artificielle, des workflows et des intégrations.

Toutes les évolutions doivent conserver cette philosophie.

## Les 4 piliers

1. **Un VMS professionnel** — caméras, enregistrements fiables, WebRTC, PTZ, diagnostics
2. **Une plateforme d'IA** — plugins, tracking, ANPR, détection métier, smart zones
3. **Un moteur d'automatisation** — workflows, MQTT, HTTP, audio, PTZ, relais, scripts, intégrations
4. **Un écosystème ouvert** — marketplace, SDK, API, plugins tiers, monitoring, sécurité

## Philosophie

MG-VMS ne doit pas être seulement un logiciel qui affiche des caméras. Il
doit devenir **une plateforme programmable de supervision vidéo**, capable
de s'adapter à tous les métiers grâce à une architecture modulaire.

---

# Roadmap officielle — 17 priorités

## P1 · Stabilisation ⭐ (BLOQUANT — avant toute nouvelle feature)
Corriger définitivement :
- PTZ WebRTC
- bugs ONVIF
- enregistrements incomplets
- stabilité RTSP
- supervision processus FFmpeg
- watchdog caméras
- reconnexions automatiques
- diagnostics détaillés

**Livrable transverse** : tableau de santé complet (état caméra, FPS, débit, RTSP, WebRTC, CPU, GPU, erreurs FFmpeg, historique coupures).

## P2 · Plugin Manager — cœur de MG-VMS
- Chargement dynamique · Multi-plugins simultanés · Isolation erreurs · Sandbox
- Dépendances · Versionning · Mises à jour indépendantes
- Activation/désactivation sans redémarrage
- Bases d'un futur Store
- Architecture : Core → Plugin Manager → { IA · Notifications · Business · Automation · Intégration }

**Statut Feb 2026 : 60% fait — 49 plugins × 11 catégories, pipeline chaîné actif. Reste sandbox + marketplace + SDK.**

## P3 · Smart Zones (zones intelligentes)
Chaque zone devient un objet capable de :
- **Détecter** : personne / véhicule / animal / objet / mouvement / plaque / visage / arme / feu / fumée
- **Mesurer** : présence / durée / nombre / occupation / entrée / sortie / distance / vitesse
- **Déclencher** :
  - **Plugins** : appeler un plugin (notification, ANPR ciblée, tracking ciblé…)
  - **Actionneurs caméra** : projecteur / IR / éclairage / relais / GPIO / haut-parleur (audio ONVIF) / micro (talk bidirectionnel) / sirène intégrée / PTZ preset
  - **Actionneurs externes** : Home Assistant (services `light.turn_on`, `switch.turn_on`, `notify.*`, `automation.trigger`), Tuya (Cloud API + LAN), MQTT (topic + payload), Zigbee2MQTT, Node-RED, webhooks HTTP, appels API tiers, scripts shell, TTS Google/Azure/OpenAI, appels téléphoniques (Twilio), SMS, emails
- **Chaîner** : une zone peut déclencher une autre zone, un workflow, ou faire des actions séquentielles avec délais (SI → attendre 10s → SI encore présent → escalade)

## P4 · Workflow Engine
Moteur graphique d'automatisation inspiré Home Assistant + Node-RED. Tous les plugins doivent pouvoir être utilisés comme déclencheurs ou actions.
Exemple : `SI Personne entre dans Zone A → attendre 30s → toujours présente → lecture audio → attendre → toujours présente → notification → toujours présente → sirène`

## P5 · Timeline (Reolink-like, en mieux)
Zoom/dézoom, navigation fluide, calendrier, recherche rapide, graduation dynamique. **Timeline IA** avec icônes par type d'événement (🚶 🚗 🐕 🔴 📦 ⚠) + filtrage.

## P6 · Timeline Photos
Miniatures générées automatiquement, cache, recherche rapide, navigation instantanée (au lieu des 10 miniatures actuelles).

## P7 · Recherche intelligente
Par personne, véhicule, plaque, animal, caméra, plugin, zone, date, heure. Préparer l'arrivée future de la reconnaissance faciale **sans l'intégrer immédiatement**.

## P8 · ANPR — refonte cycle Entrée/Présence/Sortie
Éviter 1000 événements pour une voiture stationnée. Nouvelle lecture uniquement si le véhicule quitte réellement la scène puis revient. Utiliser tracking + position + temps + distance.

## P9 · Audio
Talk bidirectionnel, lecture audio, messages vocaux, diffusion. Préparer contrôle des haut-parleurs ONVIF.

## P10 · Contrôle caméra
Éclairage, projecteur, sirène, sorties digitales, GPIO, relais. **Utilisables depuis les Workflows.**

## P11 · Sécurité
HTTPS + Let's Encrypt + certificats personnalisés, déconnexion automatique après inactivité, expiration configurable des sessions, journal d'audit, gestion des appareils, popup MFA obligatoire tant que non configuré, MFA imposable par l'admin.

## P12 · Accélération matérielle multi-vendor
Ne plus être limité à NVIDIA. Support NVIDIA / Intel QuickSync / Intel OpenVINO / AMD / VAAPI / AMF / CPU. Détection auto du meilleur backend.

## P13 · Health Dashboard
Docker, Mongo, GPU, CPU, RAM, stockage, FFmpeg, go2rtc, caméras, plugins, version, licence.

## P14 · Marketplace
Plugins ANPR / Retail / Fire / Smoke / Weapon / PPE / Agriculture / Commerce / Parking / Smart City / Notifications / Home Assistant / MQTT / Node-RED. Chaque plugin : version, auteur, licence, changelog, mise à jour, install en un clic.

## P15 · UX moderne
Inspirations Reolink, UniFi Protect, Immich, Frigate, Proxmox, Home Assistant. **Simple. Fluide. Professionnel. Accessible aux installateurs.**

## P16 · Statistiques anonymes (bStats-like)
Optionnel. JAMAIS d'images/vidéos/plaques/flux/données personnelles. Uniquement version, OS, GPU, CPU, nb caméras, plugins installés, accélération matérielle.

## P17 · Auto-update
Vérifier version MG-VMS + plugins + correctifs. Afficher changelog. Préparer mises à jour en un clic.

## P18 · Base de données — Portabilité & self-hosting (Feb 2026, demande CEO)
Actuellement MG-VMS repose sur MongoDB (couplage fort via `motor` async).
Objectif : permettre à l'utilisateur de **choisir où et comment stocker la BDD** :

**P18.a — Config UI (livré Feb 2026)** ✅
- Endpoints admin `/api/settings/database` (GET/PUT/test/restart)
- UI dans Settings : afficher URI courante (masquée), tester une nouvelle URI, enregistrer dans `.env`, redémarrer le backend depuis l'UI
- Backup automatique de `.env.bak` avant modification
- Cas d'usage : pointer MG-VMS vers un serveur MongoDB dédié externe plus performant

**P18.b — Support multi-moteur (à faire)** ⚪
- Layer d'abstraction : `db.cameras.find()` → adaptateur MongoDB **ou** SQL
- Backends cibles : PostgreSQL (JSONB pour souplesse), MySQL/MariaDB (colonnes classiques)
- Migrations Alembic-like pour évolution schéma
- Test suite parallèle pour chaque backend
- Wizard "Migrer les données" : aspire MongoDB → SQL en un clic
- Config UI : dropdown moteur (mongodb / postgres / mysql / mariadb)

**P18.c — Read-replica SQL (nice-to-have)** ⚪
- Job périodique qui réplique les collections lourdes (events, plates, recordings, alerts) vers un SQL externe pour BI/reporting (Power BI, Grafana, Metabase)
- MongoDB reste la source de vérité
- Config UI : URI SQL cible + fréquence de réplication

---

## Comment interpréter cette roadmap

- **P1 est bloquant** : aucun nouveau développement de feature ne doit démarrer tant que la stabilité core n'est pas garantie.
- **P2 est le cœur** : le Plugin Manager conditionne P3/P4/P8/P14. Il progresse en parallèle de P1.
- **P3–P8** sont les grosses valeurs métier — dans l'ordre.
- **P9–P17** peuvent s'entrelacer selon la traction commerciale.
- **P18** ajouté Feb 2026 : DB portable / self-hosting.

## Ce qui a déjà été fait dans la session Feb 2026

- ✅ **P1 Stabilisation** : PTZ ONVIF réel (8 commandes + presets), UI 8-directions, Recorder Health (continuité 24h), Health Dashboard, FFmpeg Watchdog, modularisation routers.py (3 modules), logo dark/light, badges login réels (vert/rouge only)
- ✅ **P2 Plugin Manager (85%)** : PluginBus, loader dynamique manifest YAML, 49 plugins × 11 catégories, config store, hot reload, install deps, badges état, config dialog, pipeline chaîné Detector→Tracker→Segmenter→PipelineConsumer→EventConsumer wired dans ai_engine, canvas de test, Fernet secrets, Sandbox quarantine auto (5 échecs), Plugin SDK (scaffold + pack .mgpkg), UI regroupée par domaine métier (ANPR/Détection IA/Tracking/Segmentation/Feu/Sûreté/EPI/Comptage/Retail/Parking/Agriculture/Notifications) + barre de synthèse
- ✅ **P18.a Base de données** : Config UI complète (test/save/restart backend)
- Reste P2 : marketplace UI upload `.mgpkg`, isolated DB namespace par plugin

## Ordre d'exécution proposé (revised Feb 2026)

1. **P1 Stabilisation** — ✅ complet
2. **P2 finalisation** — Marketplace UI upload `.mgpkg`
3. **P8 ANPR refonte** — cycle Entrée/Présence/Sortie (haute valeur commerciale)
4. **P3 Smart Zones** — permet aux Workflows d'exister
5. **P4 Workflow Engine** — game-changer produit
6. **P18.b Multi-moteur SQL** — chantier lourd, à planifier après P8/P3
7. **P13 Health Dashboard** — améliorations UI
8. Le reste selon traction
