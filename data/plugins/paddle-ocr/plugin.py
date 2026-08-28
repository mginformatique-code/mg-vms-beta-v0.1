"""Plugin ANPR — PaddleOCR (local Baidu)."""
from __future__ import annotations

import re
import time
from typing import Optional

from plugin_manager.interfaces import PlateRecognizer, Frame, PlateResult

PLATE_RX = re.compile(r"[A-Z0-9\-]{4,10}")


class PaddleOCRPlugin(PlateRecognizer):
    name = "paddle-ocr"
    version = "1.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        self._ocr = None
        self._api_v3 = False
        # v1.0-rc4 · Un segfault C++ de paddle inference (observé sur aarch64)
        # ne doit JAMAIS tuer le backend : on sonde l'init dans un sous-processus
        # isolé AVANT toute init in-process.
        try:
            import paddleocr  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install paddleocr paddlepaddle")
            return
        ok, msg = await self._probe_isolated()
        if not ok:
            self._ctx.set_state("error", f"PaddleOCR inference indisponible (sonde isolée — backend protégé) : {msg}")
            return
        self._init_engine()

    async def _probe_isolated(self, timeout_s: int = 120) -> tuple:
        """Init PaddleOCR dans un sous-processus jetable. Capture segfaults C++."""
        import asyncio
        import os
        import sys
        code = (
            "from paddleocr import PaddleOCR\n"
            "try:\n"
            "    PaddleOCR(lang='en', use_textline_orientation=False,\n"
            "              use_doc_orientation_classify=False, use_doc_unwarping=False,\n"
            "              device='cpu')\n"
            "except TypeError:\n"
            "    PaddleOCR(use_angle_cls=False, lang='en', use_gpu=False, show_log=False)\n"
            "print('PROBE_OK')\n"
        )
        env = {**os.environ, "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True"}
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            except asyncio.TimeoutError:
                proc.kill()
                return False, f"init > {timeout_s}s (téléchargement modèles ?) — réessayez"
            txt = (out or b"").decode(errors="replace")
            if proc.returncode == 0 and "PROBE_OK" in txt:
                return True, "ok"
            sig = f"rc={proc.returncode}"
            if proc.returncode and proc.returncode < 0:
                sig += " (crash natif C++ — probablement architecture non supportée, ex: aarch64)"
            tail = txt.strip().splitlines()[-1][:150] if txt.strip() else ""
            return False, f"{sig} {tail}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _evaluate_state(self):
        try:
            import paddleocr  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install paddleocr paddlepaddle")
            return
        self._init_engine()

    def _init_engine(self):
        try:
            import paddleocr  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install paddleocr paddlepaddle")
            return
        try:
            from paddleocr import PaddleOCR
            cfg = self._ctx.config or {}
            lang = cfg.get("lang", "en")
            try:
                # PaddleOCR 3.x — nouvelle API (use_angle_cls/show_log supprimés)
                self._ocr = PaddleOCR(
                    lang=lang,
                    use_textline_orientation=True,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    device="gpu" if cfg.get("use_gpu") else "cpu",
                )
                self._api_v3 = True
            except TypeError:
                # PaddleOCR 2.x — ancienne API
                self._ocr = PaddleOCR(
                    use_angle_cls=True,
                    lang=lang,
                    use_gpu=bool(cfg.get("use_gpu", False)),
                    show_log=False,
                )
                self._api_v3 = False
            self._ctx.set_state("ready")
        except Exception as e:
            self._ctx.set_state("error", f"PaddleOCR init failed: {e}")

    async def on_config_change(self, new_config: dict) -> None:
        # Même protection que on_load : jamais d'init in-process sans sonde.
        self._ocr = None
        try:
            import paddleocr  # noqa
        except ImportError:
            self._ctx.set_state("missing_dependency", "pip install paddleocr paddlepaddle")
            return
        ok, msg = await self._probe_isolated()
        if not ok:
            self._ctx.set_state("error", f"PaddleOCR inference indisponible (sonde isolée — backend protégé) : {msg}")
            return
        self._init_engine()

    async def recognize(self, frame: Frame, vehicle_bbox: Optional[tuple] = None) -> list:
        if self._ocr is None:
            return []
        img = frame.numpy_bgr
        if vehicle_bbox:
            x1, y1, x2, y2 = [int(v) for v in vehicle_bbox]
            c = img[max(0, y1):y2, max(0, x1):x2]
            if c.size > 0:
                img = c

        min_conf = float((self._ctx.config or {}).get("min_confidence", 0.5))
        t0 = time.perf_counter()
        try:
            if getattr(self, "_api_v3", False):
                # PaddleOCR 3.x : predict() retourne des objets result avec
                # rec_texts / rec_scores — normalisé vers le format 2.x.
                #
                # v3.19 · `p.get("rec_texts", [])` ne protège QUE l'absence de
                # la clé — quand aucun texte n'est reconnu dans la région,
                # PaddleOCR renvoie la clé présente mais avec la valeur None
                # (pas une liste vide), donc le défaut de .get() ne s'applique
                # jamais et `zip(None, ...)` lève "TypeError: 'NoneType'
                # object is not iterable". Confirmé en conditions réelles :
                # 2/2 appels réels en échec avec cette erreur exacte (analyse
                # manuelle de plaque toujours KO). `or []` protège aussi le
                # cas valeur-présente-mais-None, pas seulement clé-absente.
                # v3.19 · Le `[None, (t, s)]` d'origine ne remontait AUCUNE
                # boîte réelle — `rec_polys` (polygone détecté) est disponible
                # sur l'objet retourné et donne la vraie position de la
                # plaque dans le crop (vérifié : présent aux côtés de
                # rec_texts/rec_scores). Repli sur `None` uniquement si la
                # liste manque/désaligne (voir garde `box is None` plus bas).
                preds = self._ocr.predict(img) or []
                result = [[
                    [poly, (t, s)]
                    for t, s, poly in zip(p.get("rec_texts") or [], p.get("rec_scores") or [],
                                           p.get("rec_polys") or [None] * len(p.get("rec_texts") or []))
                ] for p in preds]
            else:
                result = self._ocr.ocr(img, cls=True) or []
        except Exception as e:
            self._ctx.log.warning(f"paddle-ocr error: {e}")
            return []
        dt_ms = int((time.perf_counter() - t0) * 1000)

        out = []
        # PaddleOCR retourne [[[box, (text, score)], ...]] par page
        for page in (result or []):
            if page is None:
                continue
            for line in page:
                try:
                    box, (text, score) = line
                except Exception:
                    continue
                if score < min_conf:
                    continue
                # v3.19 · Sur les plaques FR, PaddleOCR lit parfois le point
                # séparateur physique comme "·" (interpunct) plutôt qu'un
                # tiret — non couvert par PLATE_RX, ce qui tronquait le
                # texte au premier point rencontré (ex: "GS-550·PX" ->
                # seulement "GS-550", "PX" perdu). Vérifié sur un cas réel.
                cleaned = str(text).upper().replace(" ", "").replace("·", "").replace("•", "")
                m = PLATE_RX.search(cleaned)
                if not m:
                    continue
                plate = m.group(0)
                if not (any(c.isalpha() for c in plate) and any(c.isdigit() for c in plate)):
                    continue
                # v3.19 · `box` peut rester None (polygone manquant/désaligné,
                # voir ci-dessus) — c'était la cause exacte du crash "analyse
                # manuelle KO" (TypeError: 'NoneType' object is not
                # iterable). Repli sur le crop entier plutôt que planter :
                # la position exacte est secondaire, le texte/la confiance
                # restent corrects.
                if box is None:
                    xs, ys = [0, img.shape[1]], [0, img.shape[0]]
                else:
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                out.append(PlateResult(
                    text=plate,
                    confidence=float(score),
                    bbox_plate=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
                    engine="paddle-ocr",
                    processing_ms=dt_ms,
                ))
        return out

    async def on_unload(self) -> None:
        self._ocr = None
