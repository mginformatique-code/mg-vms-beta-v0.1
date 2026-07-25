"""Plugin EventConsumer — Telegram Bot."""
from __future__ import annotations
from plugin_manager.interfaces import EventConsumer, MGVMSEvent, ConsumerResult


class TelegramNotifierPlugin(EventConsumer):
    name = "telegram-notifier"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._client = None
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        if not cfg.get("bot_token") or not cfg.get("chat_id"):
            self._ctx.set_state("not_configured", "bot_token et chat_id requis")
            return
        try:
            import httpx  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install httpx")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
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
            msg = f"🚨 {event.type}\nCaméra: {event.camera_id or '?'}\n{data.get('message', '')}"
            r = await self._client.post(
                f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                json={"chat_id": cfg["chat_id"], "text": msg[:4000]},
            )
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
