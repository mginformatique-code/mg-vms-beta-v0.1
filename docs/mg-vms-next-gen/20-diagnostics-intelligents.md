# Chapitre 20 — Diagnostics intelligents

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `02-philosophie-principes` (R02) · `04-architecture-cible` · `11-plateforme-plugins`

Ce chapitre formalise l'application de la règle **R02 « Tout voyant rouge est explicable en 1 clic »** à l'ensemble du produit. Il définit **comment** MG-VMS transforme chaque état négatif du système en explication humaine actionable — c'est l'un des différenciateurs les plus concrets vis-à-vis des concurrents (chapitre 1 §1.5).

---

## 20.1 Le principe fondateur

Un opérateur qui voit un voyant rouge et ne sait pas quoi faire perd confiance dans le système. À long terme, il ignore les alertes rouges (« ah, encore ce truc »). C'est le mode d'échec le plus dangereux d'un VMS.

**MG-VMS applique une règle absolue** : **aucun état négatif dans l'UI n'est opaque**. Chaque badge rouge / warning / erreur est **cliquable** et ouvre :

1. **La cause probable en français** (une phrase courte).
2. **Le détail technique** (pour un technicien).
3. **Les actions recommandées** (boutons cliquables).
4. **La timeline** (quand ça a commencé, historique).
5. **Le lien vers le journal** (pour approfondir).

Un utilisateur non-technicien doit pouvoir résoudre 80% des cas sans support (chapitre 3, Sophie).

---

## 20.2 Anatomie d'un diagnostic

### 20.2.1 Le dialog standard

Chaque clic sur un voyant rouge ouvre un dialog uniforme :

```
┌────────────────────────────────────────────────────────────────────┐
│  🔴  Caméra Parking Nord — Offline                                   │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                      │
│  Cause probable                                                      │
│  ─────────────                                                       │
│  La caméra ne répond plus depuis 3 min 12 s.                         │
│  Dernière erreur : "connection refused" — la caméra est peut-être    │
│  éteinte, débranchée ou son adresse IP a changé.                     │
│                                                                      │
│  Actions recommandées                                                │
│  ─────────────                                                       │
│  [🔁 Retester la connexion maintenant]                                │
│  [⚙  Vérifier la config caméra]                                       │
│  [📋 Voir les logs détaillés]                                         │
│  [📸 Voir la dernière image reçue]                                    │
│                                                                      │
│  Historique 7 jours                                                  │
│  ─────────────                                                       │
│  ✅ Online : 6j 22h 15min (98.9%)                                     │
│  ❌ Offline : 1h 45min                                                │
│  MTBF : 32 jours                                                     │
│                                                                      │
│  Détail technique (dev)                          [▼ afficher]         │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

**Éléments obligatoires** :
- Titre : icône + nom de la ressource + état.
- Cause probable : 1-3 phrases français, ton neutre, actionable.
- 2 à 4 actions recommandées (boutons).
- Historique / stats.
- Détail technique replié par défaut (auditable par dev).

### 20.2.2 Le moteur de causes probables

**`db.diagnostic_rules`** — collection de règles heuristiques mapping (`error_pattern`, `context`) → (`cause`, `actions_recommended`).

Structure d'une règle :
```json
{
  "domain": "camera",
  "trigger": {
    "state": "offline",
    "error_pattern": "connection refused|network unreachable|no route to host"
  },
  "cause_fr": "La caméra ne répond plus depuis {duration}. Dernière erreur : \"{last_error}\" — la caméra est peut-être éteinte, débranchée ou son adresse IP a changé.",
  "cause_technical": "TCP handshake échoue sur {host}:{port}. Réseau inaccessible.",
  "actions": [
    {"label": "Retester la connexion", "endpoint": "POST /cameras/{id}/refresh-stream"},
    {"label": "Vérifier la config caméra", "route": "/cameras/{id}"},
    {"label": "Voir les logs", "route": "/diagnostics/camera/{id}/logs"},
    {"label": "Voir la dernière image", "endpoint": "GET /cameras/{id}/last-snapshot"}
  ],
  "priority": 10,
  "created_at": "..."
}
```

**Algorithme de résolution** :

1. Le composant en erreur (ex. probe caméra) écrit un événement `diagnostic_signal` sur le bus interne avec `{domain, resource_id, state, error_text, context}`.
2. Le service `diagnostics_engine` (dans le core) trie les règles matching par `priority`, prend la première.
3. Le champ `cause_fr` est un template rendu avec les variables du contexte.
4. Le résultat est mis en cache 30 s (une caméra qui plante 30 fois/min ne recalcule pas la cause 30 fois).
5. Exposé via `GET /api/v1/diagnostics/{domain}/{id}/probable-cause`.

**Priorités** : de 100 (règle très spécifique) à 1 (règle générique). Une règle générique de fallback existe pour chaque domaine (`priority=1`, `cause_fr="Une erreur est survenue. Consultez les logs techniques."`).

### 20.2.3 Enrichissement par plugin

Chaque **plugin** peut enregistrer ses propres règles de diagnostic via son manifest :

```yaml
# manifest.yaml d'un plugin YOLO
diagnostic_rules:
  - domain: plugin
    plugin_name: yolo-detection
    trigger:
      state: crashed
      error_pattern: "CUDA out of memory"
    cause_fr: "La mémoire GPU est saturée. Baissez le modèle YOLO (n < s < m) ou réduisez le nombre de caméras qui utilisent ce plugin simultanément."
    actions:
      - {label: "Basculer sur YOLO nano", plugin_config_patch: {"model": "yolo11n.pt"}}
      - {label: "Voir occupation GPU", route: "/system/gpu"}
```

Ces règles sont chargées à l'installation du plugin et supprimées à sa désinstallation.

---

## 20.3 Domaines couverts

Le moteur diagnostic couvre les domaines suivants — chacun avec ses règles dédiées :

### 20.3.1 Caméras (`domain: "camera"`)

Voyants rouges possibles + causes probables :

| État | Cause probable |
|---|---|
| `offline` + `connection refused` | Caméra éteinte, débranchée, IP changée |
| `offline` + `authentication failed` | Mot de passe caméra modifié |
| `offline` + `timeout` | Latence réseau, VLAN saturé |
| `degraded` + `low fps < 5` | Bande passante insuffisante, transcodage forcé |
| `codec_mismatch` | Caméra en H.265 mais backend attend H.264 |
| `resolution_below_min` | Profil ONVIF sélectionné n'expose que 320p |
| `stream_locked` | Un autre client consomme les sessions max (limite Hikvision = 3) |

### 20.3.2 Plugins (`domain: "plugin"`)

| État | Cause probable |
|---|---|
| `crashed` + `ModuleNotFoundError` | Dépendance Python manquante — réinstaller |
| `crashed` + `CUDA out of memory` | VRAM saturée — baisser le modèle |
| `crashed` + `torch not compiled with CUDA` | Rebuild GPU incompatible — voir chapitre 17 |
| `disabled_quota_ram` | Le plugin a dépassé son quota RAM 3 fois — kill auto |
| `signature_invalid` | Plugin non signé, refuse installation |
| `incompatible_core` | Manifest exige `mgvms_core: >=4.0.0` mais on est en 3.0 |

### 20.3.3 Infrastructure (`domain: "system"`)

| État | Cause probable |
|---|---|
| `gpu_absent` | Aucun GPU NVIDIA détecté — voir §17 |
| `gpu_saturated_vram` | VRAM > 90% — baisser modèles IA ou nombre de caméras |
| `mongo_slow` | Requêtes > 1s — vérifier index, taille collections |
| `mongo_unreachable` | MongoDB HS — vérifier docker compose |
| `go2rtc_unreachable` | Container go2rtc HS — restart |
| `storage_almost_full` | Pool > 90% — augmenter rétention ou disque |
| `disk_smart_warning` | Secteurs défectueux — remplacer disque |
| `cpu_overload` | Load average > cores — trop de plugins actifs |

### 20.3.4 Notifications / intégrations

| État | Cause probable |
|---|---|
| `smtp_auth_failed` | Mot de passe email changé ou 2FA activé côté Gmail — utiliser app password |
| `discord_webhook_404` | Webhook Discord supprimé côté serveur — recréer |
| `telegram_bot_blocked` | L'utilisateur a bloqué le bot — relancer /start |
| `mqtt_unreachable` | Broker externe HS — vérifier config |

### 20.3.5 Enregistrements

| État | Cause probable |
|---|---|
| `recording_gap` | Gap dans l'enregistrement — ffmpeg subprocess crashé, restart auto |
| `retention_full` | Impossible d'écrire — pool storage saturé |
| `codec_incompatible` | Format vidéo non supporté par le player |

---

## 20.4 Page /diagnostics

Page centrale qui agrège **tous** les diagnostics du système en une vue.

**Layout** :

```
┌────────────────────────────────────────────────────────────────────┐
│  Diagnostics                                                        │
│  ────────                                                           │
│                                                                     │
│  📊 Santé globale                                                    │
│    ✅ Core : opérationnel · uptime 15 j                              │
│    ✅ 42/45 caméras online                                           │
│    ⚠  3 caméras offline (voir liste)                                 │
│    ✅ 8/8 plugins actifs                                             │
│    ⚠  1 plugin instable (fire-detection — 5 crashes en 1h)          │
│    ✅ GPU : RTX A2000 · VRAM 4.2/6 GB · 62°C                         │
│    ✅ Storage : 3.2 TB libres · SMART OK                              │
│                                                                     │
│  🎯 Problèmes actifs (4)                                             │
│    🔴 Parking Nord — offline depuis 3 min           [Diagnostiquer] │
│    🔴 Entrée B — codec_mismatch                     [Diagnostiquer] │
│    🔴 Réception — auth failed                       [Diagnostiquer] │
│    ⚠  fire-detection — instable                     [Diagnostiquer] │
│                                                                     │
│  📈 Métriques temps-réel                                             │
│    [Graphes CPU/RAM/GPU/Réseau/FPS]                                 │
│                                                                     │
│  🧠 Santé IA (temps réel)                                            │
│    [Section AI Health — voir v2.21.0]                               │
│                                                                     │
│  🔄 Réconciliation DB ↔ go2rtc                                       │
│    [Section streams-sync — voir v2.22.0]                            │
│                                                                     │
│  📋 Journal lifecycle streams                                        │
│    [Timeline dernières transitions]                                 │
│                                                                     │
│  🔍 Chercher un incident                                             │
│    [Recherche par caméra, période, type]                            │
└────────────────────────────────────────────────────────────────────┘
```

Poll auto-refresh 5 s pour la santé globale, 10 s pour la réconciliation, temps-réel pour les métriques (WS).

---

## 20.5 Arbre de décision pour un opérateur

Guide affiché en ligne dans le dialog diagnostic :

```
Caméra offline ?
├─ Cause : connection_refused / timeout
│   ├─ Retester → OK ? Fin.
│   └─ Retester → KO
│       ├─ Ping l'IP depuis le VMS → réussit ? → caméra probablement en veille (POE cyclique)
│       └─ Ping → échoue → problème réseau (VLAN, câble, PoE) → intervention terrain
│
├─ Cause : auth_failed
│   ├─ Mot de passe caméra a-t-il été changé récemment ?
│   │   ├─ Oui → mettre à jour dans /cameras/{id}
│   │   └─ Non → tester avec un client tiers (VLC) → même erreur → réinitialiser caméra
│
├─ Cause : codec_mismatch
│   ├─ Aller dans /cameras/{id} → onglet Vidéo
│   ├─ Changer le codec attendu (H.264 ↔ H.265)
│   └─ Sauver → tester → OK ?
│
└─ Cause : stream_locked
    ├─ Une autre app (VLC, autre VMS, appli mobile) consomme les sessions
    ├─ Se déconnecter des autres apps
    └─ Redémarrer la caméra (réinit sessions)
```

Cet arbre est encodé dans les `actions` du dialog — l'opérateur suit les boutons sans avoir à connaître l'arbre par cœur.

---

## 20.6 Journal lifecycle streams

Composant existant depuis v2.15.0 (`db.stream_lifecycle_journal`, capped 20 000 entrées).

Chaque transition d'état d'un flux caméra écrit une ligne :

```json
{
  "timestamp": "2026-07-24T14:32:11+00:00",
  "camera_id": "uuid",
  "action": "register|unregister|status_change|error|refresh",
  "from_state": "online",
  "to_state": "offline",
  "reason": "connection_refused after 3 attempts",
  "caller": "probe_loop",
  "correlation_id": "..."
}
```

Consultable via `/diagnostics/stream-lifecycle`. Filtrable par caméra, action, plage temps.

**Utilité clé** : reconstitution des incidents *a posteriori* (« pourquoi la caméra a-t-elle basculé offline hier à 3h47 ? »).

---

## 20.7 Rapport d'incident PDF

À la demande d'un admin, MG-VMS génère un **rapport d'incident PDF** pour une caméra spécifique + une plage temps.

Endpoint : `POST /api/v1/diagnostics/incident-report`

Body :
```json
{
  "camera_id": "uuid",
  "from": "2026-07-24T00:00:00Z",
  "to": "2026-07-24T23:59:59Z",
  "include": ["lifecycle", "diagnostics", "recordings", "events", "gpu_metrics"]
}
```

Contenu du PDF :
- En-tête : caméra, période, opérateur qui demande.
- Timeline lifecycle sur la période.
- Diagnostics associés (causes probables des incidents).
- Snapshots des enregistrements aux moments critiques.
- Événements IA générés.
- Métriques CPU/GPU/réseau.
- Conclusion automatique (« 2 incidents, cause principale = auth_failed »).
- Signature électronique (hash SHA-256 des données).

Utile pour dossiers d'assurance, RGPD, litiges clients.

---

## 20.8 Notifications proactives

**Le VMS ne doit pas attendre que l'utilisateur consulte /diagnostics** pour signaler un problème critique.

Événements diagnostic qui déclenchent une notification proactive :

- `system.gpu_saturated_vram` (VRAM > 90% pendant > 5 min)
- `system.storage_almost_full` (pool > 90%)
- `system.disk_smart_warning`
- `system.mongo_slow` (P95 > 2s pendant > 5 min)
- `plugin.disabled_quota_*` (plugin auto-désactivé)
- `camera.offline_persistent` (offline > 30 min pour caméra critique — flag `critical: true`)

Chaque notification passe par le pipeline standard (chapitre 5 §5.5) : SMTP, Discord, Telegram, MQTT, webhook — configurable admin.

---

## 20.9 Tests d'acceptation

### TA-20.1 — Voyant rouge cliquable

**Given** une caméra offline.
**When** je clique sur le badge rouge dans /cameras.
**Then** un dialog s'ouvre avec cause probable en français + 3 actions minimum.

### TA-20.2 — Cause probable enrichie

**Given** un plugin `fire-detection` crash avec `CUDA out of memory`.
**When** je consulte son diagnostic.
**Then** la cause probable est spécifique (« VRAM saturée ») et non générique.

### TA-20.3 — Action « Retester » fonctionnelle

**Given** une caméra offline avec cause `connection_refused`.
**When** je clique « Retester la connexion ».
**Then** un `POST /cameras/{id}/refresh-stream` est envoyé, la caméra teste sa connexion, le résultat s'affiche dans le dialog en < 5s.

### TA-20.4 — Historique 7 jours

**Given** une caméra active depuis 30 jours.
**When** j'ouvre son diagnostic.
**Then** l'historique affiche 168h de données lifecycle avec % online / MTBF.

### TA-20.5 — Notification proactive

**Given** le pool storage atteint 91% (déclencheur à 90%).
**When** l'état est détecté.
**Then** une notification SMTP + Discord est envoyée aux admins dans les 60 s.

---

## 20.10 Métriques de succès

- **Taux de résolution autonome** — % de voyants rouges résolus sans ticket support. Cible ≥ 80%.
- **Temps médian d'ACK** — de l'apparition du voyant à l'ouverture du dialog. Cible ≤ 60 s.
- **Précision cause probable** — % de causes proposées correctement identifiées (survey opérateurs). Cible ≥ 85%.
- **Nombre de règles diagnostic** — cible ≥ 100 en v3.0 (couvrant les cas les plus fréquents).

---

## 20.11 ADR

### ADR-20 — Moteur de règles heuristiques + priorités vs moteur ML

**Contexte** : deux approches pour deviner la cause.
**Décision** : moteur de règles heuristiques (pattern matching + priorités). Ajoutable/modifiable par admin ou plugin sans changement de code.
**Conséquences** : maintenance manuelle des règles. Extensible via plugins.
**Alternatives rejetées** : ML sur logs (overkill pour v3.0, coût opérationnel, données insuffisantes au départ).

### ADR-21 — Cache 30s de la cause probable

**Contexte** : un flap violent (30 crash/min) pourrait saturer le moteur.
**Décision** : cache la résolution de cause 30s. Une nouvelle cause ne peut apparaître qu'après ce délai.
**Conséquences** : latence de mise à jour cause = 30s max. Acceptable.

---

## Annexes

### A. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : anatomie dialog · moteur de règles · 5 domaines couverts · rapport PDF · notifications proactives · 2 ADR |
