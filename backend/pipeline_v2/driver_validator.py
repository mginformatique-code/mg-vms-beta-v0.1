"""v0.5.7 · Universal Camera API — Driver Validator (non destructif).

Service passif de validation des capacités d'une caméra. Il ne modifie
**jamais** l'état physique de l'équipement :

  ✅ Autorisé : appeler ``get_device_info``, ``get_streams``, ``get_capabilities``,
     ``get_status`` (opérations en lecture seule).
  ❌ Interdit : ``ptz_move``, ``set_light``, ``set_siren``, ``start_audio``,
     ``reboot`` — ces capacités sont validées **par inspection de contrat**
     (méthode surchargée par rapport à ``CameraDriver`` base).

Score pondéré (poids par test) :

    snapshot     25
    stream       25
    device_info  15
    events       15
    ptz          10
    audio         5
    reboot        3
    siren         2

Le score final est calculé sur les tests **effectivement supportés** par
la caméra : une capacité absente (``UNSUPPORTED``) n'est pas comptée dans
le dénominateur. Un test ``PASS`` compte pour son poids, ``WARNING`` pour
70 %, ``FAIL`` / ``TIMEOUT`` pour 0.

Le service n'écrit rien en base en mode ``GET`` — il est entièrement
idempotent. La persistance est explicite via ``persist=True``.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

from pipeline_v2.camera_driver import (
    CameraDriver,
    CameraDriverError,
    UnsupportedCapabilityError,
)
from pipeline_v2.camera_manager import camera_manager

logger = logging.getLogger("pipeline_v2.driver_validator")


# ═════════════════════════════════════════════════════════════════════════
# Enum d'états — unique dans tout le validator
# ═════════════════════════════════════════════════════════════════════════
class TestState(str, Enum):
    """États autorisés pour un test de validation.

    - ``PASS``        : test réussi.
    - ``WARNING``     : test partiellement réussi (compté 70 %).
    - ``FAIL``        : test exécuté mais échec.
    - ``TIMEOUT``     : test n'a pas répondu dans le délai imparti.
    - ``UNSUPPORTED`` : capacité non déclarée par le driver — exclu du score.
    - ``SKIPPED``     : test volontairement non exécuté — exclu du score.
    """
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
    SKIPPED = "skipped"


_STATE_FACTOR: dict[TestState, float] = {
    TestState.PASS: 1.0,
    TestState.WARNING: 0.7,
    TestState.FAIL: 0.0,
    TestState.TIMEOUT: 0.0,
    # UNSUPPORTED / SKIPPED : exclus du numérateur ET du dénominateur.
}


# Poids officiels — voir docstring module.
TEST_WEIGHTS: dict[str, int] = {
    "snapshot":    25,
    "stream":      25,
    "device_info": 15,
    "events":      15,
    "ptz":         10,
    "audio":        5,
    "reboot":       3,
    "siren":        2,
}


# ═════════════════════════════════════════════════════════════════════════
# Résultats
# ═════════════════════════════════════════════════════════════════════════
@dataclass
class TestResult:
    """Résultat d'un test unitaire de validation."""
    name: str
    state: TestState
    weight: int
    latency_ms: Optional[int] = None
    reason: Optional[str] = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        # Nettoie les champs None
        return {k: v for k, v in d.items() if v is not None and v != {}}


@dataclass
class ValidationReport:
    """Rapport complet de validation d'une caméra."""
    validation_id: str
    camera_id: str
    vendor: str
    model: str
    driver: str
    started_at: str
    finished_at: str
    duration_ms: int
    score: int
    tests: dict[str, dict]

    def to_dict(self) -> dict:
        return asdict(self)


# ═════════════════════════════════════════════════════════════════════════
# Utilitaires — inspection de contrat (méthode surchargée ?)
# ═════════════════════════════════════════════════════════════════════════
def _method_is_overridden(driver: CameraDriver, method_name: str) -> bool:
    """True si ``method_name`` a été surchargée depuis ``CameraDriver`` base.

    Sert à valider les capacités destructives (ptz, siren, light, audio, reboot)
    **sans les exécuter**. On regarde la MRO :

      - Méthode inexistante → False.
      - Méthode identique à celle de ``CameraDriver`` (ABC de base) → False.
      - Méthode redéfinie dans un ancêtre autre que ``CameraDriver`` → True.

    Note : ONVIFDriver surcharge déjà PTZ/IR, donc tous ses descendants (Reolink,
    Hikvision, Dahua) sont **automatiquement** considérés PTZ-conformes — c'est
    le comportement voulu (héritage = support).
    """
    from drivers.camera_driver import CameraDriver as _Base
    driver_impl = getattr(driver.__class__, method_name, None)
    base_impl = getattr(_Base, method_name, None)
    if driver_impl is None:
        return False
    if base_impl is None:
        # Méthode absente de l'ABC → toute présence chez le driver = surcharge.
        return True
    return driver_impl is not base_impl


# ═════════════════════════════════════════════════════════════════════════
# Validator
# ═════════════════════════════════════════════════════════════════════════
class DriverValidator:
    """Service de validation non destructif d'un ``CameraDriver``.

    Toutes les méthodes sont ``async``. Aucune persistance implicite —
    la sauvegarde du dernier rapport est explicite via ``run_and_persist``.
    """

    DEFAULT_TIMEOUT_S: float = 6.0

    async def validate(self, camera_id: str,
                        timeout_s: float | None = None) -> ValidationReport:
        """Exécute la batterie de tests pour ``camera_id`` (aucune persistance)."""
        t_total = time.perf_counter()
        started_at = _now_iso()
        try:
            driver = await camera_manager.get_driver(camera_id)
        except CameraDriverError as e:
            # Impossible de tester : renvoie un rapport avec score=0 et raison.
            finished_at = _now_iso()
            return ValidationReport(
                validation_id=str(uuid.uuid4()),
                camera_id=camera_id,
                vendor="unknown", model="unknown", driver="unknown",
                started_at=started_at, finished_at=finished_at,
                duration_ms=int((time.perf_counter() - t_total) * 1000),
                score=0,
                tests={"connect": TestResult(
                    "connect", TestState.FAIL, 100, reason=e.message or str(e),
                ).to_dict()},
            )

        vendor = getattr(driver, "vendor", "unknown")
        info = None
        try:
            info = await driver.get_device_info()
        except Exception:
            pass

        # Batterie de tests parallèle où c'est safe (lectures seules).
        results: dict[str, TestResult] = {}
        results["device_info"] = await self._test_device_info(driver)
        results["stream"] = await self._test_stream(driver)
        results["snapshot"] = await self._test_snapshot(driver, results["stream"])
        results["events"] = await self._test_events(driver)
        # Inspection contrat uniquement (aucune action physique).
        results["ptz"] = self._test_contract(driver, ["_ptz_move", "_ptz_preset"])
        results["audio"] = self._test_contract(driver, ["_start_audio", "_stop_audio"])
        results["siren"] = self._test_contract(driver, ["_set_siren"])
        results["reboot"] = self._test_contract(driver, ["reboot", "_reboot"])

        # Adapter le poids réel de chaque résultat.
        for name, res in results.items():
            res.weight = TEST_WEIGHTS.get(name, 0)

        score = self._compute_score(results)
        finished_at = _now_iso()
        duration_ms = int((time.perf_counter() - t_total) * 1000)

        return ValidationReport(
            validation_id=str(uuid.uuid4()),
            camera_id=camera_id,
            vendor=vendor,
            model=(info.model if info else "unknown") or "unknown",
            driver=vendor,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            score=score,
            tests={k: v.to_dict() for k, v in results.items()},
        )

    async def run_and_persist(self, camera_id: str) -> ValidationReport:
        """Exécute la validation ET persiste le résultat en Mongo.

        Écrit dans ``cameras[camera_id].last_validation``.
        """
        report = await self.validate(camera_id)
        try:
            from database import db
            await db.cameras.update_one(
                {"id": camera_id},
                {"$set": {"last_validation": report.to_dict()}},
            )
        except Exception as e:
            logger.warning("persist validation report failed for %s: %s", camera_id, e)
        return report

    # ── Tests unitaires ─────────────────────────────────────────
    async def _test_device_info(self, driver: CameraDriver) -> TestResult:
        t0 = time.perf_counter()
        try:
            info = await asyncio.wait_for(driver.get_device_info(),
                                          timeout=self.DEFAULT_TIMEOUT_S)
        except asyncio.TimeoutError:
            return TestResult("device_info", TestState.TIMEOUT, 0,
                              reason=f"timeout > {self.DEFAULT_TIMEOUT_S}s")
        except Exception as e:
            return TestResult("device_info", TestState.FAIL, 0, reason=str(e))
        lat = int((time.perf_counter() - t0) * 1000)
        if not info or not (info.manufacturer or info.model):
            return TestResult("device_info", TestState.WARNING, 0,
                              latency_ms=lat, reason="empty manufacturer/model")
        return TestResult("device_info", TestState.PASS, 0, latency_ms=lat,
                          meta={"manufacturer": info.manufacturer, "model": info.model})

    async def _test_stream(self, driver: CameraDriver) -> TestResult:
        t0 = time.perf_counter()
        try:
            streams = await asyncio.wait_for(driver.get_streams(),
                                             timeout=self.DEFAULT_TIMEOUT_S)
        except asyncio.TimeoutError:
            return TestResult("stream", TestState.TIMEOUT, 0,
                              reason=f"timeout > {self.DEFAULT_TIMEOUT_S}s")
        except Exception as e:
            return TestResult("stream", TestState.FAIL, 0, reason=str(e))
        lat = int((time.perf_counter() - t0) * 1000)
        if not streams:
            return TestResult("stream", TestState.UNSUPPORTED, 0,
                              latency_ms=lat, reason="no stream returned")
        first = streams[0]
        url = getattr(first, "url", "") or ""
        parsed = urlparse(url)
        if not parsed.scheme or parsed.scheme not in ("rtsp", "http", "https", "rtsps"):
            return TestResult("stream", TestState.FAIL, 0, latency_ms=lat,
                              reason=f"invalid stream URL scheme '{parsed.scheme}'")
        return TestResult("stream", TestState.PASS, 0, latency_ms=lat,
                          meta={"count": len(streams), "first_url_scheme": parsed.scheme})

    async def _test_snapshot(self, driver: CameraDriver,
                              stream_result: TestResult) -> TestResult:
        # Snapshot dépend d'un stream disponible — s'il n'y en a pas, on est cohérent.
        if stream_result.state in (TestState.UNSUPPORTED, TestState.FAIL,
                                    TestState.TIMEOUT):
            return TestResult("snapshot", TestState.UNSUPPORTED, 0,
                              reason="no working stream to snapshot from")
        # Le contrat CameraDriver n'expose pas encore snapshot() natif — on utilise
        # get_streams() comme proxy (une URL valide = capacité snapshot confirmée).
        return TestResult("snapshot", TestState.PASS, 0,
                          latency_ms=stream_result.latency_ms,
                          meta={"source": "stream_url"})

    async def _test_events(self, driver: CameraDriver) -> TestResult:
        # L'API events n'est pas dans le contrat de base — on regarde la présence
        # d'un attribut ``events`` ou méthode ``get_events`` sur le driver concret.
        has_events = any(
            hasattr(driver, name)
            for name in ("get_events", "events", "subscribe_events")
        )
        if not has_events:
            return TestResult("events", TestState.UNSUPPORTED, 0,
                              reason="driver exposes no events API")
        return TestResult("events", TestState.PASS, 0,
                          meta={"note": "contract-only inspection"})

    def _test_contract(self, driver: CameraDriver,
                        method_names: list[str]) -> TestResult:
        """Vérifie qu'au moins une méthode privée est surchargée par le driver."""
        overridden = [m for m in method_names if _method_is_overridden(driver, m)]
        if not overridden:
            return TestResult(method_names[0].lstrip("_"), TestState.UNSUPPORTED, 0,
                              reason="no override — capability not implemented")
        return TestResult(
            method_names[0].lstrip("_"),
            TestState.PASS,
            0,
            meta={"overridden": overridden, "note": "contract-only inspection"},
        )

    # ── Score pondéré ────────────────────────────────────────────
    def _compute_score(self, results: dict[str, TestResult]) -> int:
        num = 0.0
        den = 0.0
        for name, res in results.items():
            weight = TEST_WEIGHTS.get(name, 0)
            if res.state in (TestState.UNSUPPORTED, TestState.SKIPPED):
                continue
            den += weight
            num += weight * _STATE_FACTOR.get(res.state, 0.0)
        if den <= 0:
            return 0
        return int(round((num / den) * 100))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Singleton exposé
driver_validator = DriverValidator()

__all__ = [
    "TestState",
    "TestResult",
    "ValidationReport",
    "DriverValidator",
    "driver_validator",
    "TEST_WEIGHTS",
]
