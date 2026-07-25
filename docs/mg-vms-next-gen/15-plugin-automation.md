# Chapitre 15 — Plugin Automation

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `11-plateforme-plugins` · `20-diagnostics-intelligents`

Le plugin `automation` est le moteur d'automatisation du VMS — équivalent Node-RED intégré natif. Il permet à l'utilisateur de créer des règles **SI (déclencheur) ET/OU (conditions) ALORS (actions)** sans écrire de code.

---

## 15.1 Vision

Un opérateur ou admin doit pouvoir créer une automatisation en < 2 minutes :

*« Si une plaque de la liste noire est détectée à l'entrée principale entre 18h et 6h, alors envoyer un SMS à l'agent d'astreinte et sauvegarder un extrait vidéo 30 s. »*

L'objectif est d'ouvrir la logique VMS à un public non-développeur, tout en restant assez puissant pour construire des scénarios complexes multi-caméras.

---

## 15.2 Modèle conceptuel

Une **règle d'automatisation** est composée de :

- **Trigger** — événement qui déclenche l'évaluation (1 seul par règle).
- **Conditions** — filtres qui doivent être satisfaits (ET / OU, 0 à N).
- **Actions** — actions à exécuter en séquence ou parallèle (1 à N).

```
┌─────────────────────────────────────────────────────────┐
│  Trigger : Plaque détectée                               │
│  ────────────────────────────────                        │
│                                                          │
│  Conditions (ET) :                                       │
│    • Caméra = "Entrée principale"                        │
│    • Plaque appartient à liste noire                     │
│    • Heure ∈ [18:00, 06:00]                               │
│                                                          │
│  Actions (parallèle) :                                   │
│    → Envoyer SMS à "+33612345678" : "🚨 Blacklist entrée"│
│    → Sauvegarder extrait 30s HD dans pool "Preuves"      │
│    → Publier MQTT "mgvms/site_a/security_breach"         │
│    → Ouvrir relais Zigbee "sirène.entrée"                │
│                                                          │
│  Cooldown : 5 min (même plaque non redéclenchée)         │
└─────────────────────────────────────────────────────────┘
```

---

## 15.3 Triggers (déclencheurs)

Fournis par le core ou les plugins (`TriggerProvider`).

### 15.3.1 Fournis par le core

- `camera.online`, `camera.offline`
- `alert.created`, `alert.acknowledged`
- `system.gpu_saturated`, `system.storage_full`
- `user.login`, `user.login_failed`

### 15.3.2 Fournis par plugins (exemples)

| Trigger | Plugin |
|---|---|
| `event.detected` (YOLO) | `yolo-detection` |
| `plate.detected`, `plate.blacklist`, `plate.whitelist` | `fast-alpr`, `openalpr`, etc. |
| `face.recognized`, `face.unknown` | `face-recognition-*` |
| `smoke.detected` | `smoke-detection` |
| `fire.detected` | `fire-detection` |
| `parking.occupation_threshold` | `parking-manager` |
| `mqtt.message` | `mqtt-integration` |
| `webhook.received` | `webhook-inbound` |
| `schedule.time_reached` | Core (calendrier) |
| `gpio.pin_change` | `gpio-raspberry` |

Chaque trigger a un **schéma de données** documenté (utilisable dans conditions et actions).

---

## 15.4 Conditions

Filtres booléens ET/OU/NON sur les données du trigger + contexte système.

### 15.4.1 Opérateurs

- Comparaison : `=`, `≠`, `<`, `≤`, `>`, `≥`, `in`, `matches` (regex).
- Ensembles : `contains`, `intersect`.
- Temporel : `time_between`, `day_of_week_in`, `date_between`.
- Système : `camera_online(id)`, `plugin_healthy(name)`.

### 15.4.2 Variables disponibles

Champs du trigger (ex. `event.camera_id`, `event.confidence`) + variables globales :
- `now` — datetime courant.
- `site.id`, `site.timezone`.
- `system.gpu_util`, `system.cpu_util`.

### 15.4.3 Groupes logiques

Les conditions peuvent être regroupées avec ET/OU et parenthèses via UI drag&drop.

---

## 15.5 Actions

Fournies par le core ou par plugins (`ActionProvider`).

### 15.5.1 Fournies par le core

- **Notification** : email, popup navigateur, notification desktop.
- **Sauvegarde vidéo** : extrait N sec dans un pool.
- **Snapshot** : capture instantanée.
- **PTZ** : `move_to_preset(preset_id)`, `move(direction, speed)`.
- **Enregistrement** : start/stop sur caméra spécifique.
- **Utilisateur** : bloquer un user, révoquer sessions.
- **Alerte manuelle** : créer une alerte custom.

### 15.5.2 Fournies par plugins

| Action | Plugin |
|---|---|
| Envoi SMS | `twilio-sms` |
| Post Discord | `discord-notifier` |
| Post Telegram | `telegram-notifier` |
| Envoi email SMTP | `smtp-notifier` |
| Publish MQTT | `mqtt-integration` |
| Appel Webhook | `webhook-outbound` |
| Actionner relais Zigbee | `zigbee-integration` |
| Actionner relais KNX | `knx-integration` |
| Appel Home Assistant service | `home-assistant-integration` |
| Synthèse vocale (TTS) | `tts-notifier` |

Chaque action a un **schéma de paramètres** (JSON Schema) — auto-génère le formulaire de config.

---

## 15.6 Interface utilisateur

### 15.6.1 Éditeur visuel

Style Node-RED simplifié — canvas où l'utilisateur pose des « nodes » :

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Trigger    │──▶│  Conditions │──▶│  Actions    │
│  Plaque     │   │  Blacklist  │   │  → SMS      │
│  détectée   │   │  Camera=X   │   │  → Video    │
│             │   │  Heure nuit │   │  → MQTT     │
└─────────────┘   └─────────────┘   └─────────────┘
```

Chaque node ouvre un panneau latéral de config.

### 15.6.2 Mode « Simple » vs « Avancé »

- **Simple** : wizard 3 étapes (Trigger → Conditions → Actions) — recommandé pour Sophie / Karim.
- **Avancé** : canvas plein écran avec branches conditionnelles, boucles, variables — cible Éric / Nicolas.

### 15.6.3 Templates prêts à l'emploi

Bibliothèque de scénarios courants :
- « Alerte plaque blacklist »
- « Notification personne détectée nuit »
- « Sauvegarde intrusion périmètre »
- « Contrôle accès portail via LAPI »
- « Comptage véhicules parking → MQTT »

Import 1 clic + personnalisation.

### 15.6.4 Test / debug

- Bouton **[Tester avec données factices]** — simule le trigger, exécute les actions en mode dry-run.
- Bouton **[Historique exécutions]** — liste des N derniers déclenchements avec résultat par action.
- Logs par règle stockés dans `db.plugin_data.automation.executions` (TTL 30 j).

---

## 15.7 Sécurité & bonnes pratiques

- Chaque règle est associée à un user créateur (audit R09).
- Une action `admin.*` (bloquer user, révoquer session) nécessite que le créateur soit admin.
- Les actions PTZ / relais physiques (`relay.actuate`) sont **auditées systématiquement**.
- Cooldown obligatoire pour éviter les tempêtes (défaut 60 s).
- Rate limit global : max 100 exécutions/minute par site.
- Kill switch : bouton **[Désactiver toutes les automatisations]** en cas de dysfonctionnement.

---

## 15.8 Cas d'usage réels

### Cas 1 — Site industriel

*« Si smoke_detected sur caméra "atelier peinture" ET horaire nuit ET production_active (via MQTT) alors sirène + email direction + PTZ preset "zoom_atelier" + sauvegarde 60s + alerte critique »*

### Cas 2 — Résidentiel

*« Si personne_detectée sur "portail" ET horaire nuit ET user_absent (Home Assistant) alors notification Telegram avec photo + sauvegarde 20s + allumage lumière porche (Zigbee) »*

### Cas 3 — Parking

*« Si occupation parking > 90% alors publish MQTT "parking/full" + notification Slack manager + display "Complet" sur écran extérieur (Home Assistant) »*

### Cas 4 — Multi-caméras

*« Si personne détectée sur "entrée" puis personne détectée sur "couloir" en moins de 30s alors alerte "flux entrant" + comptage++ »*

---

## 15.9 Tests d'acceptation

- **TA-15.1** — Création règle simple : trigger + 1 condition + 1 action. Test dry-run → exécution simulée réussie.
- **TA-15.2** — Cooldown respecté : même trigger en < cooldown → règle non déclenchée à nouveau.
- **TA-15.3** — Rate limit : > 100 exécutions/minute → excès mis en queue, notif admin.
- **TA-15.4** — Kill switch : désactivation globale coupe toutes les règles en < 5s.
- **TA-15.5** — Historique : chaque exécution enregistrée avec success/failure par action.

---

## Annexes

### A. Historique

| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale |
