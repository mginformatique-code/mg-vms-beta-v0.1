"""MG-VMS — Enregistrement vidéo RÉEL (FFmpeg → segments MP4 sur disque).

Chaque caméra avec `record_enabled` est enregistrée en continu depuis go2rtc
(RTSP) en segments MP4 copiés sans réencodage. Les fichiers sont indexés en
base (timeline réelle), avec rétention automatique.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import db

logger = logging.getLogger("recorder")

RECORDINGS_DIR = Path(os.environ.get("RECORDINGS_DIR", "/app/recordings"))
GO2RTC_RTSP = os.environ.get("GO2RTC_RTSP", "rtsp://127.0.0.1:8554")
SEGMENT_SECONDS = int(os.environ.get("RECORD_SEGMENT_SECONDS", "120"))
RETENTION_DAYS = int(os.environ.get("RECORD_RETENTION_DAYS", "7"))
MIN_FREE_GB = float(os.environ.get("RECORD_MIN_FREE_GB", "2"))

_processes: dict[str, asyncio.subprocess.Process] = {}
_pools_cache: dict = {}  # id -> {path, max_size_gb, enabled, ...}
_stderr_logs: dict[str, Path] = {}  # camera_id -> chemin du log stderr ffmpeg (dernier restart)


async def _load_pools() -> None:
    """Charge la liste des pools de stockage depuis les settings."""
    doc = await db.settings.find_one({"key": "storage_pools"}, {"_id": 0})
    pools = list((doc or {}).get("value", []) or [])
    _pools_cache.clear()
    for p in pools:
        _pools_cache[p["id"]] = p


def _cam_target_dir(cam: dict) -> Path:
    """Détermine le dossier cible : pool désigné par la caméra, sinon RECORDINGS_DIR."""
    pool_id = cam.get("storage_pool_id") or ""
    pool = _pools_cache.get(pool_id) if pool_id else None
    if pool and pool.get("enabled") and Path(pool["path"]).exists():
        d = Path(pool["path"]) / cam["id"]
    else:
        d = RECORDINGS_DIR / cam["id"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cam_dir(camera_id: str) -> Path:
    d = RECORDINGS_DIR / camera_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _cam_all_dirs(camera_id: str) -> list[Path]:
    """Retourne tous les dossiers susceptibles de contenir des segments d'une caméra
    (pool actif + fallback RECORDINGS_DIR)."""
    dirs = [RECORDINGS_DIR / camera_id]
    for p in _pools_cache.values():
        candidate = Path(p["path"]) / camera_id
        if candidate.exists():
            dirs.append(candidate)
    return dirs


async def _start_ffmpeg(cam: dict) -> None:
    camera_id = cam["id"]
    out_dir = _cam_target_dir(cam)
    out = out_dir / "%Y%m%d_%H%M%S.mp4"
    # P0-fix · Connexion RTSP mutualisée : certaines caméras (Reolink
    # notamment) refusent une 2e connexion RTSP concurrente — le recorder
    # ouvrait sa propre connexion en plus de celle de l'IA (frame_source),
    # provoquant des timeouts/déconnexions en boucle. Sauf stream_mode=
    # direct_rtsp (contournement explicite de Go2RTC), le recorder lit
    # maintenant depuis le relais Go2RTC déjà ouvert (1 seule connexion
    # réelle vers la caméra, partagée avec l'IA/preview/statut) — copie
    # brute, zéro transcodage, même qualité qu'une lecture directe.
    from streaming import _build_rtsp_url, _is_direct_rtsp, _stream_name
    if _is_direct_rtsp(cam):
        src = _build_rtsp_url(cam)
    else:
        src = f"{GO2RTC_RTSP}/{_stream_name(camera_id)}"
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        # v3.1.9 · `+genpts` régénère des PTS propres côté démuxeur — mitigation
        # ffmpeg standard face à un flux source avec des discontinuités de
        # timestamps (caméra/go2rtc instable), qui sinon peut faire dérailler
        # le muxer `segment` en aval (durée de segment délirante ou rollover
        # prématuré — voir _probe_duration). N'affecte pas la copie des
        # données vidéo/audio elles-mêmes (`-c copy` reste sans réencodage).
        "-fflags", "+genpts",
        "-i", src,
        "-c", "copy", "-f", "segment",
        "-segment_time", str(SEGMENT_SECONDS),
        "-reset_timestamps", "1", "-strftime", "1",
        str(out),
    ]
    # v3.1.4 · stderr n'était jamais capturé (DEVNULL) — quand ffmpeg crashait
    # (observé : caméra plantée peu après démarrage, flux go2rtc corrompu),
    # le watchdog du recorder_loop savait QUE le process était mort mais
    # jamais POURQUOI. Tronqué à chaque (re)démarrage : on ne garde que la
    # dernière tentative, pas un historique qui grossirait indéfiniment.
    stderr_log = out_dir / ".ffmpeg-stderr.log"
    stderr_f = open(stderr_log, "wb")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr_f,
            close_fds=True, start_new_session=True)
    finally:
        stderr_f.close()  # le enfant a déjà son propre descripteur dupliqué
    _processes[camera_id] = proc
    _stderr_logs[camera_id] = stderr_log
    logger.info("Enregistrement démarré : caméra %s (pid %s) → %s", camera_id, proc.pid, out_dir)


def _probe_duration(path: Path) -> float:
    """Durée fiable d'un segment enregistré.

    v3.1.9 · `format.duration` seul peut être délirant sur un flux source
    avec des discontinuités de timestamps (voir commentaire `_index_segments`
    plus bas) — confirmé en prod : un segment de 1.6 Mo dont le stream VIDÉO
    ne fait que 0.05s de contenu réel rapportait `format.duration=65678s`
    (18h). Le clamp `MAX_PLAUSIBLE` (3× la durée cible) empêchait déjà les
    cas les plus extrêmes de polluer l'index indéfiniment, mais retombait
    quand même sur une valeur (le plafond lui-même) bien plus grande que le
    contenu réel de CES segments-là — assez pour que des dizaines de
    segments quasi-vides (ffmpeg qui redémarre en boucle sur un flux caméra
    instable) se chevauchent tous sur la même fenêtre de plusieurs minutes
    dans l'index Mongo. On priorise donc la durée du STREAM VIDÉO lui-même
    quand ffprobe sait la lire — c'est le signal le plus fiable de ce qui
    est réellement décodable, contrairement à la métadonnée `format`
    globale qui peut être écrite n'importe comment par le muxer segment
    face à des PTS discontinus."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-show_entries", "stream=codec_type,duration",
             "-of", "json", str(path)],
            capture_output=True, timeout=10)
        data = json.loads(out.stdout or "{}")
        fmt_duration = float((data.get("format") or {}).get("duration", 0) or 0)
        video_durations = [
            float(s["duration"]) for s in (data.get("streams") or [])
            if s.get("codec_type") == "video" and s.get("duration") not in (None, "N/A")
        ]
        if video_durations:
            vd = max(video_durations)
            if vd > 0:
                return vd
        return fmt_duration
    except Exception:
        return 0.0


async def _event_flags(camera_id: str, start_iso: str, end_iso: str) -> dict:
    """Corrèle les événements IA/mouvement réels avec un segment."""
    evts = await db.events.find(
        {"camera_id": camera_id, "timestamp": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0, "type": 1},
    ).to_list(200)
    if not evts:
        return {"has_event": False, "event_type": None, "mode": "continuous", "event_count": 0}
    ai_types = [e["type"] for e in evts if e["type"] != "Mouvement"]
    return {
        "has_event": True,
        "event_type": ai_types[0] if ai_types else "Mouvement",
        "mode": "ai" if ai_types else "motion",
        "event_count": len(evts),
    }


async def _index_segments(cam: dict) -> None:
    """Indexe en base les segments MP4 clos (fichiers réels sur disque).
    Cherche dans tous les répertoires connus pour cette caméra (pool actif + fallback)."""
    all_files: list[Path] = []
    for d in await _cam_all_dirs(cam["id"]):
        all_files.extend(sorted(d.glob("*.mp4")))
    if not all_files:
        return
    all_files.sort(key=lambda p: p.name)
    newest = all_files[-1]
    for f in all_files:
        if f == newest and _processes.get(cam["id"]) and _processes[cam["id"]].returncode is None:
            continue  # segment en cours d'écriture
        if await db.recordings.find_one({"file_path": str(f)}):
            continue
        try:
            start = datetime.strptime(f.stem, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        duration = await asyncio.to_thread(_probe_duration, f)
        if duration <= 0:
            continue
        # v3.1.4 · Un segment `-c copy` nourri par un flux go2rtc avec des
        # discontinuités de timestamps peut produire un MP4 dont les
        # métadonnées de durée sont délirantes (observé : 28h pour 13 Mo,
        # sur un segment cible de SEGMENT_SECONDS=120s) — ffprobe rapporte
        # fidèlement cette valeur corrompue, donc on ne peut pas s'y fier
        # aveuglément : un `end` erroné empoisonne l'index (ce segment se
        # met alors à "couvrir" n'importe quel événement pendant des heures
        # via la requête de plage dans _lookup_recording_for). On clamp à
        # une marge large mais finie autour de la durée cible du segment.
        MAX_PLAUSIBLE = SEGMENT_SECONDS * 3
        if duration > MAX_PLAUSIBLE:
            logger.warning(
                "Durée aberrante ignorée : %s → ffprobe=%.0fs (clampé à %ds) — "
                "probable métadonnée MP4 corrompue (flux source discontinu)",
                f, duration, MAX_PLAUSIBLE)
            duration = MAX_PLAUSIBLE
        end = start + timedelta(seconds=duration)
        flags = await _event_flags(cam["id"], start.isoformat(), end.isoformat())
        # Filtrage par mode d'enregistrement (motion/ai) : purge immédiate si aucun événement
        mode = cam.get("record_mode", "continuous")
        if mode == "motion" and not flags["has_event"]:
            try: f.unlink(missing_ok=True)
            except OSError: pass
            continue
        if mode == "ai" and flags["mode"] != "ai":
            try: f.unlink(missing_ok=True)
            except OSError: pass
            continue
        size_mb = round(f.stat().st_size / 1e6, 1)
        await db.recordings.insert_one({
            "id": str(uuid.uuid4()),
            "camera_id": cam["id"], "camera_name": cam["name"],
            "site_id": cam.get("site_id", ""), "site_name": cam.get("site_name", ""),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration_sec": int(duration),
            "size_mb": size_mb,
            "file_path": str(f),
            "thumbnail": None,
            "storage_pool_id": cam.get("storage_pool_id", ""),
            **flags,
        })


async def _refresh_recent_flags() -> None:
    """Met à jour la corrélation événements des segments récents (2 h)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    recent = await db.recordings.find({"start": {"$gte": since}}, {"_id": 0, "id": 1, "camera_id": 1, "start": 1, "end": 1}).to_list(500)
    for rec in recent:
        flags = await _event_flags(rec["camera_id"], rec["start"], rec["end"])
        await db.recordings.update_one({"id": rec["id"]}, {"$set": flags})


async def _load_retention_config() -> dict:
    """Charge la config rétention depuis la base (surchargée par settings.retention)."""
    doc = await db.settings.find_one({"key": "retention"}, {"_id": 0})
    val = (doc or {}).get("value") or {}
    return {
        "retention_days": int(val.get("retention_days", RETENTION_DAYS)),
        "min_free_gb": float(val.get("min_free_gb", MIN_FREE_GB)),
        "max_disk_pct": float(val.get("max_disk_pct", 85.0)),
    }


async def _apply_retention() -> dict:
    """Purge : (1) par âge, puis (2) par quota disque en supprimant les plus anciens.
    Retourne un rapport de purge."""
    cfg = await _load_retention_config()
    deleted_age = 0
    freed_bytes_age = 0

    # 1) Par âge
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg["retention_days"])).isoformat()
    old = await db.recordings.find(
        {"start": {"$lt": cutoff}, "file_path": {"$ne": None}},
        {"_id": 0, "id": 1, "file_path": 1, "size_bytes": 1},
    ).to_list(5000)
    for rec in old:
        try:
            p = Path(rec["file_path"])
            if p.exists():
                freed_bytes_age += p.stat().st_size
                p.unlink(missing_ok=True)
                deleted_age += 1
        except OSError:
            pass
    if old:
        await db.recordings.delete_many({"id": {"$in": [r["id"] for r in old]}})

    # 2) Par quota disque : tant que free < min_free OR usage > max_pct, supprimer les plus anciens
    deleted_quota = 0
    freed_bytes_quota = 0
    while True:
        du = shutil.disk_usage(RECORDINGS_DIR)
        free_gb = du.free / 1e9
        used_pct = 100.0 * du.used / du.total
        if free_gb >= cfg["min_free_gb"] and used_pct <= cfg["max_disk_pct"]:
            break
        oldest = await db.recordings.find_one(
            {"file_path": {"$ne": None}},
            {"_id": 0, "id": 1, "file_path": 1},
            sort=[("start", 1)],
        )
        if not oldest:
            break  # rien à supprimer
        try:
            p = Path(oldest["file_path"])
            if p.exists():
                freed_bytes_quota += p.stat().st_size
                p.unlink(missing_ok=True)
        except OSError:
            pass
        await db.recordings.delete_one({"id": oldest["id"]})
        deleted_quota += 1
        if deleted_quota > 5000:
            logger.warning("Purge quota interrompue à 5000 segments — reprise au prochain cycle")
            break

    report = {
        "deleted_by_age": deleted_age,
        "deleted_by_quota": deleted_quota,
        "freed_gb": round((freed_bytes_age + freed_bytes_quota) / 1e9, 3),
        "retention_days": cfg["retention_days"],
        "min_free_gb": cfg["min_free_gb"],
        "max_disk_pct": cfg["max_disk_pct"],
    }
    if deleted_age or deleted_quota:
        logger.info("Rétention : %d supprimés par âge, %d par quota, %.2f Go libérés",
                    deleted_age, deleted_quota, report["freed_gb"])
    return report


async def get_retention_status() -> dict:
    """Snapshot de l'état de la rétention pour l'UI."""
    cfg = await _load_retention_config()
    du = shutil.disk_usage(RECORDINGS_DIR)
    total = await db.recordings.count_documents({})
    oldest = await db.recordings.find_one({}, {"_id": 0, "start": 1}, sort=[("start", 1)])
    newest = await db.recordings.find_one({}, {"_id": 0, "start": 1}, sort=[("start", -1)])
    # Somme des tailles des enregistrements
    agg = await db.recordings.aggregate([{"$group": {"_id": None, "total_size": {"$sum": "$size_bytes"}}}]).to_list(1)
    total_size = (agg[0]["total_size"] if agg else 0) or 0
    return {
        "config": cfg,
        "disk": {
            "total_gb": round(du.total / 1e9, 2),
            "used_gb": round(du.used / 1e9, 2),
            "free_gb": round(du.free / 1e9, 2),
            "used_pct": round(100.0 * du.used / du.total, 1),
        },
        "recordings": {
            "count": total,
            "size_gb": round(total_size / 1e9, 3),
            "oldest": oldest.get("start") if oldest else None,
            "newest": newest.get("start") if newest else None,
        },
    }


async def get_recorder_health(camera_id: str | None = None) -> dict:
    """Retourne l'état des enregistreurs par caméra (P1 stabilisation).

    Pour chaque caméra `record_enabled`:
      - ffmpeg_alive: bool (PID vivant ?)
      - pid: int | None
      - last_segment_at: ISO du dernier segment indexé
      - last_segment_age_sec: secondes écoulées
      - expected_segment_sec: durée attendue d'un segment (config)
      - gap_detected: True si aucun segment depuis 3× la durée attendue
      - continuity_24h: analyse des trous des 24 dernières heures
    """
    q = {"record_enabled": True}
    if camera_id:
        q["id"] = camera_id
    cams = await db.cameras.find(q, {"_id": 0}).to_list(500)
    now = datetime.now(timezone.utc)
    since_24h = (now - timedelta(hours=24)).isoformat()
    results = []
    for cam in cams:
        cid = cam["id"]
        proc = _processes.get(cid)
        pid = getattr(proc, "pid", None) if proc else None
        alive = bool(proc and proc.returncode is None)

        # PID vivant côté OS ?
        pid_alive_os = False
        if pid:
            try:
                os.kill(pid, 0)
                pid_alive_os = True
            except (OSError, ProcessLookupError):
                pid_alive_os = False

        # Dernier segment indexé
        last = await db.recordings.find_one(
            {"camera_id": cid}, {"_id": 0, "start": 1, "end": 1},
            sort=[("start", -1)],
        )
        last_start = last.get("start") if last else None
        last_end = last.get("end") if last else None
        age_sec = None
        if last_end:
            try:
                dt_end = datetime.fromisoformat(last_end.replace("Z", "+00:00"))
                age_sec = int((now - dt_end).total_seconds())
            except Exception:
                age_sec = None

        # Gap détecté : si record_mode continu, on attend un segment toutes les ~SEGMENT_SECONDS.
        # Si aucun segment depuis 3× cette durée alors qu'un ffmpeg tourne, alerte.
        record_mode = cam.get("record_mode", "continuous")
        gap_detected = False
        if record_mode == "continuous" and age_sec is not None:
            gap_detected = age_sec > (3 * SEGMENT_SECONDS)

        # Analyse continuité 24h (nombre de segments + couverture temporelle)
        segs = await db.recordings.find(
            {"camera_id": cid, "start": {"$gte": since_24h}},
            {"_id": 0, "start": 1, "end": 1, "duration_sec": 1},
        ).sort("start", 1).to_list(2000)
        total_duration = sum(s.get("duration_sec", 0) or 0 for s in segs)
        # Détection des trous > 2× SEGMENT_SECONDS entre segments consécutifs
        gaps = []
        for i in range(1, len(segs)):
            try:
                prev_end = datetime.fromisoformat(segs[i - 1]["end"].replace("Z", "+00:00"))
                cur_start = datetime.fromisoformat(segs[i]["start"].replace("Z", "+00:00"))
                gap = (cur_start - prev_end).total_seconds()
                if gap > 2 * SEGMENT_SECONDS:
                    gaps.append({
                        "start": segs[i - 1]["end"],
                        "end": segs[i]["start"],
                        "duration_sec": int(gap),
                    })
            except Exception:
                continue
        coverage_pct = round(100.0 * total_duration / (24 * 3600), 1) if record_mode == "continuous" else None

        results.append({
            "camera_id": cid,
            "camera_name": cam.get("name"),
            "record_enabled": True,
            "record_mode": record_mode,
            "ffmpeg_alive": alive,
            "pid_alive_os": pid_alive_os,
            "pid": pid,
            "last_segment_start": last_start,
            "last_segment_end": last_end,
            "last_segment_age_sec": age_sec,
            "expected_segment_sec": SEGMENT_SECONDS,
            "gap_detected": gap_detected,
            "continuity_24h": {
                "segments": len(segs),
                "recorded_seconds": total_duration,
                "coverage_pct": coverage_pct,
                "gaps": gaps[:20],
                "gap_count": len(gaps),
            },
        })
    return {
        "cameras": results,
        "generated_at": now.isoformat(),
        "segment_seconds": SEGMENT_SECONDS,
    }



async def stop_all_recorders() -> None:
    """Termine proprement tous les ffmpeg enregistreurs (utilisé au shutdown)."""
    for cam_id, proc in list(_processes.items()):
        try:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    proc.kill()
        except ProcessLookupError:
            pass
        _processes.pop(cam_id, None)


async def sweep_orphan_recorders() -> None:
    """Au démarrage : tue les ffmpeg orphelins (PPID=1) qui enregistrent
    encore une caméra ; évite l'accumulation après un redémarrage brutal."""
    try:
        out = await asyncio.create_subprocess_exec(
            "pgrep", "-af", "ffmpeg.*cam_",
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        stdout, _ = await out.communicate()
    except FileNotFoundError:
        return
    known_ids = {c["id"] for c in await db.cameras.find({}, {"_id": 0, "id": 1}).to_list(2000)}
    for line in stdout.decode(errors="ignore").splitlines():
        try:
            pid_str, cmd = line.split(" ", 1)
            pid = int(pid_str)
        except ValueError:
            continue
        # ne tue que les processus dont le camera_id n'existe plus, ou tous ceux
        # sans parent (adoptés par init) — ils sont forcément des orphelins d'un ancien uvicorn.
        try:
            with open(f"/proc/{pid}/status") as f:
                ppid = next((int(l.split()[1]) for l in f if l.startswith("PPid:")), None)
        except OSError:
            continue
        if ppid != 1:
            continue  # rattaché à uvicorn actuel : laissé intact
        import re as _re
        match = _re.search(r"cam_([0-9a-f-]{36})", cmd)
        cam_id = match.group(1) if match else None
        if cam_id and cam_id in known_ids:
            # orphelin mais pour une caméra encore active : le recorder_loop va relancer un nouveau ffmpeg,
            # on tue quand même l'ancien pour éviter le double-enregistrement
            pass
        try:
            os.kill(pid, 9)
            logger.info("ffmpeg orphelin tué (pid=%s, cam=%s)", pid, cam_id)
        except OSError:
            pass


async def recorder_loop() -> None:
    """Boucle superviseur : démarre/répare les enregistreurs et indexe les segments."""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg introuvable — enregistrement désactivé")
        return
    await asyncio.sleep(10)  # laisse go2rtc/flux démarrer
    tick = 0
    while True:
        try:
            cfg = await _load_retention_config()
            free_gb = shutil.disk_usage(RECORDINGS_DIR).free / 1e9
            if free_gb < cfg["min_free_gb"]:
                if _processes:
                    logger.error("Espace disque insuffisant (%.1f Go libres) — enregistrement suspendu", free_gb)
                    for cam_id, proc in list(_processes.items()):
                        if proc.returncode is None:
                            proc.terminate()
                    _processes.clear()
                await _apply_retention()
                await asyncio.sleep(60)
                continue
            cams = await db.cameras.find({"record_enabled": True}, {"_id": 0}).to_list(500)
            # Filtre `record_mode = off` (l'utilisateur peut désactiver via mode sans toucher record_enabled)
            cams = [c for c in cams if c.get("record_mode", "continuous") != "off"]
            await _load_pools()  # rafraîchit les pools de stockage à chaque cycle
            active_ids = set()
            for cam in cams:
                active_ids.add(cam["id"])
                proc = _processes.get(cam["id"])
                if proc is None or proc.returncode is not None:
                    # Watchdog FFmpeg (P1) — trace la reprise dans diagnostics_events
                    if proc is not None and proc.returncode is not None:
                        stderr_tail = ""
                        log_path = _stderr_logs.get(cam["id"])
                        if log_path is not None:
                            try:
                                stderr_tail = log_path.read_text(errors="replace")[-2000:].strip()
                            except OSError:
                                pass
                        logger.warning(
                            "recorder.watchdog : ffmpeg mort pour %s (rc=%s) — relance auto%s",
                            cam["id"], proc.returncode,
                            f" — stderr: {stderr_tail}" if stderr_tail else " (stderr vide)",
                        )
                        try:
                            from diagnostics import record_disconnect
                            await record_disconnect(
                                cam,
                                f"ffmpeg process died (rc={proc.returncode}) — restart auto",
                                {"pid": getattr(proc, "pid", None), "returncode": proc.returncode,
                                 "source": "recorder.watchdog", "stderr_tail": stderr_tail},
                            )
                        except Exception:
                            logger.exception("recorder.watchdog record_disconnect failed")
                    await _start_ffmpeg(cam)
                await _index_segments(cam)
            # stoppe les enregistreurs des caméras désactivées/supprimées
            for cam_id, proc in list(_processes.items()):
                if cam_id not in active_ids and proc.returncode is None:
                    proc.terminate()
                    _processes.pop(cam_id, None)
                    logger.info("Enregistrement arrêté : caméra %s", cam_id)
            tick += 1
            if tick % 4 == 0:
                await _refresh_recent_flags()
            if tick % 20 == 0:
                await _apply_retention()
        except Exception:
            logger.exception("recorder_loop : erreur, reprise dans 30s")
        await asyncio.sleep(30)
