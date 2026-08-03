"""Plugin anpr-eps — Machine à états ANPR : Entrée / Présence / Sortie.

Problème adressé (roadmap P8) :
    Sans EPS, chaque frame où la plaque est lue génère un événement → une voiture
    stationnée pendant 4h avec un ANPR à 5 FPS produit 72 000 événements.

Solution :
    On maintient un état par plaque × caméra :
        - ENTERED (nouvelle apparition)  → émet `plate_entered` UNE FOIS
        - PRESENT (toujours vue)         → silence (ou heartbeat périodique optionnel)
        - EXITED  (absente depuis > N s) → émet `plate_exited` UNE FOIS
        - après EXITED, si revue → nouveau cycle ENTERED

Notes :
    - Utilise `ctx.db` (namespace isolé du Plugin Manager) pour persister l'état
      entre redémarrages backend.
    - Émet des `business_events` consommés par le core (alerts + notifiers).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from plugin_manager.interfaces import Frame, PipelineConsumer, PipelineResult

STATE_ENTERED = "entered"
STATE_PRESENT = "present"
STATE_EXITED  = "exited"


class AnprEpsPlugin(PipelineConsumer):
    """Machine à états EPS pour événements ANPR."""

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        # In-memory state pour vitesse ; miroir en DB pour persistance
        # Clé : (camera_id, plate)
        self._state: dict[tuple[str, str], dict] = {}
        # Reload state depuis la DB isolée
        if ctx.db is not None:
            try:
                docs = await ctx.db.find({"state": {"$in": [STATE_ENTERED, STATE_PRESENT]}})
                for d in docs:
                    key = (d["camera_id"], d["plate"])
                    self._state[key] = {
                        "state": d["state"],
                        "first_seen_ts": d.get("first_seen_ts"),
                        "last_seen_ts": d.get("last_seen_ts", time.time()),
                        "last_hb_ts": d.get("last_hb_ts", time.time()),
                        "confidence": d.get("confidence", 0.0),
                    }
                ctx.log.info(f"[anpr-eps] rehydrated {len(self._state)} active plates from DB")
            except Exception as e:
                ctx.log.warning(f"[anpr-eps] rehydrate failed: {e}")
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        # Config lue à la volée depuis ctx.config, rien à faire
        pass

    def _cfg(self):
        c = self._ctx.config or {}
        return {
            "exit_s": int(c.get("exit_threshold_seconds", 30)),
            "min_conf": float(c.get("min_confidence", 0.65)),
            "hb_enabled": bool(c.get("emit_presence_heartbeats", False)),
            "hb_s": int(c.get("heartbeat_minutes", 15)) * 60,
        }

    async def _persist(self, camera_id: str, plate: str, entry: dict) -> None:
        """Miroir DB (best-effort — silencieux si DB indisponible)."""
        if self._ctx.db is None:
            return
        try:
            await self._ctx.db.update(
                {"camera_id": camera_id, "plate": plate},
                {"$set": {"camera_id": camera_id, "plate": plate, **entry}},
            )
            # Update ne crée pas → insert si absent
            existing = await self._ctx.db.find_one({"camera_id": camera_id, "plate": plate})
            if not existing:
                await self._ctx.db.insert({"camera_id": camera_id, "plate": plate, **entry})
        except Exception:
            pass

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        """Traite les plaques reconnues dans ce cycle pipeline.

        Le core enrichit `pipeline.business_events` avec les plaques via
        `plate_recognized` (structure : {plate, confidence, engine, bbox}).
        """
        cfg = self._cfg()
        now = time.time()
        camera_id = pipeline.camera_id or frame.camera_id or "unknown"
        emitted = []

        # Récupère les plaques du cycle courant (émises par les PlateRecognizer)
        plates_now = []
        for ev in pipeline.business_events or []:
            if ev.get("type") == "plate_recognized":
                plate = (ev.get("plate") or ev.get("data", {}).get("plate") or "").upper().strip()
                conf = float(ev.get("confidence") or ev.get("data", {}).get("confidence") or 0.0)
                if plate and conf >= cfg["min_conf"]:
                    plates_now.append((plate, conf))

        # 1) Passage à ENTERED ou PRESENT pour les plaques vues maintenant
        seen_keys = set()
        for plate, conf in plates_now:
            key = (camera_id, plate)
            seen_keys.add(key)
            entry = self._state.get(key)
            if entry is None or entry.get("state") == STATE_EXITED:
                # Nouvelle entrée (ou re-entrée après sortie)
                self._state[key] = {
                    "state": STATE_ENTERED,
                    "first_seen_ts": now,
                    "last_seen_ts": now,
                    "last_hb_ts": now,
                    "confidence": conf,
                }
                emitted.append({
                    "type": "plate_entered",
                    "severity": "info",
                    "message": f"Plaque entrée : {plate}",
                    "data": {
                        "plate": plate,
                        "camera_id": camera_id,
                        "confidence": conf,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })
                await self._persist(camera_id, plate, self._state[key])
            else:
                # Toujours présent → PRESENT (aucun event sauf heartbeat)
                entry["state"] = STATE_PRESENT
                entry["last_seen_ts"] = now
                entry["confidence"] = max(entry.get("confidence", 0.0), conf)
                if cfg["hb_enabled"] and (now - entry.get("last_hb_ts", 0)) >= cfg["hb_s"]:
                    entry["last_hb_ts"] = now
                    emitted.append({
                        "type": "plate_present_heartbeat",
                        "severity": "info",
                        "message": f"Plaque toujours présente : {plate}",
                        "data": {
                            "plate": plate,
                            "camera_id": camera_id,
                            "since_seconds": int(now - entry["first_seen_ts"]),
                        },
                    })
                await self._persist(camera_id, plate, entry)

        # 2) Détection de sortie : plaques absentes depuis > exit_s
        exit_s = cfg["exit_s"]
        to_exit = []
        for key, entry in list(self._state.items()):
            if key[0] != camera_id:
                continue  # scope par caméra
            if key in seen_keys:
                continue
            if entry.get("state") == STATE_EXITED:
                continue
            if (now - entry.get("last_seen_ts", 0)) > exit_s:
                to_exit.append(key)

        for key in to_exit:
            plate = key[1]
            entry = self._state[key]
            entry["state"] = STATE_EXITED
            duration = int(entry.get("last_seen_ts", now) - entry.get("first_seen_ts", now))
            emitted.append({
                "type": "plate_exited",
                "severity": "info",
                "message": f"Plaque sortie : {plate}",
                "data": {
                    "plate": plate,
                    "camera_id": camera_id,
                    "presence_duration_seconds": duration,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            })
            await self._persist(camera_id, plate, entry)

        return emitted

    # Utilitaire pour tests
    def _get_state(self, camera_id: str, plate: str) -> str | None:
        entry = self._state.get((camera_id, plate.upper()))
        return entry.get("state") if entry else None
