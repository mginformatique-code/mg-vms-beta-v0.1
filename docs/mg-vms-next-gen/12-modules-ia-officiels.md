# Chapitre 12 — Modules IA officiels (bundle v3.0)

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `11-plateforme-plugins` · `17-gpu-manager` · `20-diagnostics-intelligents`

Ce chapitre spécifie les plugins IA **officiels** livrés en bundle avec le core v3.0. Ces plugins sont installables/désinstallables comme n'importe quel plugin mais sont fournis, testés et supportés par l'équipe MG-VMS.

---

## 12.1 Liste bundle v3.0

| Nom | Version | Interface | GPU | Description courte |
|---|---|---|---|---|
| `yolo-detection` | 1.0 | FrameAnalyzer | Optionnel | Détection d'objets YOLOv11 (persons, véhicules, animaux, sac, etc.) |
| `fast-alpr` | 1.0 | PlateRecognizer | Non | ANPR CPU-ONNX (fast-alpr) |
| `zone-analytics` | 1.0 | FrameAnalyzer + ActionProvider | Non | CrossLine, Zone intrusion, Loitering, Counting |
| `smtp-notifier` | 1.0 | EventConsumer | Non | Envoi email |
| `discord-notifier` | 1.0 | EventConsumer | Non | Post webhook Discord |
| `telegram-notifier` | 1.0 | EventConsumer | Non | Post bot Telegram |

Périmètre bundle strict : ces 6 plugins couvrent 90% des usages courants. Les autres passent par Marketplace.

---

## 12.2 `yolo-detection`

### 12.2.1 Objectif
Détecter les objets (personnes, véhicules, animaux, sacs, etc.) dans chaque frame vidéo. Base de tous les scénarios IA supérieurs.

### 12.2.2 Config utilisateur (schema)

```json
{
  "model": {
    "type": "string",
    "enum": ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt", "yolo11l.pt"],
    "default": "yolo11n.pt"
  },
  "confidence": {"type": "number", "minimum": 0.1, "maximum": 0.99, "default": 0.35},
  "iou": {"type": "number", "minimum": 0.1, "maximum": 0.99, "default": 0.45},
  "classes_enabled": {
    "type": "array",
    "items": {"type": "string"},
    "default": ["person", "car", "truck", "motorcycle", "bicycle", "bus", "dog", "cat"]
  },
  "min_area_pct": {"type": "number", "minimum": 0, "maximum": 100, "default": 1.5,
                    "description": "Ignorer détections < X% du frame (anti-faux positifs)"}
}
```

### 12.2.3 Output

```json
{
  "detections": [
    {
      "label": "person",
      "label_fr": "Personne",
      "confidence": 0.87,
      "bbox": [x1, y1, x2, y2],
      "track_id": null  // ou UUID si plugin tracking installé
    }
  ],
  "timing_ms": 42,
  "device_used": "cuda:0"
}
```

### 12.2.4 Modes dégradés

- Pas de GPU → CPU (5-10× plus lent). Log warning au boot. Badge UI `CPU fallback`.
- Modèle introuvable → tentative re-download depuis registry. Si toujours KO → plugin en état `crashed` avec cause probable claire (chapitre 20).
- VRAM saturée → auto-downgrade au modèle plus léger (n < s < m). Notification admin.

### 12.2.5 Interactions

- Émet event `event.detected` sur le bus interne pour chaque détection.
- Consommé par : recorder (pour segments d'événement), plugin zone-analytics (pour cross-line), UI live overlays.

---

## 12.3 `fast-alpr`

### 12.3.1 Objectif

Lire les plaques d'immatriculation via fast-alpr (moteur CPU-ONNX open source, sans dépendance cloud).

### 12.3.2 Contrat `PlateRecognizer`

Voir chapitre 11 §11.3.2 pour le format de sortie normalisé.

### 12.3.3 Config

```json
{
  "detector_model": {"type": "string", "default": "yolo-v9-t-384-license-plate-end2end"},
  "ocr_model": {"type": "string", "default": "european-plates-mobile-vit-v2-model"},
  "min_confidence": {"type": "number", "default": 0.7},
  "country_hint": {"type": "string", "default": "fr", "enum": ["fr", "eu", "us", "gb"]},
  "cooldown_seconds": {"type": "integer", "default": 300,
                        "description": "Même plaque non déclenchée avant N secondes"}
}
```

### 12.3.4 Robustesse

- Modèles ONNX embarqués dans le plugin (~ 80 MB total). Pas de dépendance runtime supplémentaire.
- CPU-only : aucun impact GPU, cohabite librement avec `yolo-detection` sur même caméra.
- Émet `plate.detected` sur le bus. Corrélation blacklist/whitelist par le core (permet aux plugins d'obs de rester génériques).

---

## 12.4 `zone-analytics`

### 12.4.1 Objectif

Analytics vidéo classiques : ligne de comptage, zone d'intrusion, temps d'attente (loitering), comptage entrée/sortie.

### 12.4.2 Scénarios supportés

- **CrossLine** — franchissement d'une ligne virtuelle. Compteur A→B et B→A.
- **Zone Intrusion** — présence dans un polygone.
- **Loitering** — présence continue dans une zone > N secondes.
- **Counting** — cumul de comptages sur période.
- **Direction** — détection de sens (contresens).

### 12.4.3 Dépendance

Consomme les événements `event.detected` de `yolo-detection` (ou d'un autre FrameAnalyzer). Sans FrameAnalyzer, le plugin est inutile → manifest déclare `dependencies.plugins: {yolo-detection: ">=1.0"}` **soft** (fonctionne aussi avec `frigate-integration` v3.1+).

### 12.4.4 Config par scénario par caméra

Éditeur visuel dans l'UI caméra (drag&drop de ligne / polygone sur snapshot). Chaque scénario a :
- Nom.
- Classes détectées (person / car / truck / animal).
- Cooldown.
- Actions (trigger event `alert` avec sévérité, publier MQTT, etc.).
- Calendrier d'armement (permanent, jour, nuit, custom).

---

## 12.5 `smtp-notifier` / `discord-notifier` / `telegram-notifier`

### 12.5.1 Contrat commun `EventConsumer`

Chacun implémente :
```python
async def on_event(event: MGVMSEvent) -> ConsumerResult
```

### 12.5.2 Config commune

- **Filtres** : types d'événements consommés (`event.detected`, `plate.blacklist`, `alert.critical`, ...).
- **Cooldown** par cible (destinataire, chat, salon) pour éviter le spam.
- **Format message** — template Jinja2 configurable :
  ```
  🚨 {{ event.data.severity | upper }} sur {{ event.data.camera.name }}
  {{ event.data.message }}
  {% if event.data.thumbnail_url %}📷 {{ event.data.thumbnail_url }}{% endif %}
  ```

### 12.5.3 Différences par cible

- **SMTP** — sender + smtp host/port/user/password (chiffré Fernet), TLS/SSL, HTML supporté.
- **Discord** — webhook URL, embed avec image inline.
- **Telegram** — bot token + chat_id(s), envoi photo attaché possible.

### 12.5.4 Robustesse

- Retry backoff (3×) sur échec.
- Circuit breaker si > 5 échecs consécutifs sur un canal → circuit ouvert 5 min.
- Queue en cas de canal HS → livrées à la reconnexion (TTL 24h).
- Diagnostic UI : test envoi, historique livraisons OK/KO, taux de succès 7j.

---

## 12.6 Contract d'installation bundle

Les 6 plugins sont **pré-installés** mais **désactivés par défaut** au premier boot. Le Mode Installateur (chapitre 6) propose leur activation.

Un admin peut à tout moment :
- Désactiver un plugin bundle (ex. remplacer `fast-alpr` par `paddle-ocr` du Marketplace).
- Supprimer un plugin bundle (soft-delete + réinstallation possible depuis Marketplace).
- Mettre à jour un plugin bundle indépendamment du core.

---

## 12.7 Tests d'acceptation

- **TA-12.1** — YOLO détecte person + car sur frame test → événements bus émis.
- **TA-12.2** — fast-alpr détecte plaque sur frame test → format normalisé PlateResult.
- **TA-12.3** — zone-analytics avec CrossLine → compteur incrémenté sur franchissement.
- **TA-12.4** — smtp-notifier envoi test → OK avec MAIL sandbox.
- **TA-12.5** — Désinstallation `yolo-detection` → événement `plugin.uninstalled`, zone-analytics passe en warning "dépendance manquante".
- **TA-12.6** — Bench 20 caméras 1080p sur RTX A2000 → YOLO nano 20fps stable, ANPR CPU parallèle sans surcoût GPU.

---

## Annexes

### A. Historique

| v1.0 | 2026-07-24 | équipe MG-VMS | Rédaction initiale |
