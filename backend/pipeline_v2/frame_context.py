"""Pipeline v2 · FrameContext — objet UNIQUE partagé par tous les stages.

La frame est décodée UNE seule fois, les crops véhicules extraits UNE seule
fois, les JPEG encodés UNE seule fois (memoization par qualité). Tous les
plugins/étages consomment ce même objet par référence — zéro copie.
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Optional


def encode_jpeg_data_uri(bgr_img, max_width: int = 1280, quality: int = 85):
    """Encode une image BGR en data-URI JPEG (None si vide/échec)."""
    import cv2
    if bgr_img is None or bgr_img.size == 0:
        return None
    h, w = bgr_img.shape[:2]
    if w > max_width:
        bgr_img = cv2.resize(bgr_img, (max_width, int(h * max_width / w)),
                              interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", bgr_img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None


def dominant_color_fr(bgr_crop):
    """Couleur dominante réelle (analyse HSV) — nommage français."""
    import cv2
    import numpy as np
    if bgr_crop is None or bgr_crop.size == 0:
        return None
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[:, :, i].astype(np.float32) for i in range(3))
    mean_s, mean_v = float(s.mean()), float(v.mean())
    if mean_v < 60:
        return "Noir"
    if mean_s < 45:
        if mean_v > 170:
            return "Blanc"
        return "Gris"
    # v3.1.2 · Fix : ne voter sur la teinte QUE parmi les pixels réellement
    # saturés (carrosserie colorée), pas tout le crop. Sinon un feu arrière
    # rouge très saturé mais minoritaire en surface (quelques % du crop)
    # suffit à faire remonter mean_s au-dessus de 45 ET à dominer
    # l'histogramme de teinte non masqué — une voiture BLANCHE vue de
    # l'arrière ressort alors classée "Rouge". Repéré via un cas réel
    # (Twingo blanche classée Rouge, feux arrière visibles sur le crop).
    colored_mask = ((s > 45) & (v > 60)).astype(np.uint8)
    total_px = bgr_crop.shape[0] * bgr_crop.shape[1]
    n_colored = int(colored_mask.sum())
    if total_px == 0 or n_colored / total_px < 0.20:
        # Pas assez de carrosserie réellement colorée pour faire confiance à
        # une teinte dominante (ex : blanche/grise avec juste des feux/reflets
        # colorés) — retomber sur la classification neutre déjà écartée trop
        # tôt par le test mean_s ci-dessus.
        return "Blanc" if mean_v > 170 else "Gris"
    hist = cv2.calcHist([hsv], [0], colored_mask, [180], [0, 180]).flatten()
    hue = int(hist.argmax())
    if hue < 8 or hue >= 168:
        return "Rouge"
    if hue < 20:
        return "Orange"
    if hue < 33:
        return "Jaune"
    if hue < 85:
        return "Vert"
    if hue < 130:
        return "Bleu"
    if hue < 150:
        return "Violet"
    return "Rose"


def point_in_polygon(x_norm: float, y_norm: float, poly: list) -> bool:
    """Test point-in-polygon (ray casting) sur coordonnées normalisées 0-1."""
    if not poly or len(poly) < 3:
        return True
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > y_norm) != (yj > y_norm)) and \
           (x_norm < (xj - xi) * (y_norm - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


@dataclass
class VehicleROI:
    """Crop véhicule UNIQUE, partagé par TOUS les moteurs ANPR.

    Le crop est extrait une seule fois (vue numpy, zéro copie), le JPEG
    encodé une seule fois par qualité demandée.
    """
    owner: dict                 # détection YOLO source (dict legacy)
    bbox: tuple                 # bbox paddée (x1, y1, x2, y2) dans l'image
    crop: object                # numpy ndarray BGR (vue sur ctx.image)
    track_id: Optional[int] = None
    _jpeg: dict = field(default_factory=dict, repr=False)
    _data_uri: dict = field(default_factory=dict, repr=False)

    def jpeg(self, quality: int = 85) -> Optional[bytes]:
        q = int(quality)
        if q not in self._jpeg:
            import cv2
            if self.crop is None or getattr(self.crop, "size", 0) == 0:
                self._jpeg[q] = None
            else:
                ok, buf = cv2.imencode(".jpg", self.crop,
                                       [cv2.IMWRITE_JPEG_QUALITY, q])
                self._jpeg[q] = buf.tobytes() if ok else None
        return self._jpeg[q]

    def jpeg_data_uri(self, max_width: int = 1280, quality: int = 85):
        key = (int(max_width), int(quality))
        if key not in self._data_uri:
            self._data_uri[key] = encode_jpeg_data_uri(self.crop, max_width, quality)
        return self._data_uri[key]


@dataclass
class FrameContext:
    """Représentation unique d'une frame traversant le pipeline.

    Tous les stages et plugins reçoivent CE même objet — plus aucune copie
    indépendante de la frame n'est autorisée.
    """
    camera_id: str
    image: object = None                # numpy ndarray BGR décodé UNE fois
    timestamp: float = field(default_factory=time.time)
    fps: float = 0.0
    frame_id: int = 0

    detections: list = field(default_factory=list)   # dicts legacy YOLO
    tracks: list = field(default_factory=list)       # dicts {track_id,label,bbox,confidence}
    vehicle_rois: list = field(default_factory=list)  # list[VehicleROI]
    plates: list = field(default_factory=list)

    motion_pct: float = 0.0
    overlay_boxes: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)         # jpeg/data-uri partagés
    metadata: dict = field(default_factory=dict)
    anpr_quality: Optional[dict] = None
    anpr_state: Optional[dict] = None

    @property
    def width(self) -> int:
        return int(self.image.shape[1]) if self.image is not None else 0

    @property
    def height(self) -> int:
        return int(self.image.shape[0]) if self.image is not None else 0

    def jpeg_data_uri(self, max_width: int = 1280, quality: int = 85):
        """Data-URI JPEG de la frame complète — encodé UNE fois par config."""
        key = ("data_uri", int(max_width), int(quality))
        if key not in self.cache:
            self.cache[key] = encode_jpeg_data_uri(self.image, max_width, quality)
        return self.cache[key]

    def as_plugin_frame(self, timestamp_iso: Optional[str] = None):
        """Vue ``plugin_manager.Frame`` sur CE contexte — zéro copie.

        Le buffer numpy et le cache JPEG sont partagés : appeler ``.jpeg(q)``
        sur la Frame retournée écrit dans ``self.cache`` (clé ``("plugin_jpeg", q)``),
        donc plusieurs plugins consommant la même Frame ne déclenchent
        qu'un seul ``cv2.imencode``. Utilisé par ``downstream.run_downstream``
        pour dispatcher au PluginBus sans dupliquer la mémoire.
        """
        from plugin_manager.interfaces import Frame as _PMFrame
        ts = timestamp_iso or ""
        f = _PMFrame(
            camera_id=self.camera_id,
            timestamp=ts,
            numpy_bgr=self.image,
            width=self.width,
            height=self.height,
        )
        # Partage du cache JPEG : la Frame écrit dans son propre dict,
        # mais le proxy ci-dessous route vers self.cache pour éviter
        # tout ré-encodage entre stages.
        shared = self.cache
        def _shared_jpeg(quality: int = 85, _self=f):
            q = int(quality)
            key = ("plugin_jpeg", q)
            if key not in shared:
                img = _self.numpy_bgr
                if img is None or getattr(img, "size", 0) == 0:
                    shared[key] = None
                else:
                    import cv2
                    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
                    shared[key] = buf.tobytes() if ok else None
            return shared[key]
        f.jpeg = _shared_jpeg  # type: ignore[method-assign]
        return f

    def to_legacy_result(self) -> dict:
        """Forme dict historique consommée par le downstream et les tests."""
        return {
            "detections": self.detections,
            "plates": self.plates,
            "motion_pct": self.motion_pct,
            "_img_bgr": self.image,
            "timings": self.timings,
            "overlay_boxes": self.overlay_boxes,
            "counts": self.counts,
            "anpr_quality": self.anpr_quality,
            "anpr_state": self.anpr_state,
            "_ctx": self,
        }
