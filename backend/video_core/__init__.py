"""MG-VMS · Video Core v3 · Moteur vidéo UNIQUE.

Architecture cible :

    CAMERA RTSP ─► RtspSource (PyAV, tcp, no-transcode, single connection)
                   │
                   ├─► Recorder subscribers  (segments MP4, ffmpeg -c copy)
                   ├─► AI subscribers        (frames décodées, GPU si dispo)
                   └─► WebRTC subscribers    (RTP H264 passthrough via aiortc)

Une caméra = UNE connexion RTSP amont, plusieurs consommateurs internes via
distribution asyncio. Zéro go2rtc, zéro MediaMTX, zéro MJPEG interne.

Public API :
    manager = VideoCoreManager.instance()
    await manager.ensure_camera(cam_dict)
    track = await manager.get_h264_track(camera_id)     # aiortc-compatible
    await manager.stop_camera(camera_id)
    stats = await manager.runtime_snapshot(camera_id)
"""
from .manager import VideoCoreManager
from .runtime import runtime_snapshot, upsert_runtime

__all__ = ["VideoCoreManager", "runtime_snapshot", "upsert_runtime"]
