"""Tests v1.0-rc4.5 · Phase 1 · Root cause Go2RTC (flux lents/neige).

Vérifications par inspection statique du code source (pas de Go2RTC live requis) :
- streaming.py force `#transport=tcp#timeout=15` sur toute source RTSP nouvelle
- video_engine.py DEFAULT_CONFIG utilise hd_preview_width=1280 (pas 0=native)
- deploy-app/go2rtc.yaml expose la section ffmpeg.rtsp avec -rtsp_transport tcp
"""
import re


def test_streaming_appends_transport_tcp_to_rtsp_source():
    """register_camera_stream doit suffixer #transport=tcp#timeout=15 sur les
    URLs RTSP qui n'ont pas déjà un fragment #transport=."""
    with open("/app/backend/streaming.py") as f:
        src = f.read()
    # La chaîne doit apparaître dans le code
    assert "#transport=tcp#timeout=15" in src, (
        "streaming.py ne suffixe pas la source RTSP avec #transport=tcp — "
        "risque d'artefacts UDP sur LAN imparfait"
    )
    # Doit être conditionné sur rtsp:// (pas rtmp/http)
    assert 'startswith("rtsp://")' in src or 'startswith(\'rtsp://\')' in src, (
        "L'ajout doit être conditionné sur les URLs rtsp://"
    )
    # Doit éviter le double-suffixe si l'URL contient déjà #transport=
    assert '"#transport=" not in rtsp_url' in src, (
        "Le code doit éviter d'ajouter #transport=tcp si déjà présent"
    )


def test_streaming_uses_rtsp_source_variable_in_desired_and_put():
    """La variable rtsp_source (avec fragment) doit être utilisée dans le dict
    `desired` ET dans le PUT vers Go2RTC — sinon on continue à envoyer l'URL
    brute."""
    with open("/app/backend/streaming.py") as f:
        src = f.read()
    # Recherche le bloc `desired = {` et confirme name: rtsp_source
    m = re.search(r"desired\s*=\s*\{[^}]+\}", src, re.DOTALL)
    assert m, "Le bloc `desired = { ... }` doit exister dans register_camera_stream"
    block = m.group(0)
    assert "name: rtsp_source" in block, (
        "Le dict `desired` doit référencer rtsp_source (avec fragment), pas rtsp_url brute"
    )
    # Le PUT doit également utiliser rtsp_source
    assert '"src", rtsp_source' in src, (
        "Le PUT vers Go2RTC doit envoyer rtsp_source (avec fragment)"
    )


def test_video_engine_hd_preview_width_defaults_to_1280():
    """Le default MJPEG HD doit être 1280 (pas 0=native) pour éviter CPU 4K."""
    from video_engine import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["hd_preview_width"] == 1280, (
        f"hd_preview_width doit valoir 1280 par défaut, pas "
        f"{DEFAULT_CONFIG['hd_preview_width']} — sinon transcoding MJPEG "
        f"CPU-heavy sur 4K"
    )


def test_go2rtc_yaml_declares_ffmpeg_rtsp_tcp_template():
    """deploy-app/go2rtc.yaml doit surcharger le template ffmpeg.rtsp pour
    forcer -rtsp_transport tcp sur les transcodages internes Go2RTC."""
    with open("/app/deploy-app/go2rtc.yaml") as f:
        y = f.read()
    assert "ffmpeg:" in y, "Section `ffmpeg:` absente"
    # Le template rtsp doit être présent
    assert "rtsp:" in y and "-rtsp_transport tcp" in y, (
        "Le template ffmpeg.rtsp doit forcer -rtsp_transport tcp"
    )
    # Doit contenir aussi les autres flags critiques
    assert "-rtsp_flags prefer_tcp" in y, "Flag -rtsp_flags prefer_tcp manquant"
    assert "-timeout 15000000" in y, "Timeout socket 15s manquant"
    assert "-fflags nobuffer" in y, "-fflags nobuffer manquant (latence)"
    assert "-flags low_delay" in y, "-flags low_delay manquant (latence)"


def test_go2rtc_yaml_uses_input_placeholder():
    """Le template ffmpeg.rtsp doit utiliser le placeholder {input} de Go2RTC
    (sinon l'URL de la caméra n'est pas injectée)."""
    with open("/app/deploy-app/go2rtc.yaml") as f:
        y = f.read()
    assert "{input}" in y, (
        "Le template ffmpeg.rtsp doit contenir {input} — placeholder Go2RTC "
        "remplacé à l'exécution par l'URL de la source"
    )
