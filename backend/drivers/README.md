# MG-VMS v0.4.6 · Camera Device Layer — Documentation

## Vision

Le code métier de MG-VMS **ne voit plus** de constructeur.
Il voit un **Device avec des capacités**.

```
                                    ┌──────────────────────────┐
Code métier (workflows, plugins,    │                          │
UI, routes API, alertes…)   ────────►  CameraDeviceService     │
                                    │                          │
                                    └────────────┬─────────────┘
                                                 │
                                    ┌────────────▼─────────────┐
                                    │   CameraDriver (ABC)     │
                                    │  · get_device_info       │
                                    │  · get_capabilities      │
                                    │  · get_status/streams    │
                                    │  · set_light/ir/siren    │
                                    │  · ptz_move/zoom/preset  │
                                    │  · start/stop_audio      │
                                    └───┬───────┬───────┬──────┘
                                        │       │       │
                          ┌─────────────┘  ┌────┴────┐  └──────────────┐
                          ▼                ▼         ▼                 ▼
                 ┌────────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
                 │  ONVIFDriver   │ │ Reolink    │ │  Dahua     │ │ Hikvision  │
                 │  (universel)   │ │ Driver     │ │  Driver    │ │  Driver    │
                 │                │ │ (étend     │ │  (étend    │ │  (étend    │
                 │  Profile S/T   │ │  ONVIF)    │ │  ONVIF)    │ │  ONVIF)    │
                 └────────────────┘ └────────────┘ └────────────┘ └────────────┘
```

## Contrat CameraDriver

Toute méthode publique de contrôle est **gardée par une capacité**.
Une commande dont la caméra ne supporte pas la fonction lève
`UnsupportedCapabilityError` **avant** tout appel réseau — jamais 500.

```python
from drivers import UnsupportedCapabilityError
try:
    await drv.set_siren(enabled=True, duration=10)
except UnsupportedCapabilityError as e:
    return e.to_dict()
    # → {"success": false, "error": "unsupported_capability",
    #    "message": "Cette caméra ne supporte pas la capacité 'siren'"}
```

## Registry & fallback

```python
from drivers import resolve_driver
d = resolve_driver(vendor="reolink", host="192.168.1.10", ...)   # ReolinkDriver
d = resolve_driver(vendor="brand-inconnu", host="...", ...)       # → ONVIFDriver (fallback)
```

Vendors reconnus : `onvif`, `generic`, `reolink`, `dahua`, `hikvision`.
Tout vendor absent bascule automatiquement sur `ONVIFDriver`.

## Modèle CameraCapabilities

Champs remontés par `probe()` :

| Catégorie | Champs |
|---|---|
| PTZ | `ptz` · `zoom` · `focus` |
| Audio | `audio_input` · `audio_output` · `microphone` · `speaker` · `two_way_audio` |
| Lumière | `spotlight` · `white_light` · `ir_control` · `ir_cut_filter` |
| Alarmes | `siren` · `alarm_output` |
| Capteurs | `pir_sensor` · `battery` |
| IA embarquée | `onboard_ai` · `onboard_ai_features` (tuple : person/vehicle/animal/face) |
| Protocoles | `onvif` · `isapi` · `cgi` · `reolink_api` |
| Vidéo | `max_resolution` (w,h) · `max_fps` |

Une Reolink RLC-823A remontera typiquement :
```json
{
  "ptz": true, "zoom": true, "focus": false,
  "spotlight": true, "white_light": false,
  "siren": true, "audio_input": true, "audio_output": true,
  "two_way_audio": true, "microphone": true, "speaker": true,
  "pir_sensor": false, "battery": false,
  "onboard_ai": true, "onboard_ai_features": ["person", "vehicle"],
  "onvif": true, "reolink_api": true,
  "max_resolution": [3840, 2160], "max_fps": 25
}
```

Une caméra Hikvision dôme fixe classique :
```json
{
  "ptz": false, "zoom": false, "spotlight": false, "siren": false,
  "ir_cut_filter": true, "ir_control": true,
  "onvif": true, "isapi": true, "white_light": false,
  "onboard_ai": false, "onboard_ai_features": []
}
```

## Endpoints API (`/api/devices/…`)

Tous les endpoints exigent une authentification et une permission
(`view_live` pour les GET, `manage_cameras` pour les POST).

| Méthode | Endpoint | Rôle |
|---|---|---|
| GET | `/api/devices/_supported` | Liste des vendors reconnus |
| GET | `/api/devices/{id}/info` | DeviceInfo (manufacturer, model, firmware, mac…) |
| GET | `/api/devices/{id}/capabilities` | CameraCapabilities |
| GET | `/api/devices/{id}/status` | DeviceStatus (online, battery, sd_card…) |
| GET | `/api/devices/{id}/streams` | Liste des sous-flux RTSP |
| POST | `/api/devices/{id}/discover` | Probe + persistance Mongo |
| POST | `/api/devices/{id}/light` | `{enabled, brightness?, mode?}` |
| POST | `/api/devices/{id}/ir` | `{mode: auto\|on\|off}` |
| POST | `/api/devices/{id}/siren` | `{enabled, duration?}` |
| POST | `/api/devices/{id}/audio/start` \| `/stop` | Sortie audio |
| POST | `/api/devices/{id}/ptz/move` | `{direction, speed?}` |
| POST | `/api/devices/{id}/ptz/zoom` | `{value: -1.0…1.0}` |
| POST | `/api/devices/{id}/ptz/preset` | `{id}` |

### Mapping erreur → HTTP

| `error.code` | HTTP | Signification |
|---|---:|---|
| `unsupported_capability` | 400 | La caméra ne supporte pas cette fonction |
| `camera_missing_ip` | 400 | Caméra sans IP configurée |
| `authentication_failed` | 401 | Identifiants rejetés |
| `camera_not_found` | 404 | ID caméra inconnu |
| `device_unreachable` | 503 | Timeout / connect refusé |
| `command_timeout` | 503 | Commande émise sans réponse |

**Jamais 500.**

## Persistance MongoDB

`POST /api/devices/{id}/discover` écrit dans `db.cameras[{id}]` :

```json
{
  "id": "<camera_id>",
  "driver": "reolink",
  "device_info": { "manufacturer": "Reolink", "model": "RLC-823A", ... },
  "capabilities": { "ptz": true, "spotlight": true, ... },
  "streams_detected": [{ "name": "main", "url": "rtsp://...", ... }, ...]
}
```

L'UI consomme `capabilities` pour n'afficher que les widgets pertinents
(pas de bouton sirène si `capabilities.siren=false`).

## Ordre d'implémentation constructeur

| Driver | État v0.4.6 | Fonctions couvertes |
|---|---|---|
| **ONVIFDriver** | ✅ complet | connect, info, caps (PTZ+IR), streams, PTZ (move/zoom/preset), IR cut filter |
| **ReolinkDriver** | ✅ complet | +GetAbility (spotlight/siren/PIR/battery/AI), SetWhiteLed, AudioAlarmPlay, SetIrLights, GetBatteryInfo, GetHddInfo |
| **DahuaDriver** | 🟡 minimal | Hérite ONVIF · CGI `Lighting_V2` (white light) · sirène/audio à venir v0.4.7 |
| **HikvisionDriver** | 🟡 minimal | Hérite ONVIF · ISAPI `supplementLight` détecté · sirène/audio à venir v0.4.7 |
| **AxisDriver** | ⚪ à créer | VAPIX prévu v0.4.7 |
| **HanwhaDriver** | ⚪ à créer | Sunapi prévu v0.4.7 |
| **UniviewDriver** | ⚪ à créer | LAPI prévu v0.4.7 |

## Extension : ajouter un nouveau driver constructeur

```python
# backend/drivers/nouveau_driver.py
from .onvif_driver import ONVIFDriver
from .registry import register_driver

class NouveauDriver(ONVIFDriver):
    vendor = "nouveau"

    async def _set_siren(self, enabled, duration):
        # Appel API constructeur ici
        ...

register_driver("nouveau", NouveauDriver)
```

Puis ajouter l'import dans `drivers/__init__.py`. La caméra sera
utilisable immédiatement dès qu'un enregistrement `db.cameras.vendor == "nouveau"`
existe.
