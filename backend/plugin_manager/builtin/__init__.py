"""Plugins « builtin » — wrappers PoC v2.30 (bundle officiel).

Ces classes exposent le code existant (`ai_engine`) sous forme de plugins
conformes aux interfaces `FrameAnalyzer` / `PlateRecognizer` (§11.10.1 -
composants à externaliser). Elles permettent de faire fonctionner le bus
multi-plugin dès aujourd'hui sans réécrire l'IA.

En v3.0 : ces wrappers seront remplacés par des vrais plugins isolés dans
`/data/plugins/yolo-detection/` et `/data/plugins/fast-alpr/` avec manifest
YAML.
"""
from .yolo_wrapper import YoloDetectionPlugin
from .alpr_wrapper import FastAlprPlugin
from .mock_plate import MockPlatePlugin, MOCK_PLATE_TEXT

__all__ = [
    "YoloDetectionPlugin",
    "FastAlprPlugin",
    "MockPlatePlugin",
    "MOCK_PLATE_TEXT",
]
