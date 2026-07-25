"""PluginBus — dispatcher de frames vers N plugins actifs (chapitre 11 §11.4.1).

Le PluginBus est le composant qui matérialise le pattern « fan-out » cœur du
Plugin Manager : quand le core reçoit une frame, il ne connaît pas
l'implémentation individuelle des plugins IA — il délègue au bus qui invoque
en parallèle tous les plugins actifs implémentant l'interface demandée.

Garanties :

  1. **Isolation crash** : un plugin qui lève une exception est capturé,
     journalisé, et son compteur d'erreurs incrémenté. Les autres plugins
     continuent (`asyncio.gather(return_exceptions=True)`).
  2. **Timeout par plugin** : chaque appel est borné (`asyncio.wait_for`) pour
     qu'un plugin bloquant ne gèle jamais le pipeline vidéo.
  3. **Ordre préservé** : la liste des résultats respecte l'ordre
     d'enregistrement, ce qui rend le mode `cascade` déterministe.
  4. **Métriques** : chaque appel maintient un compteur (`calls`, `errors`,
     `timeouts`, `last_ms`) exploité par l'UI Plugin Manager.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .interfaces import FrameAnalyzer, PlateRecognizer, EventConsumer, Frame, MGVMSEvent

logger = logging.getLogger("plugin_bus")


@dataclass
class BusEntry:
    """Instance runtime d'un plugin enregistré sur le bus."""
    name: str
    interface: str  # "FrameAnalyzer" | "PlateRecognizer" | "EventConsumer"
    instance: object
    enabled: bool = True
    order: int = 100  # priorité (plus petit = plus prioritaire pour cascade)
    calls: int = 0
    errors: int = 0
    timeouts: int = 0
    last_ms: float = 0.0
    last_error: Optional[str] = None

    def summary(self) -> dict:
        return {
            "name": self.name,
            "interface": self.interface,
            "enabled": self.enabled,
            "order": self.order,
            "calls": self.calls,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "last_ms": round(self.last_ms, 2),
            "last_error": self.last_error,
        }


class PluginBus:
    """Bus événementiel du Plugin Manager (PoC in-memory v2.30)."""

    def __init__(self, default_timeout_s: float = 5.0):
        self._entries: dict[str, BusEntry] = {}
        self.default_timeout_s = default_timeout_s

    # ── Enregistrement / suppression ────────────────────────────────────

    def register(self, name: str, instance, *, order: int = 100) -> BusEntry:
        """Enregistre une instance de plugin sur le bus.

        Détecte automatiquement l'interface via `isinstance`. Le même `name`
        remplace l'ancienne entrée (upgrade à chaud).
        """
        if isinstance(instance, PlateRecognizer):
            iface = "PlateRecognizer"
        elif isinstance(instance, FrameAnalyzer):
            iface = "FrameAnalyzer"
        elif isinstance(instance, EventConsumer):
            iface = "EventConsumer"
        else:
            raise TypeError(f"{name!r} n'implémente aucune interface plugin valide")

        entry = BusEntry(name=name, interface=iface, instance=instance, order=order)
        self._entries[name] = entry
        logger.info("plugin_bus.register name=%s interface=%s order=%s", name, iface, order)
        return entry

    def unregister(self, name: str) -> bool:
        return self._entries.pop(name, None) is not None

    def set_enabled(self, name: str, enabled: bool) -> bool:
        entry = self._entries.get(name)
        if not entry:
            return False
        entry.enabled = enabled
        return True

    # ── Sélection ───────────────────────────────────────────────────────

    def list_entries(self, interface: Optional[str] = None) -> list[BusEntry]:
        entries = list(self._entries.values())
        if interface:
            entries = [e for e in entries if e.interface == interface]
        entries.sort(key=lambda e: (e.order, e.name))
        return entries

    def active(self, interface: str) -> list[BusEntry]:
        return [e for e in self.list_entries(interface) if e.enabled]

    def summary(self) -> list[dict]:
        return [e.summary() for e in self.list_entries()]

    # ── Dispatch ────────────────────────────────────────────────────────

    async def _call_one(
        self,
        entry: BusEntry,
        coro_factory,
        timeout_s: Optional[float] = None,
    ):
        """Exécute une coroutine plugin avec timeout + capture d'erreur."""
        entry.calls += 1
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                coro_factory(entry.instance),
                timeout=timeout_s or self.default_timeout_s,
            )
            entry.last_ms = (time.perf_counter() - t0) * 1000
            entry.last_error = None
            return result
        except asyncio.TimeoutError:
            entry.timeouts += 1
            entry.errors += 1
            entry.last_ms = (time.perf_counter() - t0) * 1000
            entry.last_error = "timeout"
            logger.warning("plugin_bus.timeout name=%s after=%.1fms", entry.name, entry.last_ms)
            return None
        except Exception as e:  # pragma: no cover — isolation crash volontaire
            entry.errors += 1
            entry.last_ms = (time.perf_counter() - t0) * 1000
            entry.last_error = f"{type(e).__name__}: {e}"[:200]
            logger.warning("plugin_bus.error name=%s err=%s", entry.name, entry.last_error)
            return None

    async def dispatch_frame(
        self,
        frame: Frame,
        camera_config: Optional[dict] = None,
        timeout_s: Optional[float] = None,
    ) -> list[tuple[str, object]]:
        """Fan-out sur tous les `FrameAnalyzer` actifs.

        Retourne `[(plugin_name, AnalysisResult|None), ...]` dans l'ordre
        d'enregistrement (déterministe pour cascade).
        """
        entries = self.active("FrameAnalyzer")
        if not entries:
            return []
        cfg = camera_config or {}
        results = await asyncio.gather(
            *[self._call_one(e, lambda inst, f=frame, c=cfg: inst.analyze(f, c), timeout_s)
              for e in entries],
            return_exceptions=False,
        )
        return [(e.name, r) for e, r in zip(entries, results)]

    async def dispatch_plate(
        self,
        frame: Frame,
        vehicle_bbox: Optional[tuple] = None,
        timeout_s: Optional[float] = None,
        *,
        cascade_stop_at: Optional[float] = None,
    ) -> list[tuple[str, list]]:
        """Fan-out sur tous les `PlateRecognizer` actifs.

        Si `cascade_stop_at` est fourni : arrête dès qu'un moteur retourne un
        résultat avec `confidence >= cascade_stop_at` (mode économie
        cloud/quota). Sinon appelle tous les moteurs en parallèle.

        Retourne `[(engine_name, [PlateResult, ...]), ...]`.
        """
        entries = self.active("PlateRecognizer")
        if not entries:
            return []

        if cascade_stop_at is not None:
            # Appels séquentiels (cascade) — respecte l'ordre `order`
            out: list[tuple[str, list]] = []
            for e in entries:
                plates = await self._call_one(
                    e,
                    lambda inst, f=frame, b=vehicle_bbox: inst.recognize(f, b),
                    timeout_s,
                )
                out.append((e.name, plates or []))
                if plates and max((p.confidence for p in plates), default=0.0) >= cascade_stop_at:
                    break
            return out

        # Parallèle
        results = await asyncio.gather(
            *[self._call_one(e, lambda inst, f=frame, b=vehicle_bbox: inst.recognize(f, b), timeout_s)
              for e in entries],
            return_exceptions=False,
        )
        return [(e.name, r or []) for e, r in zip(entries, results)]

    async def dispatch_event(
        self,
        event: MGVMSEvent,
        timeout_s: Optional[float] = None,
    ) -> list[tuple[str, object]]:
        """Fan-out sur tous les `EventConsumer` actifs."""
        entries = self.active("EventConsumer")
        if not entries:
            return []
        results = await asyncio.gather(
            *[self._call_one(e, lambda inst, ev=event: inst.on_event(ev), timeout_s)
              for e in entries],
            return_exceptions=False,
        )
        return [(e.name, r) for e, r in zip(entries, results)]


# Singleton
bus = PluginBus()
