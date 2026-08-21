"""Tests v1.0-rc4.5 · Phase 1 · Root cause Go2RTC (flux lents/neige).

Vérifications par inspection statique du code source (pas de Go2RTC live requis) :
- streaming.py préfixe la source RTSP par `ffmpeg:` (transport TCP forcé)
- video_engine.py DEFAULT_CONFIG utilise hd_preview_width=1280 (pas 0=native)
- deploy-app/go2rtc.yaml expose la section ffmpeg.rtsp avec -rtsp_transport tcp

v3.1.6 · Les 2 premiers tests testaient l'ANCIEN mécanisme
(`#transport=tcp#timeout=15` suffixé à l'URL) qui a dû être retiré (v2.1,
`Get "tcp": unsupported protocol scheme ""` — go2rtc n'accepte `#transport=`
QUE pour tunneliser RTSP-sur-WebSocket, jamais documenté pour choisir
TCP/UDP, cf. internal/rtsp/README.md du dépôt go2rtc). Root cause confirmée
depuis par un vrai log `bad cseq` (perte de paquets RTP) capturé en prod
— fix correct cette fois : préfixer la source par `ffmpeg:`, dont le
template d'entrée par défaut de go2rtc force déjà TCP (doc go2rtc :
`#input=rtsp/udp` "will change RTSP transport from TCP to UDP+TCP" — donc
le défaut sans override est TCP), sans toucher `_build_rtsp_url` ni risquer
la même erreur de parsing de fragment.
"""
import re


def test_streaming_prefixes_rtsp_source_with_ffmpeg():
    """register_camera_stream doit préfixer la source RTSP par `ffmpeg:` —
    seul mécanisme qui force réellement le transport TCP côté go2rtc pour
    la connexion caméra (le client RTSP natif de go2rtc n'a pas cette
    option, cf. docstring du module)."""
    with open("/app/backend/streaming.py") as f:
        src = f.read()
    assert 'rtsp_source = f"ffmpeg:{rtsp_url}"' in src, (
        "streaming.py ne préfixe plus la source RTSP par ffmpeg: — "
        "risque de repasser par le client RTSP natif go2rtc (transport non garanti)"
    )
    # L'ANCIEN mécanisme (prouvé cassé, cf. docstring) ne doit plus réapparaître
    assert "#transport=tcp#timeout=15" not in src, (
        "Le fragment #transport=tcp#timeout=15 est réapparu — cette syntaxe casse "
        "le client RTSP natif go2rtc (Get \"tcp\": unsupported protocol scheme \"\")"
    )


def test_streaming_uses_rtsp_source_variable_in_desired_and_put():
    """La variable rtsp_source (préfixée ffmpeg:) doit être utilisée dans le
    dict `desired` ET dans le PUT vers Go2RTC — sinon on continue à envoyer
    l'URL brute (client natif, transport non garanti)."""
    with open("/app/backend/streaming.py") as f:
        src = f.read()
    m = re.search(r"desired\s*=\s*\{[^}]+\}", src, re.DOTALL)
    assert m, "Le bloc `desired = { ... }` doit exister dans register_camera_stream"
    block = m.group(0)
    assert "name: rtsp_source" in block, (
        "Le dict `desired` doit référencer rtsp_source (ffmpeg:...), pas rtsp_url brute"
    )
    # Le PUT doit également utiliser rtsp_source (construit manuellement, cf. commentaire
    # anti-double-encodage — pas de tuple ("src", rtsp_source) mais interpolé dans l'URL)
    assert "&src={rtsp_source}" in src, (
        "Le PUT vers Go2RTC doit envoyer rtsp_source (ffmpeg:...)"
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
