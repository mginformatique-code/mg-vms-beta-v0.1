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

from .interfaces import FrameAnalyzer, PlateRecognizer, EventConsumer, Tracker, Segmenter, PipelineConsumer, Frame, MGVMSEvent, PipelineResult

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
    # État déclaré par le plugin lui-même après on_load / on_config_change
    state: str = "ready"  # ready | not_configured | missing_dependency | error | disabled | quarantined
    state_message: Optional[str] = None
    # ─── Sandbox comportementale (P2) ────────────────────────────────
    # Un plugin qui échoue N fois consécutivement est **mis en quarantaine** :
    # le bus ne l'appelle plus tant que l'admin ne l'a pas réactivé (ou tant qu'un
    # `on_config_change` réussi n'a pas remis `consecutive_errors = 0`).
    consecutive_errors: int = 0
    quarantined_at: Optional[str] = None
    quarantine_reason: Optional[str] = None

    def is_dispatchable(self) -> bool:
        """Un plugin est dispatché uniquement s'il est enabled ET ready (pas quarantined)."""
        return self.enabled and self.state == "ready"

    def summary(self) -> dict:
        return {
            "name": self.name,
            "interface": self.interface,
            "enabled": self.enabled,
            "order": self.order,
            "state": self.state,
            "state_message": self.state_message,
            "dispatchable": self.is_dispatchable(),
            "calls": self.calls,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "last_ms": round(self.last_ms, 2),
            "last_error": self.last_error,
            "consecutive_errors": self.consecutive_errors,
            "quarantined_at": self.quarantined_at,
            "quarantine_reason": self.quarantine_reason,
        }


class PluginBus:
    """Bus événementiel du Plugin Manager (PoC in-memory v2.30)."""

    # Seuil de quarantine automatique (P2 sandbox) : après N erreurs consécutives,
    # le plugin est marqué `quarantined` et exclu du dispatch jusqu'à réactivation
    # explicite par l'admin (ou reset auto sur un succès isolé).
    QUARANTINE_THRESHOLD = 5

    def __init__(self, default_timeout_s: float = 5.0):
        self._entries: dict[str, BusEntry] = {}
        self.default_timeout_s = default_timeout_s

    def _mark_success(self, entry: BusEntry) -> None:
        """Un appel a réussi → on réinitialise le compteur d'erreurs consécutives."""
        if entry.consecutive_errors:
            entry.consecutive_errors = 0

    def _mark_failure(self, entry: BusEntry, reason: str) -> None:
        """Un appel a échoué → incrémente le compteur et met en quarantine si seuil dépassé."""
        entry.consecutive_errors += 1
        if entry.consecutive_errors >= self.QUARANTINE_THRESHOLD and entry.state != "quarantined":
            from datetime import datetime, timezone
            entry.state = "quarantined"
            entry.quarantined_at = datetime.now(timezone.utc).isoformat()
            entry.quarantine_reason = (
                f"{entry.consecutive_errors} échecs consécutifs · dernier: {reason}"
            )[:200]
            logger.error(
                "plugin_bus.quarantine name=%s reason=%s",
                entry.name, entry.quarantine_reason,
            )

    def unquarantine(self, name: str) -> bool:
        """Sort un plugin de la quarantine — appelé par l'admin via l'API."""
        entry = self._entries.get(name)
        if not entry or entry.state != "quarantined":
            return False
        entry.state = "ready"
        entry.state_message = "réactivé manuellement après quarantine"
        entry.consecutive_errors = 0
        entry.quarantined_at = None
        entry.quarantine_reason = None
        logger.info("plugin_bus.unquarantine name=%s", name)
        return True

    # ── Enregistrement / suppression ────────────────────────────────────

    def register(self, name: str, instance, *, order: int = 100) -> BusEntry:
        """Enregistre une instance de plugin sur le bus.

        Détecte automatiquement l'interface via `isinstance`. Le même `name`
        remplace l'ancienne entrée (upgrade à chaud).
        """
        if isinstance(instance, PlateRecognizer):
            iface = "PlateRecognizer"
        elif isinstance(instance, Tracker):
            iface = "Tracker"
        elif isinstance(instance, Segmenter):
            iface = "Segmenter"
        elif isinstance(instance, PipelineConsumer):
            iface = "PipelineConsumer"
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
        """Plugins enabled ET state=ready (dispatchable réellement)."""
        return [e for e in self.list_entries(interface) if e.is_dispatchable()]

    def set_state(self, name: str, state: str, message: Optional[str] = None) -> bool:
        """Met à jour l'état d'un plugin (typiquement après on_load / reload)."""
        entry = self._entries.get(name)
        if not entry:
            return False
        entry.state = state
        entry.state_message = message
        return True

    def summary(self) -> list[dict]:
        return [e.summary() for e in self.list_entries()]

    # ── Dispatch ────────────────────────────────────────────────────────

    async def _call_one(
        self,
        entry: BusEntry,
        coro_factory,
        timeout_s: Optional[float] = None,
    ):
        """Exécute une coroutine plugin avec timeout + capture d'erreur + quarantine auto."""
        entry.calls += 1
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                coro_factory(entry.instance),
                timeout=timeout_s or self.default_timeout_s,
            )
            entry.last_ms = (time.perf_counter() - t0) * 1000
            entry.last_error = None
            self._mark_success(entry)
            return result
        except asyncio.TimeoutError:
            entry.timeouts += 1
            entry.errors += 1
            entry.last_ms = (time.perf_counter() - t0) * 1000
            entry.last_error = "timeout"
            logger.warning("plugin_bus.timeout name=%s after=%.1fms", entry.name, entry.last_ms)
            self._mark_failure(entry, "timeout")
            return None
        except Exception as e:  # pragma: no cover — isolation crash volontaire
            entry.errors += 1
            entry.last_ms = (time.perf_counter() - t0) * 1000
            entry.last_error = f"{type(e).__name__}: {e}"[:200]
            logger.warning("plugin_bus.error name=%s err=%s", entry.name, entry.last_error)
            self._mark_failure(entry, entry.last_error)
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

    # ── Pipeline chaîné Detector → Tracker → Segmenter → Business ─────

    async def dispatch_pipeline(
        self,
        frame: Frame,
        camera_config: Optional[dict] = None,
        *,
        run_segmentation: bool = False,
        run_business: bool = True,
        emit_events: bool = False,
        timeout_s: Optional[float] = None,
        precomputed_detections: Optional[list] = None,
    ) -> PipelineResult:
        """Enchaîne détection → tracking → segmentation → consommateurs métier.

        Si `precomputed_detections` est fourni, l'étape 1 (FrameAnalyzer)
        est **court-circuitée** et les detections passées sont utilisées
        directement. Cas d'usage : ai_engine a déjà fait tourner YOLO et
        veut réutiliser les résultats sans double inférence.
        """
        cfg = camera_config or {}
        result = PipelineResult(
            camera_id=frame.camera_id,
            timestamp=frame.timestamp,
        )
        timing = {}

        # ── 1. Detection ────────────────────────────────
        t = time.perf_counter()
        if precomputed_detections is not None:
            result.detections = list(precomputed_detections)
            result.plugins_used["detectors"] = ["precomputed"]
        else:
            det_results = await self.dispatch_frame(frame, cfg, timeout_s=timeout_s)
            result.plugins_used["detectors"] = [n for n, _ in det_results]
            for _name, ar in det_results:
                if ar is not None and hasattr(ar, "detections"):
                    result.detections.extend(ar.detections)
        timing["detection_ms"] = int((time.perf_counter() - t) * 1000)

        # ── 2. Tracking ─────────────────────────────────
        t = time.perf_counter()
        tracker_entries = self.active("Tracker")
        result.plugins_used["trackers"] = [e.name for e in tracker_entries]
        if tracker_entries and result.detections:
            tr_results = await asyncio.gather(
                *[self._call_one(e, lambda inst, f=frame, d=result.detections: inst.track(f, d),
                                 timeout_s) for e in tracker_entries],
                return_exceptions=False,
            )
            # Prend les tracks du 1er tracker (ordre order asc). Les autres
            # tournent quand même — leur état interne est mis à jour.
            for r in tr_results:
                if r is not None and hasattr(r, "tracks") and r.tracks:
                    result.tracks = r.tracks
                    break
        timing["tracking_ms"] = int((time.perf_counter() - t) * 1000)

        # ── 3. Segmentation (opt-in, coûteux) ──────────
        if run_segmentation:
            t = time.perf_counter()
            seg_entries = self.active("Segmenter")
            result.plugins_used["segmenters"] = [e.name for e in seg_entries]
            if seg_entries:
                seg_results = await asyncio.gather(
                    *[self._call_one(e, lambda inst, f=frame, c=cfg: inst.segment(f, c),
                                     timeout_s) for e in seg_entries],
                    return_exceptions=False,
                )
                for r in seg_results:
                    if r is not None and hasattr(r, "masks"):
                        result.masks.extend(r.masks)
            timing["segmentation_ms"] = int((time.perf_counter() - t) * 1000)

        # ── 4. Business Consumers ──────────────────────
        if run_business:
            t = time.perf_counter()
            biz_entries = self.active("PipelineConsumer")
            result.plugins_used["business"] = [e.name for e in biz_entries]
            if biz_entries:
                biz_results = await asyncio.gather(
                    *[self._call_one(e, lambda inst, f=frame, p=result: inst.consume(f, p),
                                     timeout_s) for e in biz_entries],
                    return_exceptions=False,
                )
                for name, events in zip([e.name for e in biz_entries], biz_results):
                    if events:
                        for ev in events:
                            if isinstance(ev, dict):
                                ev = {**ev, "source": name}
                                result.business_events.append(ev)
            timing["business_ms"] = int((time.perf_counter() - t) * 1000)

        # ── 5. Emit events (optionnel) ─────────────────
        if emit_events and result.business_events:
            from .interfaces import MGVMSEvent
            for be in result.business_events:
                event = MGVMSEvent(
                    type=be.get("type", "business.event"),
                    camera_id=frame.camera_id,
                    timestamp=frame.timestamp,
                    data=be,
                )
                await self.dispatch_event(event, timeout_s=timeout_s)

        result.timing_ms = timing
        return result


# Singleton
bus = PluginBus()
