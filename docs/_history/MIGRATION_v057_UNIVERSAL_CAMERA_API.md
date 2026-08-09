# MG-VMS v0.5.7 — Universal Camera API · Plan de migration

**Date** : Février 2026
**Auteur** : Fork agent E1
**Statut** : Phase 1 (consolidation d'interfaces) — en cours

---

## 1. Contexte

MG-VMS v0.4.6 a déjà introduit un **Camera Device Layer** complet et
opérationnel :

```
backend/drivers/                    · implémentations concrètes
    __init__.py                      · façade + registration side-effect
    camera_driver.py                 · CameraDriver (ABC)
    camera_models.py                 · CameraCapabilities, DeviceInfo, StreamInfo, DeviceStatus, IRMode, LightMode
    exceptions.py                    · CameraDriverError + sous-classes
    registry.py                      · register_driver / get_driver / resolve_driver / list_supported_vendors
    onvif_driver.py                  · ONVIF Profile S/T (universel)
    reolink_driver.py                · Reolink JSON API
    hikvision_driver.py              · ISAPI
    dahua_driver.py                  · CGI
backend/services/
    camera_device_service.py         · orchestrateur singleton (cache, connect, persist)
backend/routes/
    devices.py                       · /api/devices/{id}/*  (info, capabilities, status, streams,
                                       discover, light, ir, siren, audio, ptz)
```

En parallèle, un nouveau fichier `backend/pipeline_v2/camera_driver.py`
(241 lignes) proposait une architecture concurrente basée sur
`typing.Protocol` + `Capabilities` (~40 flags) + un second `DriverRegistry`.

**Décision utilisateur (option C — migration propre) :**

> « Faire évoluer MG-VMS vers une API universelle multi-caméras
> sans casser l'existant. Aucune régression. Aucune duplication.
> Aucune seconde pile de drivers. »

## 2. Tableau de migration

| Composant actuel                              | Action                         | Décision |
| --------------------------------------------- | ------------------------------ | -------- |
| `backend/drivers/`                            | Conservé — source unique       | ✅ |
| `backend/services/camera_device_service.py`   | Conservé et enrichi            | ✅ |
| `backend/drivers/registry.py`                 | Fusionné (unique)              | ✅ |
| `backend/pipeline_v2/camera_driver.py`        | **Réécrit** comme contrat pur (re-export + Protocol) | ✅ |
| `backend/pipeline_v2/camera_manager.py`       | **Créé** — orchestration légère, délègue au service | ✅ |
| `backend/routes/devices.py` (`/api/devices/*`) | Inchangé                       | ✅ |
| Frontend Camera Center / Pipeline Center      | Inchangé                       | ✅ |

## 3. Architecture cible

```
                    Applicatif (workflows, plugins, UI, routes)
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │      CameraManager (nouveau)  │
                    │   - lifecycle & cache         │
                    │   - résolution driver         │
                    │   - fallback + validation     │
                    │   AUCUNE commande métier      │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  CameraDeviceService (existant)│
                    │  - get_driver(cam_id)          │
                    │  - discover(cam_id)            │
                    │  - persist capabilities Mongo  │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │   CameraDriver Protocol        │
                    │   (contrat, aucune logique)    │
                    └───────────────┬───────────────┘
                                    │
        ┌─────────┬─────────┬───────┼───────┬─────────┬─────────┐
        ▼         ▼         ▼       ▼       ▼         ▼         ▼
      ONVIF   Reolink   Hikvision  Dahua   Axis    Hanwha    …
     (existant)(existant)(existant)(existant)(futur)(futur)   …
```

## 4. Contrat unique

**Un seul contrat** : `backend/drivers.CameraDriver` (ABC, déjà existant).

`backend/pipeline_v2/camera_driver.py` **ré-exporte** ce contrat +
ajoute une facette `Protocol` (`CameraDriverProtocol`, `runtime_checkable`)
pour du typing structural moderne — mais toute la logique reste dans
`backend/drivers/`.

**Règle d'usage** :

```python
# ✅ CORRECT — via la façade pipeline_v2 (contrat)
from pipeline_v2.camera_driver import (
    CameraDriver, CameraCapabilities, DeviceInfo, IRMode, LightMode,
    UnsupportedCapabilityError,
)

# ✅ ÉGALEMENT CORRECT — via drivers/ directement (implémentation)
from drivers import CameraDriver, CameraCapabilities

# ❌ INTERDIT — aucun consommateur ne doit importer un driver concret
from drivers.reolink_driver import ReolinkDriver   # non
```

Les deux imports pointent vers les **mêmes objets** (identité `is`).
Il n'existe **pas** deux `CameraCapabilities` ni deux `CameraDriver`.

## 5. Capabilities enrichi (backward-compatible)

Le dataclass `CameraCapabilities` (dans `backend/drivers/camera_models.py`)
est étendu avec de nouveaux flags, tous en **valeurs par défaut** — aucun
consommateur existant n'est cassé :

| Nouveau flag       | Type | Défaut | Description                             |
| ------------------ | ---- | ------ | --------------------------------------- |
| `multi_stream`     | bool | False  | Deux profils vidéo (main + sub)          |
| `codec_h265`       | bool | False  | Encodage H.265 supporté                  |
| `talkback`         | bool | False  | Alias sémantique de `two_way_audio`     |
| `flash`            | bool | False  | Flash / stroboscope                     |
| `ai_person`        | bool | False  | Détection personne embarquée            |
| `ai_vehicle`       | bool | False  | Détection véhicule embarquée            |
| `ai_animal`        | bool | False  | Détection animal                        |
| `ai_face`          | bool | False  | Détection visage                        |
| `ai_helmet`        | bool | False  | Détection casque                        |
| `ai_anpr`          | bool | False  | ANPR / LPR embarqué                     |
| `ai_line_crossing` | bool | False  | Franchissement de ligne                 |
| `ai_intrusion`     | bool | False  | Détection intrusion (zone virtuelle)    |
| `thermal`          | bool | False  | Capteur thermique                       |
| `radar`            | bool | False  | Radar (Bosch, Axis)                     |
| `relay`            | bool | False  | Sortie relais                           |
| `digital_io`       | bool | False  | Entrées/sorties numériques              |
| `wifi`             | bool | False  | Connexion Wi-Fi                         |
| `poe`              | bool | False  | Alimentation PoE                        |
| `sdcard`           | bool | False  | Emplacement SD interne                  |
| `ftp`              | bool | False  | Upload FTP intégré                      |
| `smtp`             | bool | False  | Alerte email SMTP intégrée              |
| `https`            | bool | False  | Interface web HTTPS                     |

Les flags historiques (`ptz`, `zoom`, `spotlight`, `siren`, `battery`,
`pir_sensor`, `onboard_ai`, `onboard_ai_features` …) restent inchangés.
Les drivers concrets remontent les nouveaux flags **au fur et à mesure** —
un `False` par défaut est sémantiquement identique à « inconnu ou non
détecté », donc aucune régression.

## 6. CameraManager — nouveau, mais restreint

`backend/pipeline_v2/camera_manager.py` — **façade légère** dont le seul
rôle est :

- résoudre `camera_id → driver` via le service ;
- garder un cache mémoire ;
- valider (IP + credentials présents) ;
- fournir un point d'entrée unifié pour le futur Driver Validator ;
- exposer la liste des vendors supportés.

**Ce qu'il ne fait pas** (et ne fera jamais) :

- ❌ pas d'appel HTTP direct à une caméra ;
- ❌ pas de logique constructeur ;
- ❌ pas de commande métier (`snapshot`, `ptz_move`, `set_light`, …).

Toutes les commandes physiques restent dans les drivers et sont exposées
par `CameraDeviceService`.

## 7. Compatibilité

- Les routes `/api/devices/*` sont **inchangées**.
- Les tests existants (`tests/test_camera_drivers.py`, 22 tests) doivent
  continuer à passer sans modification.
- Le frontend (Camera Center, Pipeline Center, Discovery, RBAC, …) n'est
  pas touché.

## 8. Critères de validation Phase 1

- [x] Document de migration livré (ce fichier).
- [ ] `pipeline_v2/camera_driver.py` est un contrat pur (re-export + Protocol).
- [ ] `pipeline_v2/camera_manager.py` créé (délégation stricte).
- [ ] `drivers/camera_models.CameraCapabilities` enrichi (nouveaux flags, défauts).
- [ ] Test suite `test_camera_drivers.py` (22 tests) 100 % vert.
- [ ] Nouveau test suite `test_v057_universal_api.py` (couverture du contrat + manager).
- [ ] Aucune modification des routes `/api/devices/*`.
- [ ] Aucune modification du frontend.

## 9. Phases suivantes (hors Phase 1)

- **Phase 2** : Nouveaux drivers (Axis, Hanwha, Uniview, Bosch, Sony,
  Milesight, Avigilon, Vivotek). Toujours en `backend/drivers/*`.
- **Phase 3** : `GET /api/devices/{id}/validate` — Driver Validator
  automatique (probe des capacités déclarées + benchmark).
- **Phase 4** : Frontend Camera Center rendu 100 % par `capabilities` —
  suppression de tout `if brand == "Reolink"`.
- **Phase 5** : Operations Center (CPU/GPU/RAM/VRAM, Mongo, go2rtc,
  dropped frames).

## 10. Traçabilité des changements

Toute modification de code Phase 1 est étiquetée dans le message de
commit / le commentaire d'entête `v0.5.7 · Phase 1`.
