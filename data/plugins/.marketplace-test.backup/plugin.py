"""Plugin marketplace-test — implémentation minimaliste FrameAnalyzer."""
from plugin_manager.interfaces import FrameAnalyzer, Frame, Detection


class MarketplaceTestPlugin(FrameAnalyzer):
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
