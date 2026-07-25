# Chapitre 11 — Plateforme de plugins

> **Version** : v1.0 · **Date** : 2026-07-24 · **Statut** : brouillon en cours de validation · **Chapitre fondateur**
> **Auteur** : équipe MG-VMS · **Reviewers** : *à compléter*
> **Chapitres liés** : `04-architecture-cible` (ADR-15) · `02-philosophie-principes` (R16) · `05-contrats-interfaces` (SDK/API) · `24-plugins-marketplace` (catalogue)

Ce chapitre définit le pivot architectural le plus important de MG-VMS Next Generation : **MG-VMS n'est plus un VMS avec des plugins, c'est une plateforme dont tout est plugin sauf le noyau**. Ce paradigme est celui de Home Assistant, Grafana et VS Code. Il change la nature du produit — de « logiciel de vidéosurveillance » à « écosystème de vidéosurveillance ».

---

## 11.1 Vision

### 11.1.1 Le problème du monolithe

Un VMS traditionnel (Milestone, Genetec, Digifort, Nx Witness, y compris MG-VMS v2.22.0) est un **monolithe** : tout le code est dans un seul binaire, toutes les fonctionnalités sont chargées au démarrage, tous les intégrateurs partagent la même version.

Conséquences observées :
- Un bug dans le module ANPR peut planter le pipeline de détection d'objets.
- Ajouter un nouveau moteur ANPR (PaddleOCR à côté de fast-alpr) exige de modifier le cœur.
- Un site qui n'a pas besoin d'IA charge quand même les 500 MB de PyTorch en RAM.
- Un intégrateur qui veut supporter un protocole domotique propriétaire (KNX, BACnet) doit forker le produit.
- Un fix de sécurité dans un module rare oblige à re-livrer tout le VMS.

### 11.1.2 Le pivot

MG-VMS NG divise le système en **deux zones** aux frontières strictes :

**Le noyau (Core)** — code obligatoire, minimal, stable :
- Gestion utilisateurs & permissions (RBAC)
- Gestion caméras (CRUD, ONVIF, RTSP)
- Passerelle vidéo (go2rtc)
- Enregistrement (recorder)
- Lecture (player, timeline)
- PTZ (base — joystick, presets)
- API HTTP + WebSocket
- Dashboard (KPIs de base)
- **Plugin Manager** (installer, charger, superviser, sandbox)

**Les plugins** — code optionnel, activable, remplaçable :
- Tous les modules IA (YOLO, ANPR, Face, Smoke, Fire, PPE, Counting, Loitering, Fall Detection…)
- Tous les moteurs ANPR (fast-alpr, OpenALPR, PaddleOCR, Plate Recognizer cloud, EasyOCR…)
- Toutes les intégrations tierces (Home Assistant, Node-RED, Grafana, MQTT, LDAP, OIDC…)
- Toutes les notifications (Discord, Telegram, Slack, Teams, Signal, WhatsApp, SMS, Pushover…)
- Tous les stockages non-locaux (S3, Azure Blob, GCS, iSCSI, SFTP…)
- Tous les modules métier avancés (Parking, Heatmap, Zone Intrusion, Counting, Analytics)
- Toutes les extensions UI (widgets dashboard custom, murs vidéo spécialisés)
- Tous les protocoles domotique (KNX, BACnet, Modbus, Zigbee, Z-Wave)

### 11.1.3 Ce que ça change

**Pour l'utilisateur** :
- Il installe uniquement ce dont il a besoin. Un site résidentiel = noyau + 2 plugins (YOLO, Telegram). Un site industriel = noyau + 15 plugins.
- La mise à jour du noyau n'affecte pas ses plugins (compatibilité SemVer).
- Un plugin qui plante ne fait pas tomber le VMS.

**Pour l'intégrateur** :
- Il écrit un plugin, le publie sur le Marketplace, le vend/donne. Pas besoin de fork.
- Il implémente une interface standardisée (`Plugin`), MG-VMS gère le reste (auth, config, logs, health).
- Un plugin peut être écrit en Python, C#, JS, Go ou Rust (SDK multi-langages).

**Pour l'équipe MG-VMS** :
- Le noyau reste petit et testable (~ 5 000 lignes Python).
- Chaque plugin a son propre cycle de vie, sa propre équipe, ses propres versions.
- La communauté peut contribuer sans que ça bloque les releases core.

---

## 11.2 Anatomie d'un plugin

### 11.2.1 Structure de fichiers

Un plugin est un dossier auto-suffisant :

```
mgvms-plugin-yolo-detection/
├── manifest.yaml               # Métadonnées + dépendances (obligatoire)
├── plugin.py                   # Point d'entrée (Python) — ou plugin.js, plugin.exe, plugin.wasm
├── requirements.txt            # Deps Python (si Python)
├── models/                     # Modèles IA embarqués (optionnel)
│   └── yolo11n.pt
├── config/
│   └── schema.json             # JSON Schema de la config utilisateur
├── ui/
│   ├── settings.jsx            # Composants React de config (optionnel)
│   └── widgets.jsx             # Widgets dashboard (optionnel)
├── docs/
│   ├── README.md
│   ├── CHANGELOG.md
│   └── screenshots/
├── tests/
│   └── test_plugin.py
└── LICENSE
```

### 11.2.2 Le `manifest.yaml`

C'est le contrat unique entre le plugin et MG-VMS. **Aucun** plugin ne charge sans manifest valide.

```yaml
apiVersion: mgvms.io/v1
kind: Plugin
metadata:
  name: yolo-detection
  displayName: "YOLO Object Detection"
  version: "1.4.2"
  description: "Détection d'objets temps-réel via YOLOv11 (CPU/GPU)."
  author: "MG-VMS Team <plugins@mg-vms.io>"
  homepage: "https://plugins.mg-vms.io/yolo-detection"
  license: "MIT"
  categories: ["ai", "detection"]
  icon: "icon.svg"
  screenshots: ["screenshots/live.png", "screenshots/config.png"]

spec:
  runtime: python                 # python | node | binary | wasm
  entrypoint: plugin.py
  interface: FrameAnalyzer        # cf. §11.3 (types d'interface)

  compatibility:
    mgvms_core: ">=3.0.0,<4.0.0"  # Semver range compat avec le core
    platforms: [linux/amd64, linux/arm64]

  capabilities:                   # Permissions demandées (déclaratif)
    - camera.frame.read
    - event.write
    - config.read
    - db.namespace.write          # Écriture dans son namespace DB isolé

  resources:                      # Réservation matérielle
    cpu_cores: 1
    ram_mb: 512
    gpu: optional                 # required | optional | none
    vram_mb: 1024
    disk_mb: 200

  dependencies:
    plugins: []                   # Plugins requis (ex. `tracking-bytetrack: >=1.0`)
    system: ["ffmpeg>=5.0"]       # Binaires système requis

  config_schema: config/schema.json

  cameras:
    scope: per-camera             # global | per-camera
    default_enabled: false

  ui:
    settings: ui/settings.jsx
    widgets:
      - name: yolo-detection-preview
        type: camera-overlay
        component: ui/widgets/preview.jsx
```

### 11.2.3 Le point d'entrée

Chaque plugin implémente une **interface standard** selon sa nature. Exemple en Python pour un plugin de type `FrameAnalyzer` :

```python
# plugin.py
from mgvms_sdk import FrameAnalyzer, PluginContext, Frame, AnalysisResult, Detection

class YoloDetectionPlugin(FrameAnalyzer):
    """Plugin YOLO — détection d'objets sur chaque frame."""

    async def on_load(self, ctx: PluginContext) -> None:
        """Appelé une fois au démarrage du plugin. Charger les modèles."""
        self.model_path = ctx.config.get("model", "yolo11n.pt")
        self.device = ctx.gpu.device if ctx.gpu.available else "cpu"
        from ultralytics import YOLO
        self.model = YOLO(f"models/{self.model_path}")
        self.model.to(self.device)
        ctx.log.info(f"YOLO chargé sur {self.device}")

    async def analyze(self, frame: Frame, camera_config: dict) -> AnalysisResult:
        """Appelé à chaque frame. Retourner les détections."""
        results = self.model.predict(frame.numpy_bgr, verbose=False)[0]
        detections = [
            Detection(
                label=self.model.names[int(b.cls)],
                confidence=float(b.conf),
                bbox=(int(b.xyxy[0][0]), int(b.xyxy[0][1]),
                      int(b.xyxy[0][2]), int(b.xyxy[0][3])),
            )
            for b in results.boxes if float(b.conf) > 0.35
        ]
        return AnalysisResult(detections=detections, timing_ms=int((results.speed["inference"] or 0)))

    async def on_config_change(self, new_config: dict) -> None:
        """Appelé à chaque changement de config utilisateur."""
        # Rechargement du modèle si le path a changé
        if new_config.get("model") != self.model_path:
            await self.on_load(...)

    async def on_unload(self) -> None:
        """Nettoyage avant arrêt/désinstallation."""
        del self.model
```

**Contrats respectés** :
- Aucun accès direct à MongoDB → passe par `ctx.db` (namespace isolé).
- Aucun accès direct à la config → `ctx.config` (typée + validée schéma).
- Aucun log direct → `ctx.log` (routé vers le journal plugin + supervisor).
- Aucun accès aux autres plugins → passage par `ctx.emit_event(...)` / `ctx.call_plugin(...)`.

---

## 11.3 Types d'interfaces

Un plugin doit implémenter **une seule** interface parmi celles-ci. La plateforme prend en charge le reste (lifecycle, config, logs, health).

### 11.3.1 `FrameAnalyzer`
Analyse chaque frame vidéo, retourne des détections/résultats.
Exemples : YOLO, tracking, face recognition, smoke detection.

**Contrat** :
```python
async def analyze(frame: Frame, camera_config: dict) -> AnalysisResult
```

### 11.3.2 `PlateRecognizer`
Sous-type de FrameAnalyzer spécialisé ANPR — retourne un format normalisé plaque.
**Toute plaque, quel que soit le moteur, retourne la même structure JSON.**

```python
async def recognize(frame: Frame, vehicle_bbox: Optional[BBox]) -> list[PlateResult]
```

`PlateResult` :
```json
{
  "text": "AB-123-CD",
  "confidence": 0.92,
  "country_hint": "fr",
  "region_hint": "PACA",
  "bbox_plate": [x1, y1, x2, y2],
  "engine": "paddle-ocr",
  "processing_ms": 42
}
```

Exemples : fast-alpr, OpenALPR, PaddleOCR, Plate Recognizer (cloud), EasyOCR, Tesseract, Google Vision, Azure Vision.

### 11.3.3 `EventConsumer`
Reçoit les événements du core (détection, alerte, plaque) et effectue une action.
Exemples : notification Discord, envoi MQTT, webhook, log Prometheus.

```python
async def on_event(event: MGVMSEvent) -> ConsumerResult
```

### 11.3.4 `ActionProvider`
Expose des actions déclenchables depuis l'automatisation.
Exemples : envoyer un SMS, ouvrir un relais, jouer une TTS.

```python
def actions() -> list[ActionDefinition]
async def execute(action_id: str, params: dict) -> ActionResult
```

### 11.3.5 `TriggerProvider`
Expose des déclencheurs utilisables dans l'automatisation.
Exemples : MQTT topic, calendrier avancé, GPIO Raspberry Pi, webhook entrant.

```python
async def start_watching(trigger_config: dict) -> AsyncIterator[TriggerEvent]
```

### 11.3.6 `StorageBackend`
Fournit un stockage non-local pour les segments vidéo.
Exemples : S3, Azure Blob, GCS, SFTP.

```python
async def write_segment(camera_id: str, segment: VideoSegment) -> str  # returns URL
async def read_segment(url: str) -> bytes
async def delete_segment(url: str) -> None
async def list_segments(camera_id: str, from_dt, to_dt) -> list[SegmentMeta]
```

### 11.3.7 `AuthProvider`
Fournit une source d'authentification externe.
Exemples : LDAP, Active Directory, OIDC (Google, Microsoft, Keycloak).

```python
async def authenticate(credentials: dict) -> Optional[UserInfo]
async def list_groups(user: str) -> list[str]
```

### 11.3.8 `UIExtension`
Ajoute des composants au frontend (widgets dashboard, pages custom, overlays).
Déclaré dans le manifest, code React chargé dynamiquement via `import()` navigateur.

### 11.3.9 `DomainService`
Plugin métier autonome qui expose ses propres endpoints REST + UI + WS sous un préfixe dédié.
Exemples : Parking Manager, Heatmap Engine, Analytics Dashboard.

```python
def routes() -> APIRouter                # préfixé /api/v1/plugins/{name}/*
def ui_pages() -> list[UIPageDefinition]
def ws_channels() -> list[str]
```

### 11.3.10 Interface libre (`CustomPlugin`)
Plugin qui ne rentre dans aucune catégorie. Doit déclarer ses capacités explicitement dans le manifest et sa surface est validée manuellement par la review Marketplace.

---

## 11.4 Le Plugin Manager

### 11.4.1 Responsabilités

Le Plugin Manager est un **composant du noyau** (jamais un plugin lui-même). Il assure :

1. **Découverte** — scan du dossier `/data/plugins/` + interrogation Marketplace.
2. **Installation** — téléchargement depuis Marketplace, vérification signature GPG, extraction, résolution des dépendances.
3. **Chargement** — parsing manifest, création du sandbox, injection du `PluginContext`.
4. **Cycle de vie** — appel `on_load` / `on_config_change` / `on_unload`.
5. **Supervision** — monitoring CPU/RAM/GPU, restart si crash, circuit breaker si > 3 crashes/heure.
6. **Sandboxing** — isolation processus (subprocess séparé pour plugins Python haute charge, worker thread pour plugins légers).
7. **Communication** — bus événementiel interne asyncio pour les échanges plugin ↔ core ↔ plugin.
8. **Persistence** — chaque plugin a son namespace DB isolé (`db.plugin_data.{plugin_name}`).

### 11.4.2 Modes d'exécution

Un plugin peut tourner selon 3 modes selon sa nature :

| Mode | Description | Cas d'usage |
|---|---|---|
| **In-process** | Chargé dans le process backend, thread ou coroutine partagée | Plugins légers, EventConsumer, notifications |
| **Sub-process** | subprocess séparé, communication via socket unix + JSON-RPC | Plugins IA lourds (YOLO, Face), isolation crash |
| **Container** | Docker container isolé, communication via socket / HTTP | Plugins avec deps système lourdes ou langage exotique (Rust, C++) |

Le mode est choisi automatiquement selon `spec.runtime` + `spec.resources` + config admin. Par défaut : plugins IA en sub-process, plugins d'intégration en in-process.

### 11.4.3 Interface utilisateur — page « Plugins »

```
┌──────────────────────────────────────────────────────────────────────┐
│  Plugins                                                              │
│  ────────────────────────────────────────────────────────────────    │
│                                                                       │
│  🔵 Installés  (12)  │  🟢 Catalogue  (128)  │  ⚙ Développement (2)  │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 📷  YOLO Detection                                v1.4.2 ✅  │   │
│  │     Détection d'objets temps-réel (YOLOv11 CPU/GPU)          │   │
│  │     Actif · 3 caméras · CPU 12% · RAM 380 MB · GPU 22%       │   │
│  │     [Configurer] [Désactiver] [Logs] [Documentation] [MAJ]    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 🚗  Plate Recognizer (cloud)                       v2.1.0 ✅  │   │
│  │     ANPR cloud haute précision · fallback fast-alpr           │   │
│  │     Actif · 2 caméras · quota 4823/10000 mois                 │   │
│  │     [Configurer] [Désactiver] [Logs] [Documentation]          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 🅿  Parking Manager                                v0.9.3 ⚠   │   │
│  │     Gestion des places, occupation, PMR/VIP                   │   │
│  │     Actif · crash il y a 3 min (auto-restart réussi)          │   │
│  │     [Configurer] [Désactiver] [Logs] [Diagnostic]             │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

**data-testid** : `plugin-row-{name}`, `plugin-{name}-configure`, `-disable`, `-logs`, `-update`, `-diagnostic`.

### 11.4.4 Configuration d'un plugin

Chaque plugin a un schéma JSON Schema (`config/schema.json`). Le frontend génère automatiquement un formulaire React à partir de ce schéma (via `react-jsonschema-form`) — pas de code UI nécessaire pour la config de base.

Exemple `schema.json` :
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Configuration YOLO Detection",
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "enum": ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt", "yolo11l.pt", "yolo11x.pt"],
      "default": "yolo11n.pt",
      "title": "Modèle YOLO",
      "description": "n=nano (rapide), x=xlarge (précis, lent)"
    },
    "confidence": {
      "type": "number",
      "minimum": 0.1, "maximum": 0.99,
      "default": 0.35,
      "title": "Seuil de confiance"
    },
    "classes_enabled": {
      "type": "array",
      "items": {"type": "string"},
      "default": ["person", "car", "truck", "motorcycle"],
      "title": "Classes détectées"
    }
  }
}
```

Un plugin peut fournir un composant React custom (`ui/settings.jsx`) pour dépasser la génération auto — utile pour UI complexes (ex. dessin de zones sur image).

---

## 11.5 Sécurité & sandbox

### 11.5.1 Capabilities déclaratives

Un plugin déclare **explicitement** ses besoins dans le manifest (§11.2.2). Le Plugin Manager refuse tout appel non-autorisé au runtime.

Capabilities disponibles :

| Capability | Permet |
|---|---|
| `camera.frame.read` | Lire les frames vidéo (FrameAnalyzer, PlateRecognizer) |
| `camera.config.read` | Lire la config caméra |
| `camera.ptz.control` | Envoyer des commandes PTZ (avec audit obligatoire) |
| `event.write` | Publier des événements sur le bus |
| `event.read` | Souscrire au flux d'événements |
| `alert.create` | Créer une alerte critique |
| `db.namespace.write` | Écrire dans son namespace DB isolé |
| `db.namespace.read` | Lire son namespace |
| `network.outbound` | Faire des appels HTTP sortants (avec whitelist domaines) |
| `filesystem.data` | Lire/écrire dans son dossier `data/` |
| `notification.send` | Envoyer une notification via le core |
| `automation.trigger` | Émettre un trigger vers l'automatisation |

Un plugin qui tente une action sans la capability déclarée reçoit une `PermissionDenied` — sans crash, mais loguée.

### 11.5.2 Isolation

- **In-process** : le plugin partage l'espace mémoire du backend. Isolation logique via `PluginContext` (pas de global mutable exposé). Adapté aux plugins de confiance (officiels + verified).
- **Sub-process** : espace mémoire séparé. Communication JSON-RPC. Un crash tue le sub-process, pas le backend. Redémarrage auto par superviseur.
- **Container** : isolation OS complète. Aucun accès direct au host. Réseau restreint à une bridge dédiée. Adapté aux plugins tiers non-vérifiés.

### 11.5.3 Signature & vérification

Les plugins du Marketplace officiel sont **signés GPG** par une clé MG-VMS. Le Plugin Manager vérifie la signature avant installation. Un plugin non-signé peut être installé manuellement (`Développement`) mais un warning permanent est affiché dans la liste.

### 11.5.4 Ressources

Chaque plugin est soumis à des quotas :
- **CPU cores** — max déclaré dans manifest. Dépassement 30s ⇒ throttle.
- **RAM** — max déclaré. Dépassement ⇒ kill + restart.
- **GPU VRAM** — allocation partagée par le GPU Manager (chapitre 17). Dépassement ⇒ dégradation gracieuse (retry avec batch plus petit).
- **Disk** — quota dans le namespace `plugin_data/{name}/`.
- **Network** — rate limiting sortant (100 req/s par défaut).

Un plugin qui viole ses quotas 3 fois en 1h ⇒ **désactivation automatique** + notification admin.

---

## 11.6 Cas d'usage clés

### 11.6.1 Multi-ANPR : plusieurs moteurs sur la même caméra

Une caméra parking peut utiliser 3 plugins ANPR simultanément :

```
Entrée principale
  ☑ Plate Recognizer (cloud)     · précision 98%, quota 10k/mois
  ☑ PaddleOCR (local)             · précision 91%, illimité
  ☑ EasyOCR (local)               · précision 87%, illimité

Mode :
  ◉ Meilleur résultat (fallback en cascade)
  ○ Comparaison (mise en évidence divergences)
  ○ Fusion (vote majoritaire par caractère)
```

**Sémantique des modes** :
- **Meilleur résultat** : appelle le plugin 1. Si `confidence >= 0.85` → résultat retenu. Sinon appelle plugin 2. Etc. Économie de quota cloud.
- **Comparaison** : appelle tous en parallèle. Journalise les divergences dans `db.plate_comparisons` pour analyse qualité.
- **Fusion** : appelle tous. Un algorithme de vote par caractère produit le résultat final (utile pour caméras difficiles).

Le core ne connaît **aucun** moteur individuellement — il consomme uniquement l'interface `PlateRecognizer` avec sa sortie JSON normalisée.

### 11.6.2 Sélection de plugin par caméra

Chaque caméra a sa propre liste de plugins activés. Le schéma `db.cameras.plugins` :

```json
{
  "yolo-detection": {"enabled": true, "config": {"confidence": 0.4}},
  "plate-recognizer": {"enabled": true, "config": {"mode": "best"}},
  "paddle-ocr": {"enabled": true, "config": {}},
  "parking-manager": {"enabled": true, "config": {"parking_id": "P1"}},
  "telegram-notifier": {"enabled": false},
  "face-recognition": {"enabled": false},
  "fire-detection": {"enabled": false}
}
```

Une caméra parking exploite 4 plugins. Une caméra de couloir simple n'en active qu'un (YOLO). Cette granularité permet l'optimisation matérielle (une caméra sans IA ne consomme 0 GPU).

### 11.6.3 Ajout de caméra avec plugins

L'assistant d'ajout de caméra (chapitre 6, Étape 5) devient dynamique : les checkboxes IA sont générées à partir de la liste des plugins `FrameAnalyzer` installés + activés globalement.

```
Plugins IA activables sur cette caméra :

  ☑ YOLO Detection                     · v1.4.2 · ~15 fps GPU
  ☑ Plate Recognizer                   · v2.1.0 · cloud
  ☐ Face Recognition                   · v0.8.5 · GPU requis
  ☐ Fire Detection                     · v0.3.0 · Beta
  ☐ Smoke Detection                    · v0.3.0 · Beta
  ☐ PPE Detection                      · v0.5.1 · Beta
  ☐ Parking Manager                    · v0.9.3 · Requires zone drawing

  [+ Installer d'autres plugins]
```

### 11.6.4 Un plugin qui crash

**Scénario** : `fire-detection` plugin plante toutes les 5 min pour une raison inconnue.

**Comportement système** :
1. Le superviseur détecte le crash (return code ≠ 0 sub-process ou exception in-process).
2. Restart automatique avec backoff (1s, 2s, 4s, 8s…).
3. Si > 3 crashes en 1h → circuit breaker ouvert 30 min, plugin marqué « ⚠ instable ».
4. UI affiche un badge orange sur la ligne du plugin avec [Diagnostic].
5. Le clic Diagnostic ouvre : timeline des crashes + extrait de logs + stack trace + [Signaler au développeur].
6. **Les autres plugins continuent à fonctionner normalement.** Le core continue à servir. Les autres modules IA de la même caméra continuent.

### 11.6.5 Mise à jour d'un plugin

**Scénario** : `yolo-detection` v1.4.2 → v1.5.0.

1. UI Plugins affiche « Mise à jour disponible : 1.5.0 » avec [Changelog] [Mettre à jour].
2. Clic MAJ → téléchargement, vérification signature.
3. `on_unload()` appelé sur v1.4.2.
4. Extraction v1.5.0 dans un dossier séparé (`/data/plugins/yolo-detection.v1.5.0/`).
5. Test de chargement (`on_load()` avec context de test).
6. Si OK → bascule symlink `current/` → v1.5.0. Config utilisateur préservée.
7. Si KO → rollback automatique. Warning UI. Config préservée.

**Rétention** : les 2 versions précédentes sont conservées sur disque pour rollback manuel.

---

## 11.7 Marketplace

### 11.7.1 Catalogue officiel

Une instance MG-VMS de référence héberge le catalogue public :
- URL : `https://plugins.mg-vms.io`
- API JSON : `https://plugins.mg-vms.io/api/v1/plugins?category=ai&search=...`
- Miroir configurable dans les settings (`MGVMS_PLUGIN_REGISTRY_URL`) pour environnements air-gapped.

Chaque plugin publié :
- Passe une review qualité (code review + tests de compat + scan sécurité).
- A un badge `Officiel` (édité par MG-VMS), `Verified` (auteur vérifié, review passée), `Community` (soumis, non-review), ou `Beta`.
- Publie son manifest, screenshots, changelog, licence.
- Expose ses métriques d'usage anonymisées (téléchargements, ratings).

### 11.7.2 Publication d'un plugin

Un développeur tiers publie son plugin via :

```bash
# CLI officiel
mgvms-cli plugin publish ./my-plugin --key=my-signing-key.gpg
```

- Le CLI packagé un `.mgplugin` (zip signé) et le pousse au registry.
- Un formulaire complète les métadonnées (description longue, screenshots, catégorie).
- Une PR est ouverte automatiquement sur le repo Marketplace pour la review.
- Une fois approuvé → publication.

### 11.7.3 Modèle économique

- Plugins **gratuits** — majorité de l'écosystème (community, verified).
- Plugins **freemium** — plugin gratuit, service backend payant (ex. Plate Recognizer cloud avec quota).
- Plugins **payants** — clé de licence via provider Marketplace (v3.5+).

Cette dernière catégorie est optionnelle en v3.0 (focus sur l'ouverture) mais planifiée pour un développement durable de l'écosystème.

---

## 11.8 SDK multi-langages

### 11.8.1 SDK Python (`mgvms-plugin-sdk`)

Officiellement supporté. Type hints complets. Async natif. Templates de projet :

```bash
pip install mgvms-plugin-sdk
mgvms-cli plugin init --template=frame-analyzer my-plugin
```

Templates disponibles : `frame-analyzer`, `plate-recognizer`, `event-consumer`, `action-provider`, `storage-backend`.

### 11.8.2 SDK JavaScript / TypeScript (`@mgvms/plugin-sdk`)

Node.js 18+. Bindings TypeScript. Cible : plugins d'intégration légère, extensions UI.

### 11.8.3 SDK Go et Rust

Cibles : plugins hautes performances (traitement vidéo custom, protocoles bas-niveau). Communication via JSON-RPC sur socket unix. Docs plus techniques.

### 11.8.4 SDK C#

Cible : intégration écosystème .NET / Windows. Notamment pour bridges avec Milestone, Genetec, Avigilon (migration).

### 11.8.5 Contrat de compat SDK

Chaque SDK est versionné indépendamment mais compatible avec la spec `mgvms.io/v1` du manifest. Un plugin écrit avec SDK Python v1.x fonctionne sur toute version MG-VMS supportant `apiVersion: mgvms.io/v1`.

---

## 11.9 Santé & observabilité

### 11.9.1 Métriques par plugin

Chaque plugin remonte automatiquement :

- **État** : loaded / running / paused / crashed / disabled
- **Version** installée
- **Uptime** depuis dernier restart
- **CPU** usage moyen 1min / max 1h
- **RAM** RSS actuel / max 1h
- **GPU** VRAM allouée / occupation (si applicable)
- **Temps de réponse** — P50, P95, P99 sur `analyze()` / `on_event()`
- **FPS** pour les FrameAnalyzer (frames analysées / seconde)
- **Erreurs** — compteur 1h, dernière erreur avec stack

Exposé via `GET /api/v1/plugins/{name}/health` + WebSocket canal `plugin_health`.

### 11.9.2 Logs par plugin

Chaque plugin a son propre journal `db.plugin_logs.{name}` (capped collection, TTL 7 jours) + fichier `/data/logs/plugins/{name}.log` (rotation 100 MB).

L'UI Plugins → [Logs] affiche un stream live filtrable par niveau.

### 11.9.3 Diagnostics

Reprise du principe R02 (« aucun voyant rouge orphelin ») :

Un plugin en erreur affiche dans l'UI un dialog explicite :
```
🔴 Fire Detection en erreur (3 crashes en 5 min)

Cause probable : le modèle SmokeNet-v2.pt est corrompu.
Détail technique : RuntimeError: Error loading model : unexpected EOF at byte 1024.

Actions recommandées :
  [Réinstaller le plugin]
  [Restaurer la version précédente (v0.2.9)]
  [Signaler au développeur]
  [Désactiver ce plugin sur les caméras]
```

---

## 11.10 Migration depuis MG-VMS v2.22.0

### 11.10.1 Composants à externaliser en plugins

Le code actuel qui devient des plugins v3.0 :

| Composant v2.22.0 | Devient plugin | Interface |
|---|---|---|
| `ai_engine.py` (YOLO) | `yolo-detection` | FrameAnalyzer |
| `ai_engine.py` (fast-alpr) | `fast-alpr` | PlateRecognizer |
| Notifications SMTP | `smtp-notifier` | EventConsumer |
| Notifications Discord | `discord-notifier` | EventConsumer |
| Notifications Telegram | `telegram-notifier` | EventConsumer |
| Face recognition (InsightFace) | `face-recognition-insightface` | FrameAnalyzer |
| Scénarios (crossline, zone, loitering) | `zone-analytics` | FrameAnalyzer + ActionProvider |

### 11.10.2 Composants qui restent dans le noyau

- Serveur HTTP FastAPI + auth
- Gestion des caméras (CRUD, ONVIF discovery)
- Provisionnement go2rtc (streaming.py)
- Recorder ffmpeg (recorder.py)
- WebRTC signaling
- PTZ base (v3.0 étendu par plugin `ptz-advanced` pour tours, calendrier)
- Frame source GPU (frame_source.py) — infrastructure partagée entre plugins FrameAnalyzer
- Dashboard KPIs de base
- Plugin Manager (nouveau)

### 11.10.3 Path de migration

**Phase 1 (v3.0.0)** — plateforme opérationnelle :
- Plugin Manager fonctionnel.
- 6 plugins « officiels » livrés avec le core : `yolo-detection`, `fast-alpr`, `smtp-notifier`, `discord-notifier`, `telegram-notifier`, `zone-analytics`.
- API `/api/v1/plugins/*` complète.
- SDK Python v1.

**Phase 2 (v3.1)** — écosystème :
- Marketplace en ligne (`plugins.mg-vms.io`).
- 20+ plugins additionnels (parking, heatmap, MQTT, Home Assistant, LDAP, S3…).
- SDK JavaScript.

**Phase 3 (v3.2+)** — extensibilité avancée :
- Sandbox Docker container pour plugins tiers.
- Signature payante pour verified plugins.
- SDK Go/Rust/C#.
- Support plugins premium.

---

## 11.11 Tests d'acceptation

### TA-11.1 — Un plugin ne peut pas planter le noyau

**Given** un plugin `broken-plugin` qui `raise Exception()` dans `analyze()`.
**When** je l'installe et l'active sur une caméra.
**Then** le core continue à servir toutes ses API. Les autres plugins continuent. Le plugin est marqué en erreur, mais rien d'autre ne change.

### TA-11.2 — Multi-ANPR fonctionne

**Given** 3 plugins PlateRecognizer installés et actifs sur une caméra en mode « meilleur résultat ».
**When** un véhicule passe.
**Then** la plaque finale retournée par le core a le meilleur `confidence` parmi les 3. Le champ `engine` documente lequel a été retenu.

### TA-11.3 — Capabilities respectées

**Given** un plugin déclare uniquement `event.read` mais tente d'écrire dans `db.namespace`.
**When** il appelle `ctx.db.write(...)`.
**Then** `PermissionDenied` levée, action bloquée, log audit + notif admin.

### TA-11.4 — Mise à jour rollback

**Given** un plugin `yolo-detection` v1.4.2 en fonctionnement.
**When** je mets à jour vers v1.5.0 et que le `on_load()` de la nouvelle version raise.
**Then** l'ancienne version est restaurée automatiquement. La caméra continue à détecter. UI affiche « Mise à jour échouée, rollback effectué ».

### TA-11.5 — Désinstallation propre

**Given** un plugin actif sur 3 caméras.
**When** je le désinstalle.
**Then** :
- `on_unload()` appelé pour chaque instance.
- Les caméras sont mises à jour (plugin retiré de leur liste).
- Le namespace `db.plugin_data.{name}` est archivé (`db.plugin_data_archive.{name}`, TTL 30 jours).
- Les fichiers `/data/plugins/{name}/` sont conservés 7 jours (soft-delete pour réinstallation rapide).

### TA-11.6 — Quotas respectés

**Given** un plugin déclare 512 MB RAM max.
**When** son usage dépasse 700 MB pendant 30 s.
**Then** le plugin est kill + restart. Log warning. Compteur d'incidents incrémenté.

### TA-11.7 — Config validée par schéma

**Given** un plugin avec schema exigeant `confidence` entre 0.1 et 0.99.
**When** l'utilisateur soumet `confidence: 1.5`.
**Then** HTTP 422 avec message clair. Config précédente conservée.

---

## 11.12 Métriques de succès

**Écosystème** :
- Nombre de plugins Officiels + Verified au lancement v3.0 : cible ≥ 20.
- Nombre de plugins Community 6 mois après v3.0 : cible ≥ 50.
- Taux de plugins avec ≥ 1 install actif 12 mois après publication : cible ≥ 60%.

**Fiabilité** :
- Taux de crash plugin propagé au core : cible **0%**.
- Temps médian de récupération après crash plugin : cible ≤ 5 s.
- Nombre de MàJ plugin réussies vs rollbacks : cible ≥ 95% réussies.

**Adoption** :
- Nombre médian de plugins installés par instance : cible ≥ 5 (au-delà des officiels bundle).
- Note moyenne des plugins Marketplace : cible ≥ 4.0/5.
- Nombre de développeurs actifs (≥ 1 commit / trimestre) : cible ≥ 30 à 12 mois.

---

## 11.13 ADR spécifiques

### ADR-15 — Tout est plugin sauf le noyau (Core & Plugins)

**Contexte** : évolution majeure de MG-VMS d'un monolithe vers une plateforme.
**Décision** : le noyau contient uniquement les fonctions inévitables (users, cameras, go2rtc, recorder, player, PTZ base, API, dashboard, plugin manager). Tout le reste — IA, ANPR, notifications, intégrations, storage non-local, modules métier — devient plugins avec cycle de vie indépendant.
**Conséquences** : refonte massive v3.0. Impact ~ 60% du code actuel devient plugins. Nécessite Plugin Manager complet + SDK + Marketplace. Augmente l'attractivité pour développeurs tiers.
**Alternatives rejetées** : rester monolithe (impasse produit), plugins optionnels périphériques (demi-mesure qui ne résout pas les limites cœur).

### ADR-16 — Interface `PlateRecognizer` uniforme quel que soit le moteur

**Contexte** : plusieurs moteurs ANPR possibles (fast-alpr, OpenALPR, PaddleOCR, Plate Recognizer cloud…) — chacun avec son propre format de sortie.
**Décision** : tous les plugins ANPR implémentent l'interface `PlateRecognizer` avec sortie JSON strictement normalisée (`text`, `confidence`, `country_hint`, `bbox_plate`, `engine`, `processing_ms`). Le reste du VMS ne connaît **jamais** le moteur utilisé.
**Conséquences** : ajout d'un moteur ANPR = un plugin, aucun changement core. Multi-ANPR simultané trivial (§11.6.1).
**Alternatives rejetées** : moteurs spécifiques hard-codés (extension impossible), format ouvert non-standardisé (chaos de compat).

### ADR-17 — Sandboxing selon la confiance du plugin

**Contexte** : équilibre entre performance et isolation.
**Décision** : plugins officiels → in-process (perf max). Plugins verified → sub-process (isolation crash). Plugins community non-vérifiés → container Docker (isolation OS complète). Config admin permet d'imposer un mode plus strict globalement.
**Conséquences** : 3 chemins de code à maintenir dans le Plugin Manager. Overhead runtime pour les modes sub-process/container (~5-10 ms IPC).
**Alternatives rejetées** : tout in-process (crash core = crash tout), tout container (over-engineered pour plugins officiels).

### ADR-18 — Manifest YAML au lieu de fichier Python

**Contexte** : format de déclaration des métadonnées plugin.
**Décision** : `manifest.yaml` static, parsable sans exécuter le code du plugin. Format `apiVersion: mgvms.io/v1` inspiré Kubernetes.
**Conséquences** : le Plugin Manager peut valider un plugin **avant** de l'exécuter. Analyse statique possible (marketplace, audit). Lecture humaine facile.
**Alternatives rejetées** : décorateur Python (`@mgvms.plugin(...)`) — force à exécuter le code, dangereux pour plugins non-vérifiés.

### ADR-19 — Namespace DB isolé par plugin

**Contexte** : gestion de la persistence des données plugin.
**Décision** : chaque plugin a un préfixe dédié dans MongoDB (`plugin_data.{plugin_name}`). Impossible d'accéder à un autre namespace. Migration cross-plugin passe par événements sur le bus.
**Conséquences** : nettoyage automatique à la désinstallation. Isolation de sécurité forte. Aucun risque de conflit de schéma entre plugins.
**Alternatives rejetées** : DB séparée par plugin (multiplie les instances Mongo), collection unique partagée (chaos, sécurité).

---

## 11.14 Écarts avec la v2.22.0

- 🔴 **Plugin Manager** — n'existe pas. À développer intégralement.
- 🔴 **SDK Python** — n'existe pas. À développer.
- 🔴 **Marketplace** — n'existe pas. Site web + API + review process à créer.
- 🔴 **Manifest YAML + loader** — n'existe pas.
- 🔴 **Sandboxing sub-process/container** — n'existe pas.
- 🔴 **Interfaces standardisées (FrameAnalyzer, PlateRecognizer…)** — à définir dans le SDK.
- ✅ **`ai_engine.py`** — code existant refactorable en plugins `yolo-detection` + `fast-alpr`.
- ✅ **Notifications** — code refactorable en plugins.
- ⚠ **Multi-ANPR** — code actuel a 1 seul moteur ANPR hard-codé.

C'est le chantier v3.0 le plus important en termes d'ampleur. La roadmap dédiée est détaillée dans le chapitre `26-roadmap.md`.

---

## Annexes

### A. Exemple complet — plugin `telegram-notifier`

```
mgvms-plugin-telegram-notifier/
├── manifest.yaml
├── plugin.py
├── config/schema.json
└── requirements.txt
```

**manifest.yaml** :
```yaml
apiVersion: mgvms.io/v1
kind: Plugin
metadata:
  name: telegram-notifier
  displayName: "Telegram Notifier"
  version: "1.0.0"
  author: "MG-VMS Team"
  license: "MIT"
  categories: ["notification", "integration"]
spec:
  runtime: python
  entrypoint: plugin.py
  interface: EventConsumer
  compatibility:
    mgvms_core: ">=3.0.0,<4.0.0"
  capabilities: [event.read, network.outbound]
  resources: {cpu_cores: 1, ram_mb: 128, gpu: none}
  config_schema: config/schema.json
```

**plugin.py** :
```python
from mgvms_sdk import EventConsumer, PluginContext, MGVMSEvent
import httpx

class TelegramNotifier(EventConsumer):
    async def on_load(self, ctx: PluginContext):
        self.bot_token = ctx.config["bot_token"]
        self.chat_id = ctx.config["chat_id"]
        self.client = httpx.AsyncClient(timeout=15)

    async def on_event(self, event: MGVMSEvent):
        if event.type not in ("alert.critical", "plate.blacklist"):
            return
        msg = f"🚨 {event.data.message}\nCaméra : {event.camera.name}"
        await self.client.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={"chat_id": self.chat_id, "text": msg},
        )

    async def on_unload(self):
        await self.client.aclose()
```

### B. Historique du chapitre

| Version | Date | Auteur | Changements |
|---|---|---|---|
| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale : vision plateforme · 10 interfaces standardisées · Plugin Manager · sandboxing 3 modes · Marketplace · SDK multi-langages · multi-ANPR · 5 ADR (15-19) · plan migration v2.22 → v3.0 |
