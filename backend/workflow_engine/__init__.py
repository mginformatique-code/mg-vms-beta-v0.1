"""P4 · Workflow Engine — moteur d'automatisation type Home Assistant.

Un **workflow** est composé de 3 parties :

1. **Triggers** — événements déclencheurs (au moins un match → workflow lancé)
   - `event.type`        : match sur `type` d'un événement DB (ex. `plate.blacklist`)
   - `zone.enter/exit`   : match sur événement Smart Zone
   - `plate.enter/exit`  : match sur ANPR E/P/S
   - `schedule.cron`     : trigger périodique (cron)
   - `manual`            : trigger manuel via API

2. **Conditions** — toutes doivent être vraies pour continuer (AND)
   - `time_between`  : hh:mm → hh:mm (heure locale du serveur)
   - `camera_is`     : id caméra ∈ [...]
   - `plate_in_list` : list_status ∈ ["black", "white", "none"]
   - `field_equals`  : {path, value} — vérifie n'importe quel champ de l'event

3. **Actions** — exécutées séquentiellement
   - Réutilise les actionneurs `smart_zones.actuators` (webhook/mqtt/HA/tuya/plugin/tts)
   - Ajoute : `delay` (attendre N s avant l'action suivante)

Un workflow peut être `enabled: false` (désactivé).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("workflow_engine")


# ── Conditions ────────────────────────────────────────────────────────
def _get_path(obj: dict, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _eval_condition(cond: dict, event: dict) -> bool:
    ctype = cond.get("type")
    try:
        if ctype == "time_between":
            start = cond.get("start", "00:00")
            end = cond.get("end", "23:59")
            now = datetime.now().strftime("%H:%M")
            if start <= end:
                return start <= now <= end
            # Wrap around minuit
            return now >= start or now <= end
        if ctype == "camera_is":
            return event.get("camera_id") in (cond.get("cameras") or [])
        if ctype == "plate_in_list":
            return event.get("list_status") in (cond.get("lists") or [])
        if ctype == "field_equals":
            return _get_path(event, cond.get("path", "")) == cond.get("value")
        if ctype == "field_regex":
            v = _get_path(event, cond.get("path", ""))
            return isinstance(v, str) and re.search(cond.get("pattern", ""), v) is not None
    except Exception:
        logger.warning("workflow.condition_error type=%s", ctype)
        return False
    return False


def _eval_conditions(conds: list, event: dict) -> bool:
    """AND global — toutes les conditions doivent être vraies."""
    return all(_eval_condition(c, event) for c in (conds or []))


# ── Triggers ──────────────────────────────────────────────────────────
def _trigger_matches(trigger: dict, event: dict) -> bool:
    ttype = trigger.get("type")
    if ttype == "event.type":
        return event.get("type") == trigger.get("event_type")
    if ttype in ("zone.enter", "zone.exit", "zone.present"):
        want = ttype  # "zone.enter" etc.
        if event.get("type") != want:
            return False
        zone_id = trigger.get("zone_id")
        if zone_id and (event.get("data") or {}).get("zone_id") != zone_id:
            return False
        return True
    if ttype == "plate.enter":
        return event.get("type") == "plate_entered"
    if ttype == "plate.exit":
        return event.get("type") == "plate_exited"
    return False


# ── Runtime engine ────────────────────────────────────────────────────
@dataclass
class _WorkflowStats:
    executions: int = 0
    last_run_at: str | None = None
    last_status: str = "idle"  # idle | ok | error
    last_error: str | None = None


class WorkflowEngine:
    """Évalue les workflows contre les événements du bus interne."""

    def __init__(self):
        self._workflows: list[dict] = []
        self._cache_ts: float = 0
        self._cache_ttl_s: float = 10.0
        self._stats: dict[str, _WorkflowStats] = {}

    async def _load(self) -> list[dict]:
        now = time.time()
        if now - self._cache_ts < self._cache_ttl_s and self._workflows:
            return self._workflows
        try:
            from database import db
            self._workflows = await db.workflows.find(
                {"enabled": True}, {"_id": 0},
            ).sort("created_at", -1).to_list(200)
            self._cache_ts = now
        except Exception as e:
            logger.warning("workflow.load_error err=%s", e)
        return self._workflows

    def invalidate_cache(self) -> None:
        self._cache_ts = 0

    def stats(self, workflow_id: str) -> dict:
        s = self._stats.get(workflow_id) or _WorkflowStats()
        return {"executions": s.executions, "last_run_at": s.last_run_at,
                "last_status": s.last_status, "last_error": s.last_error}

    async def on_event(self, event: dict) -> list[dict]:
        """Point d'entrée : appelée par `ai_engine` pour chaque event notable."""
        workflows = await self._load()
        results = []
        for wf in workflows:
            triggers = wf.get("triggers") or []
            if not any(_trigger_matches(t, event) for t in triggers):
                continue
            if not _eval_conditions(wf.get("conditions"), event):
                continue
            r = await self._execute(wf, event)
            results.append(r)
        return results

    async def run_manual(self, workflow_id: str, payload: dict | None = None) -> dict:
        """Lance un workflow manuellement (bouton test UI)."""
        workflows = await self._load()
        wf = next((w for w in workflows if w.get("id") == workflow_id), None)
        if not wf:
            return {"ok": False, "error": "workflow introuvable ou désactivé"}
        event = {"type": "manual.trigger", "camera_id": None,
                 "timestamp": datetime.now(timezone.utc).isoformat(),
                 "data": payload or {}}
        return await self._execute(wf, event)

    async def _execute(self, wf: dict, event: dict) -> dict:
        from smart_zones.actuators import dispatch_action
        wid = wf.get("id")
        s = self._stats.setdefault(wid, _WorkflowStats())
        s.executions += 1
        s.last_run_at = datetime.now(timezone.utc).isoformat()
        s.last_status = "running"
        action_results = []
        context = {
            "workflow_name": wf.get("name"),
            "workflow_id": wid,
            "camera_id": event.get("camera_id"),
            "event_type": event.get("type"),
            "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            **(event.get("data") or {}),
        }
        try:
            for action in wf.get("actions") or []:
                if action.get("type") == "delay":
                    await asyncio.sleep(float(action.get("config", {}).get("seconds", 1)))
                    action_results.append({"type": "delay", "ok": True})
                else:
                    r = await dispatch_action(action, context)
                    action_results.append(r)
            s.last_status = "ok"
            s.last_error = None
        except Exception as e:  # pragma: no cover
            s.last_status = "error"
            s.last_error = f"{type(e).__name__}: {e}"[:200]
            logger.exception("workflow.exec_error id=%s", wid)
        # persistance stats (best-effort)
        try:
            from database import db
            await db.workflows.update_one(
                {"id": wid},
                {"$inc": {"execution_count": 1},
                 "$set": {"last_run_at": s.last_run_at, "last_status": s.last_status}},
            )
        except Exception:
            pass
        return {"workflow_id": wid, "workflow_name": wf.get("name"),
                "status": s.last_status, "actions": action_results}


engine = WorkflowEngine()
