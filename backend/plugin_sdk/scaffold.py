"""MG-VMS Plugin Scaffolder — génère un plugin skeleton prêt à éditer.

Usage :
    python -m plugin_sdk.scaffold my-plugin --interface FrameAnalyzer --category detection

Interfaces supportées :
    FrameAnalyzer, PlateRecognizer, Tracker, Segmenter, PipelineConsumer, EventConsumer

Produit :
    my-plugin/
    ├── manifest.yaml
    ├── plugin.py
    ├── config/schema.json
    └── README.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

INTERFACES = {
    "FrameAnalyzer":     ("FrameAnalyzer",     "detection"),
    "PlateRecognizer":   ("PlateRecognizer",   "anpr"),
    "Tracker":           ("Tracker",           "tracking"),
    "Segmenter":         ("Segmenter",         "segmentation"),
    "PipelineConsumer":  ("PipelineConsumer",  "business"),
    "EventConsumer":     ("EventConsumer",     "notification"),
}

MANIFEST_TMPL = """apiVersion: mgvms.io/v1
kind: Plugin
metadata:
  name: {slug}
  displayName: "{display}"
  version: "0.1.0"
  description: "Plugin {interface} — description à compléter."
  author: "Votre nom"
  license: "MIT"
  categories: [{category}]
spec:
  runtime: python
  entrypoint: plugin.py
  className: {classname}
  interface: {interface}
  compatibility: {{mgvms_core: ">=2.30.0,<4.0.0"}}
  capabilities: [camera.frame.read, event.write]
  resources: {{cpu_cores: 0.5, ram_mb: 128, gpu: none, disk_mb: 20}}
  config_schema: config/schema.json
  bus:
    order: 100
"""

PLUGIN_TMPL = {
    "FrameAnalyzer": '''"""Plugin {slug} — implémentation minimaliste FrameAnalyzer."""
from plugin_manager.interfaces import FrameAnalyzer, Frame, Detection


class {classname}(FrameAnalyzer):
    """Détecteur d'objets custom — remplacez le corps de `analyze()`."""

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        # Ex : charger un modèle ONNX/PyTorch/... depuis ctx.config
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        # Appelé quand l'utilisateur modifie la config depuis l'UI
        pass

    async def analyze(self, frame: Frame, camera_config: dict | None = None) -> list[Detection]:
        # TODO : implémentez votre détection ici
        # Retournez une liste de Detection(label=..., bbox=..., confidence=...)
        return []
''',
    "PlateRecognizer": '''"""Plugin {slug} — implémentation minimaliste PlateRecognizer."""
from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult


class {classname}(PlateRecognizer):
    """Reconnaissance de plaques custom — remplacez le corps de `recognize()`."""

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        pass

    async def recognize(self, frame: Frame, vehicle_bbox: tuple | None = None) -> list[PlateResult]:
        # TODO : implémentez votre OCR / API cloud ici
        return []
''',
    "Tracker": '''"""Plugin {slug} — implémentation minimaliste Tracker."""
from plugin_manager.interfaces import Tracker, Frame, Detection


class {classname}(Tracker):
    """Suivi multi-objets custom — remplacez le corps de `update()`."""

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        pass

    async def update(self, frame: Frame, detections: list[Detection]) -> list[Detection]:
        # TODO : assignez des `track_id` stables aux détections
        return detections
''',
    "Segmenter": '''"""Plugin {slug} — implémentation minimaliste Segmenter."""
from plugin_manager.interfaces import Segmenter, Frame, Detection


class {classname}(Segmenter):
    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        pass

    async def segment(self, frame: Frame, detections: list[Detection]) -> list[Detection]:
        # TODO : ajoutez un `mask` numpy à chaque détection
        return detections
''',
    "PipelineConsumer": '''"""Plugin {slug} — logique métier PipelineConsumer."""
from plugin_manager.interfaces import PipelineConsumer, PipelineResult


class {classname}(PipelineConsumer):
    """Consomme le résultat pipeline complet (détections + tracks + segments)."""

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        pass

    async def consume(self, result: PipelineResult) -> None:
        # TODO : compter, alerter, notifier, écrire en base…
        pass
''',
    "EventConsumer": '''"""Plugin {slug} — EventConsumer (notifier custom)."""
from plugin_manager.interfaces import EventConsumer, MGVMSEvent


class {classname}(EventConsumer):
    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        pass

    async def on_event(self, event: MGVMSEvent) -> None:
        # TODO : envoyer l'événement vers votre canal (webhook, mail, SMS…)
        pass
''',
}

SCHEMA_TMPL = {
    "type": "object",
    "title": "{title}",
    "properties": {
        "enabled": {
            "type": "boolean",
            "title": "Actif",
            "default": True,
        }
    },
    "required": [],
}

README_TMPL = """# {display}

Plugin **{interface}** pour MG-VMS.

## Installation

```bash
cp -r {slug} /app/data/plugins/
sudo supervisorctl restart backend
```

## Configuration

Éditez `config/schema.json` pour déclarer les champs configurables par
l'utilisateur (le formulaire est généré automatiquement par l'UI Plugin Manager).

## Développement

Ouvrez `plugin.py` et implémentez la méthode principale de votre interface.
"""


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\-]+", "-", name.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "my-plugin"


def _classname(slug: str) -> str:
    return "".join(w.capitalize() for w in slug.split("-")) + "Plugin"


def scaffold(name: str, interface: str, category: str | None = None,
             out_dir: Path | None = None) -> Path:
    """Génère un skeleton plugin. Retourne le chemin du dossier créé."""
    if interface not in INTERFACES:
        raise ValueError(f"Interface inconnue: {interface}. Choix: {', '.join(INTERFACES)}")
    slug = _slugify(name)
    display = name if name != slug else slug.replace("-", " ").title()
    classname = _classname(slug)
    default_category = INTERFACES[interface][1]
    category = category or default_category

    root = (out_dir or Path.cwd()) / slug
    if root.exists():
        raise FileExistsError(f"Le dossier '{root}' existe déjà")
    root.mkdir(parents=True)
    (root / "config").mkdir()

    # manifest.yaml
    (root / "manifest.yaml").write_text(
        MANIFEST_TMPL.format(slug=slug, display=display, category=category,
                              classname=classname, interface=interface),
        encoding="utf-8",
    )

    # plugin.py
    (root / "plugin.py").write_text(
        PLUGIN_TMPL[interface].format(slug=slug, classname=classname),
        encoding="utf-8",
    )

    # config/schema.json
    schema = dict(SCHEMA_TMPL)
    schema["title"] = display
    (root / "config" / "schema.json").write_text(
        json.dumps(schema, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # README.md
    (root / "README.md").write_text(
        README_TMPL.format(display=display, interface=interface, slug=slug),
        encoding="utf-8",
    )

    return root


def _main():
    parser = argparse.ArgumentParser(description="Scaffold un plugin MG-VMS.")
    parser.add_argument("name", help="Nom du plugin (ex: cool-detector)")
    parser.add_argument("--interface", required=True, choices=list(INTERFACES),
                        help="Interface implémentée")
    parser.add_argument("--category", default=None,
                        help="Catégorie (défaut selon interface)")
    parser.add_argument("--out", default=".", help="Dossier de sortie (défaut: courant)")
    args = parser.parse_args()

    try:
        path = scaffold(args.name, args.interface, args.category, Path(args.out))
    except (ValueError, FileExistsError) as e:
        print(f"ERREUR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ Plugin scaffoldé dans {path}")
    print("Étapes suivantes :")
    print(f"  1. Édite {path}/plugin.py — implémente la méthode principale")
    print(f"  2. Édite {path}/config/schema.json — ajoute les champs de config")
    print(f"  3. cp -r {path} /app/data/plugins/ && sudo supervisorctl restart backend")


if __name__ == "__main__":
    _main()
