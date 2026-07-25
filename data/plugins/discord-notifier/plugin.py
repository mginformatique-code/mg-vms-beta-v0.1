"""Plugin EventConsumer — Discord webhook."""
from __future__ import annotations
from plugin_manager.interfaces import EventConsumer, MGVMSEvent, ConsumerResult


class DiscordNotifierPlugin(EventConsumer):
    name = "discord-notifier"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._client = None
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        if not cfg.get("webhook_url"):
            self._ctx.set_state("not_configured", "webhook_url manquant")
            return
        try:
            import httpx  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install httpx")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    async def on_event(self, event: MGVMSEvent) -> ConsumerResult:
        import httpx
        cfg = self._ctx.config or {}
        filters = cfg.get("event_types") or []
        if filters and event.type not in filters:
            return ConsumerResult(handled=False)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10)
        try:
            data = event.data or {}
            msg = f"**{event.type}** · Caméra `{event.camera_id or '?'}`\n> {data.get('message', '')}"
            r = await self._client.post(cfg["webhook_url"], json={
                "content": msg[:1900],
                "username": cfg.get("username", "MG-VMS"),
            })
            r.raise_for_status()
            return ConsumerResult(handled=True)
        except Exception as e:
            return ConsumerResult(handled=False, error=str(e))

    async def on_unload(self) -> None:
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
