"""Plugin EventConsumer — SMTP Email."""
from __future__ import annotations
import asyncio
import smtplib
from email.mime.text import MIMEText
from plugin_manager.interfaces import EventConsumer, MGVMSEvent, ConsumerResult


class SmtpNotifierPlugin(EventConsumer):
    name = "smtp-notifier"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._evaluate_state()

    def _evaluate_state(self):
        cfg = self._ctx.config or {}
        required = ["smtp_host", "smtp_port", "from_email", "to_emails"]
        missing = [k for k in required if not cfg.get(k)]
        if missing:
            self._ctx.set_state("not_configured", f"Champs requis manquants : {', '.join(missing)}")
            return
        self._ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._evaluate_state()

    def _send_sync(self, cfg: dict, subject: str, body: str):
        """SMTP est bloquant → run dans un thread."""
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = cfg["from_email"]
        msg["To"] = ", ".join(cfg["to_emails"])
        server = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=15)
        try:
            if cfg.get("use_tls", True):
                server.starttls()
            if cfg.get("username"):
                server.login(cfg["username"], cfg.get("password", ""))
            server.sendmail(cfg["from_email"], cfg["to_emails"], msg.as_string())
        finally:
            server.quit()

    async def on_event(self, event: MGVMSEvent) -> ConsumerResult:
        cfg = self._ctx.config or {}
        filters = cfg.get("event_types") or []
        if filters and event.type not in filters:
            return ConsumerResult(handled=False)
        try:
            data = event.data or {}
            subject = f"[MG-VMS] {event.type} · {event.camera_id or 'system'}"
            body = f"Événement : {event.type}\nCaméra : {event.camera_id}\nTimestamp : {event.timestamp}\n\n{data.get('message', '')}\n\nDonnées: {data}"
            await asyncio.get_event_loop().run_in_executor(None, self._send_sync, cfg, subject, body)
            return ConsumerResult(handled=True)
        except Exception as e:
            return ConsumerResult(handled=False, error=str(e))

    async def on_unload(self) -> None:
        pass
