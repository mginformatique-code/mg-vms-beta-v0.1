"""Tests · YoloDetectionProvider natif (pipeline v2)."""
import os
import time
import numpy as np

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_yolo_provider")


def test_yolo_provider_conforms_to_detection_provider_protocol():
    from pipeline_v2.interfaces import DetectionProvider
    from pipeline_v2.providers import YoloDetectionProvider
    p = YoloDetectionProvider()
    assert isinstance(p, DetectionProvider)
    assert p.name == "yolov11"


def test_yolo_provider_no_model_returns_empty_result():
    """Si ai_engine._model n'est pas chargé (early boot), retourne empty."""
    import ai_engine
    from pipeline_v2.interfaces import Frame
    from pipeline_v2.providers import YoloDetectionProvider

    saved_model = ai_engine._model
    ai_engine._model = None
    try:
        p = YoloDetectionProvider()
        frame = Frame(camera_id="c1", image=np.zeros((240, 320, 3), dtype=np.uint8),
                      timestamp=time.time())
        r = p.detect(frame)
        assert r.detections == []
        assert r.provider == "yolov11"
    finally:
        ai_engine._model = saved_model


def test_yolo_provider_ships_bbox_dataclass():
    """Le provider retourne bien des Detection avec bbox = BBox (pas tuple)."""
    import inspect
    from pipeline_v2.providers import YoloDetectionProvider
    src = inspect.getsource(YoloDetectionProvider.detect)
    assert "bbox=BBox(" in src


def test_yolo_provider_with_mocked_model_populates_detections():
    """Test avec un modèle YOLO mocké."""
    import ai_engine
    from pipeline_v2.interfaces import Frame
    from pipeline_v2.providers import YoloDetectionProvider

    class FakeTensor(list):
        def tolist(self): return list(self)

    class FakeBox:
        def __init__(self, xyxy, cls, conf):
            self.xyxy = [FakeTensor(xyxy)]; self.cls = [cls]; self.conf = [conf]

    class FakeResult:
        def __init__(self):
            self.boxes = [FakeBox([100, 100, 300, 300], 2, 0.85)]

    class FakeModel:
        names = {0: "person", 2: "car"}
        def __call__(self, img, verbose=False, conf=0.5):
            return [FakeResult()]

    saved = ai_engine._model
    ai_engine._model = FakeModel()
    try:
        p = YoloDetectionProvider()
        frame = Frame(camera_id="c1", image=np.zeros((480, 640, 3), dtype=np.uint8),
                      timestamp=time.time())
        r = p.detect(frame)
        assert len(r.detections) == 1
        assert r.detections[0].label == "car"
        assert r.detections[0].confidence == 0.85
        assert r.detections[0].bbox.x1 == 100 and r.detections[0].bbox.x2 == 300
        assert r.processing_time_ms > 0
    finally:
        ai_engine._model = saved


def test_pipeline_designer_page_exists():
    from pathlib import Path
    assert Path("/app/frontend/src/pages/PipelineDesigner.jsx").is_file()


def test_camera_control_overlay_component_exists():
    from pathlib import Path
    p = Path("/app/frontend/src/pages/CameraControlOverlay.jsx")
    assert p.is_file()
    src = p.read_text()
    # 5 boutons prévus
    for tid in ("ctrl-spotlight", "ctrl-ir", "ctrl-siren", "ctrl-tts", "ctrl-reboot"):
        assert tid in src
