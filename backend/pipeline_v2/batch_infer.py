"""Agrégateur d'inférence YOLO — un seul appel GPU pour toutes les caméras.

Problème résolu (v3.12), mesuré en production sur RTX A2000 / 6 caméras :

    inférence YOLO seule, mesurée hors pipeline ......  13-15 ms
    `yolo_ms` remonté par le pipeline ................ 130-500 ms
    utilisation GPU pendant ce temps .................      6 %

L'écart ne venait ni du modèle (yolo11n, le plus léger) ni de la résolution
d'entrée — Ultralytics redimensionne en interne, une image 4K coûte le même
temps qu'une 640px (vérifié : 14,3 ms contre 13,2 ms). Il venait de la
SÉRIALISATION : `ai_loop` lance les 6 caméras en parallèle via
`asyncio.to_thread`, mais toutes se bloquaient ensuite sur un verrou global
unique (`ai_engine.YOLO_INFERENCE_LOCK`) autour de `model.predict()`. Le GPU
recevait donc le travail d'une seule caméra à la fois et restait inoccupé,
pendant que les workers faisaient la queue.

Ce verrou était nécessaire : Ultralytics n'est pas sûr en appel concurrent
sur la MÊME instance de modèle (l'objet predictor porte l'état de la
prédiction en cours). On ne le retire donc pas — on supprime la file
d'attente en regroupant les images.

Principe : les threads appelants déposent leur image et attendent ; un
thread agrégateur collecte ce qui arrive dans une courte fenêtre, exécute UN
seul `predict([img1, ..., imgN])`, puis rend son résultat à chaque appelant.
Le GPU traite le lot en une passe, ce pour quoi il est fait.

Repli : toute anomalie (agrégateur mort, exception, délai dépassé) bascule
l'appelant sur l'ancien chemin `verrou + predict()` individuel. Le pipeline
ne peut donc pas devenir moins fiable qu'avant.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("pipeline_v2.batch_infer")

#: Fenêtre de regroupement. Doit rester bien SOUS le temps d'inférence
#: (~14 ms) pour ne pas ajouter de latence perceptible, tout en laissant aux
#: caméras lancées dans le même cycle `asyncio.gather` le temps d'arriver.
_WINDOW_S = 0.008
#: Au-delà, le lot est envoyé sans attendre la fin de la fenêtre.
_MAX_BATCH = 12
#: Garde-fou : un appelant ne reste jamais bloqué indéfiniment.
_WAIT_TIMEOUT_S = 8.0


class _Slot:
    __slots__ = ("image", "result", "error", "done")

    def __init__(self, image):
        self.image = image
        self.result: Any = None
        self.error: Optional[BaseException] = None
        self.done = threading.Event()


class BatchInference:
    def __init__(self) -> None:
        self._pending: list[_Slot] = []
        self._cv = threading.Condition()
        self._thread: Optional[threading.Thread] = None
        self._stats = {"batches": 0, "images": 0, "fallbacks": 0}

    # ── API publique ──────────────────────────────────────────────
    def infer(self, image, predict_fn) -> Any:
        """Retourne le résultat YOLO pour ``image``.

        ``predict_fn(list_of_images) -> list_of_results`` est fourni par
        l'appelant pour que ce module n'ait aucune dépendance vers
        ai_engine (et reste testable isolément).
        """
        self._ensure_runner(predict_fn)
        slot = _Slot(image)
        with self._cv:
            self._pending.append(slot)
            self._cv.notify()
        if not slot.done.wait(timeout=_WAIT_TIMEOUT_S):
            self._stats["fallbacks"] += 1
            raise TimeoutError("batch_infer: délai dépassé")
        if slot.error is not None:
            raise slot.error
        return slot.result

    def stats(self) -> dict:
        s = dict(self._stats)
        s["avg_batch"] = round(s["images"] / s["batches"], 2) if s["batches"] else 0
        return s

    # ── Interne ───────────────────────────────────────────────────
    def _ensure_runner(self, predict_fn) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._cv:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, args=(predict_fn,),
                name="yolo-batch-infer", daemon=True)
            self._thread.start()

    def _run(self, predict_fn) -> None:
        while True:
            with self._cv:
                while not self._pending:
                    self._cv.wait()
                # Laisse les autres caméras du même cycle nous rejoindre.
                deadline = time.monotonic() + _WINDOW_S
                while len(self._pending) < _MAX_BATCH:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._cv.wait(timeout=remaining)
                batch = self._pending[:_MAX_BATCH]
                self._pending = self._pending[_MAX_BATCH:]

            if not batch:
                continue
            try:
                results = predict_fn([s.image for s in batch])
                if results is None or len(results) != len(batch):
                    raise RuntimeError(
                        f"batch_infer: {len(batch)} images envoyées, "
                        f"{0 if results is None else len(results)} résultats reçus")
                for slot, res in zip(batch, results):
                    slot.result = res
            except BaseException as e:  # noqa: BLE001 — on propage à chaque appelant
                logger.warning("batch_infer: lot en échec (%s) — repli individuel", e)
                for slot in batch:
                    slot.error = e
            finally:
                self._stats["batches"] += 1
                self._stats["images"] += len(batch)
                for slot in batch:
                    slot.done.set()


#: Instance partagée par tous les CameraWorker.
batch_inference = BatchInference()
