"""v0.7.e · Wave D + Wave E — tests de non-régression.

Wave D (Camera API / ONVIF) :
  1. Le bundle WSDL local contient tous les fichiers requis (offline).
  2. ``ONVIFDriver.get_capabilities`` sonde audio, events, snapshots,
     multi_stream, codec_h265, ptz_presets.

Wave E (Timeline Reolink + miniatures + boucle vidéo) :
  3. La galerie véhicule expose les 3 crops distincts (frame + vehicle + plate).
  4. La timeline LiveView mappe la palette demandée par l'utilisateur.
  5. Le lecteur Recordings passe au segment suivant à ``onEnded`` (comportement
     Reolink-like).
"""
from __future__ import annotations

import os
import re
from pathlib import Path


os.environ["TESTING"] = "1"


# ═══════════════════════════════════════════════════════════════════
# Wave D
# ═══════════════════════════════════════════════════════════════════
class TestWsdlBundle:
    """v0.7.c avait embarqué le bundle WSDL local. On garantit que les
    fichiers ONVIF critiques restent présents."""

    REQUIRED = [
        "devicemgmt.wsdl", "media.wsdl", "ptz.wsdl", "imaging.wsdl",
        "events.wsdl", "analytics.wsdl", "accesscontrol.wsdl",
        "common.xsd", "onvif.xsd",
    ]

    def test_all_required_wsdl_present(self):
        base = Path(__file__).resolve().parents[1] / "wsdl"
        assert base.is_dir(), f"Bundle WSDL absent : {base}"
        missing = [f for f in self.REQUIRED if not (base / f).exists()]
        assert not missing, f"WSDL manquants : {missing}"

    def test_devicemgmt_wsdl_contains_getcapabilities(self):
        p = Path(__file__).resolve().parents[1] / "wsdl" / "devicemgmt.wsdl"
        assert "GetCapabilities" in p.read_text()


class TestOnvifCapabilitiesProbing:
    def test_get_capabilities_probes_audio(self):
        import inspect
        from drivers import onvif_driver
        src = inspect.getsource(onvif_driver.ONVIFDriver.get_capabilities)
        assert "GetAudioSources" in src
        assert "GetAudioOutputs" in src
        assert "two_way_audio" in src

    def test_get_capabilities_probes_events(self):
        import inspect
        from drivers import onvif_driver
        src = inspect.getsource(onvif_driver.ONVIFDriver.get_capabilities)
        assert "create_events_service" in src

    def test_get_capabilities_probes_snapshot_uri(self):
        import inspect
        from drivers import onvif_driver
        src = inspect.getsource(onvif_driver.ONVIFDriver.get_capabilities)
        assert "GetSnapshotUri" in src

    def test_get_capabilities_detects_multi_stream_and_h265(self):
        import inspect
        from drivers import onvif_driver
        src = inspect.getsource(onvif_driver.ONVIFDriver.get_capabilities)
        assert "multi_stream" in src
        assert "codec_h265" in src

    def test_get_capabilities_probes_ptz_presets(self):
        import inspect
        from drivers import onvif_driver
        src = inspect.getsource(onvif_driver.ONVIFDriver.get_capabilities)
        assert "GetPresets" in src or "ptz_presets" in src


class TestIdempotentCameraUpdate:
    """Preview stable pendant une modification caméra : register_camera_stream
    est idempotent depuis v0.5.6 P0-3 — on garantit que ce contrat tient."""

    def test_register_camera_stream_is_idempotent(self):
        import inspect
        from streaming import register_camera_stream
        src = inspect.getsource(register_camera_stream)
        # Doit contenir un short-circuit "skip" quand la config go2rtc est identique
        assert "identical" in src.lower() or "all_match" in src, \
            "register_camera_stream doit skipper les updates identiques (preview stable)"


# ═══════════════════════════════════════════════════════════════════
# Wave E — audit statique du frontend
# ═══════════════════════════════════════════════════════════════════
FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"


class TestVehicleGalleryHasThreeCrops:
    def test_gallery_uses_all_three_kinds(self):
        p = FRONTEND_SRC / "pages" / "Vehicles.jsx"
        content = p.read_text()
        # Recherche des 3 kinds attendus dans la galerie
        assert 'kind=frame' in content, "Kind=frame absent — photo complète manquante"
        assert 'kind=vehicle' in content, "Kind=vehicle absent — crop véhicule manquant"
        assert 'kind=plate' in content, "Kind=plate absent — crop plaque manquant"

    def test_gallery_has_data_testids_for_three_crops(self):
        p = FRONTEND_SRC / "pages" / "Vehicles.jsx"
        content = p.read_text()
        assert 'gallery-frame-link-' in content
        assert 'gallery-vehicle-thumb-' in content
        assert 'gallery-plate-link-' in content
        assert 'gallery-plate-thumb-' in content


class TestTimelinePaletteMatchesRequest:
    """Palette demandée : 🟦 Personne / 🟩 Voiture / 🟨 Moto / 🟧 Camion /
    🟪 Bus / 🟥 Animal / 🟫 Vélo."""

    def test_person_is_blue(self):
        p = FRONTEND_SRC / "pages" / "LiveView.jsx"
        content = p.read_text()
        m = re.search(r'person:\s*\{[^}]*color:\s*"([^"]+)"', content)
        assert m, "Entrée 'person' introuvable dans EVENT_KIND_META"
        assert m.group(1) == "#0044FF", f"Personne doit être 🟦 bleu (#0044FF), reçu {m.group(1)}"

    def test_car_is_green(self):
        p = FRONTEND_SRC / "pages" / "LiveView.jsx"
        content = p.read_text()
        m = re.search(r'car:\s*\{[^}]*color:\s*"([^"]+)"', content)
        assert m.group(1) == "#00E676"

    def test_motorbike_is_yellow(self):
        p = FRONTEND_SRC / "pages" / "LiveView.jsx"
        content = p.read_text()
        m = re.search(r'motorbike:\s*\{[^}]*color:\s*"([^"]+)"', content)
        assert m.group(1) == "#FFB800"

    def test_truck_is_orange(self):
        p = FRONTEND_SRC / "pages" / "LiveView.jsx"
        content = p.read_text()
        m = re.search(r'truck:\s*\{[^}]*color:\s*"([^"]+)"', content)
        assert m.group(1) == "#FF6600"

    def test_bus_is_purple(self):
        p = FRONTEND_SRC / "pages" / "LiveView.jsx"
        content = p.read_text()
        m = re.search(r'bus:\s*\{[^}]*color:\s*"([^"]+)"', content)
        assert m.group(1) == "#9333EA"

    def test_animal_is_red(self):
        p = FRONTEND_SRC / "pages" / "LiveView.jsx"
        content = p.read_text()
        m = re.search(r'animal:\s*\{[^}]*color:\s*"([^"]+)"', content)
        assert m.group(1) == "#FF3333"

    def test_bicycle_is_brown(self):
        p = FRONTEND_SRC / "pages" / "LiveView.jsx"
        content = p.read_text()
        m = re.search(r'bicycle:\s*\{[^}]*color:\s*"([^"]+)"', content)
        assert m.group(1) == "#8B4513"


class TestRecordingsAutoNextSegment:
    def test_video_has_onended_handler(self):
        p = FRONTEND_SRC / "pages" / "Recordings.jsx"
        content = p.read_text()
        assert "onEnded=" in content
        assert "segments[idx + 1]" in content or "segments.findIndex" in content
