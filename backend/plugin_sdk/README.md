# MG-VMS Plugin SDK

Le SDK MG-VMS permet à quiconque de développer des **plugins** pour la plateforme
sans forker le core. Un plugin est un dossier auto-contenu qui déclare un
**manifest**, un **schéma de configuration** et une **implémentation Python**
héritant de l'une des interfaces du Plugin Manager.

## Créer un nouveau plugin

```bash
python -m plugin_sdk.scaffold my-plugin --interface FrameAnalyzer --category detection
```

Un dossier `my-plugin/` est créé avec :

```
my-plugin/
├── manifest.yaml       # méta-données + capabilities + resources
├── plugin.py           # implémentation Python
├── config/
│   └── schema.json     # JSON Schema pour l'UI de config
└── README.md
```

## Publier localement

Déposez le dossier dans `/app/data/plugins/` et redémarrez le backend :

```bash
cp -r my-plugin /app/data/plugins/
sudo supervisorctl restart backend
```

Le loader dynamique le découvrira automatiquement à travers le manifest.

## Publier sur le Marketplace

Le Marketplace MG-VMS scanne `/app/data/plugins/` **et** un registre externe
publique (roadmap P14). Pour publier :

1. Empaquetez votre plugin : `python -m plugin_sdk.pack my-plugin/`
   → produit `my-plugin-1.0.0.mgpkg` (tar.gz contenant le dossier).
2. (Roadmap) Uploadez sur `https://marketplace.mg-vms.io` — signature GPG requise.

## Interfaces disponibles

| Interface       | Rôle                                                        |
|-----------------|-------------------------------------------------------------|
| `FrameAnalyzer` | Détecteur (YOLO, RT-DETR, EfficientDet…)                    |
| `PlateRecognizer` | ANPR (fast-alpr, cloud, OCR custom)                      |
| `Tracker`       | Suivi multi-objets (ByteTrack, BoTSORT…)                    |
| `Segmenter`     | Segmentation instance (SAM2, Mask R-CNN…)                   |
| `PipelineConsumer` | Logique métier (comptage, occupation, PPE, incidents)   |
| `EventConsumer` | Notifiers (Telegram, Discord, SMTP, MQTT, webhooks)         |

## Contexte plugin (`ctx`)

Chaque plugin reçoit un objet `ctx` fourni par le core :

```python
ctx.config         # dict — config utilisateur (secrets déjà déchiffrés)
ctx.set_state(state, message=None)   # state ∈ {ready, not_configured, missing_dependency, error, disabled}
ctx.log.info(...) # logger dédié préfixé [nom-du-plugin]
```

## Sandbox (P2)

Le bus applique automatiquement :
- **Timeout** par appel (défaut 5s)
- **Capture d'exception** (un crash plugin ne tue jamais le pipeline)
- **Quarantine auto** après 5 échecs consécutifs → plugin exclu du dispatch
  jusqu'à réactivation manuelle via `POST /api/plugins/bus/{name}/unquarantine`

## Compatibilité

Le manifest déclare `compatibility.mgvms_core` (semver range). Le loader
refuse de charger un plugin incompatible avec la version courante du core.
