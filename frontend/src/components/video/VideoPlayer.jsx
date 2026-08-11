import React, { useEffect, useRef, useState } from "react";
import WHEPPlayer from "@/components/video/WHEPPlayer";
import MJPEGPlayer from "@/components/video/MJPEGPlayer";
import DirectRTSPCard from "@/components/video/DirectRTSPCard";
import Go2RTCPlayer from "@/components/video/Go2RTCPlayer";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;

/**
 * video-pipeline-v2.2 · Dispatcher UNIQUE avec **fallback universel MJPEG**.
 *
 * Chaque pipeline tente son mode natif :
 *   - mediamtx    → WHEPPlayer (WebRTC WHEP)
 *   - mjpeg       → MJPEGPlayer (broker ffmpeg partagé /api/video/{id}/mjpeg)
 *   - direct_rtsp → DirectRTSPCard (pas de preview navigateur, info honnête)
 *   - go2rtc      → Go2RTCPlayer (WebRTC go2rtc, fallback MJPEG interne)
 *
 * Si le player natif signale une erreur via `onError` (watchdog ICE, UDP filtré
 * en preview cloud, path MediaMTX non-ready, broker MJPEG mort…), le dispatcher
 * bascule sur `/api/stream/{id}/live.mjpeg` — endpoint universel qui passe par
 * go2rtc et fonctionne partout (LAN + preview cloud).
 */
export function pipelineOf(camera) {
  const p = (camera?.stream_pipeline || "").toLowerCase();
  if (["direct_rtsp", "mjpeg", "mediamtx", "go2rtc"].includes(p)) return p;
  const legacy = (camera?.stream_mode || "auto").toLowerCase();
  return legacy === "direct_rtsp" ? "direct_rtsp" : "mediamtx";
}

// Fallback universel : petit composant <img> qui pointe vers l'endpoint legacy
// MJPEG proxifié par go2rtc, avec retry backoff 2.5 s. Aucun state React lourd.
function UniversalMjpegFallback({ cameraId, hd = false, className, dataTestId }) {
  const [reloadKey, setReloadKey] = useState(0);
  const retryTimer = useRef(null);
  const token = localStorage.getItem("mg_token") || "";
  const src = `${API}/stream/${cameraId}/live.mjpeg?token=${encodeURIComponent(token)}&hd=${hd ? 1 : 0}&r=${reloadKey}`;
  useEffect(() => () => { if (retryTimer.current) clearTimeout(retryTimer.current); }, []);
  return (
    <div className={`relative ${className}`} data-testid={`${dataTestId}-fallback`}>
      <img src={src} alt="" className={`object-contain bg-black w-full h-full`}
           data-testid={dataTestId}
           onError={() => {
             if (retryTimer.current) clearTimeout(retryTimer.current);
             retryTimer.current = setTimeout(() => setReloadKey((k) => k + 1), 2500);
           }} />
      <span className="absolute top-1 left-1 text-[9px] mono uppercase tracking-wider bg-black/60 text-[#FFB800] px-1.5 py-0.5"
            title="Le pipeline natif n'a pas répondu — bascule automatique sur MJPEG universel">
        FALLBACK
      </span>
    </div>
  );
}

export default function VideoPlayer({ camera, hd = false, className = "", dataTestId = "video-player" }) {
  const [fallback, setFallback] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const pipeline = pipelineOf(camera);

  // Re-tente le pipeline natif quand la caméra change (nouveau contexte)
  useEffect(() => { setFallback(false); setRetryKey((k) => k + 1); }, [camera?.id, pipeline]);

  if (!camera?.id) return <div className={`bg-black ${className}`} data-testid={dataTestId} />;

  if (pipeline === "direct_rtsp") {
    return <DirectRTSPCard cameraId={camera.id} className={className} dataTestId={dataTestId} />;
  }

  // Fallback universel MJPEG déclenché → visible sur TOUS les pipelines browser-playables
  if (fallback) {
    return <UniversalMjpegFallback cameraId={camera.id} hd={hd}
                                    className={className} dataTestId={dataTestId} />;
  }

  if (pipeline === "go2rtc") {
    // Go2RTCPlayer gère lui-même son propre fallback WebRTC→MJPEG en interne.
    // On lui passe onError pour couvrir aussi les erreurs de son MJPEG.
    return <Go2RTCPlayer key={`${camera.id}-${hd ? "hd" : "sd"}-${retryKey}`}
                          cameraId={camera.id} hd={hd}
                          className={className} dataTestId={dataTestId}
                          onError={() => setFallback(true)} />;
  }

  if (pipeline === "mediamtx") {
    return <WHEPPlayer key={`${camera.id}-${retryKey}`} cameraId={camera.id}
                        className={className} dataTestId={dataTestId}
                        onError={() => setFallback(true)} />;
  }

  // pipeline === "mjpeg"
  return <MJPEGPlayer key={`${camera.id}-${retryKey}`} cameraId={camera.id}
                       className={className} dataTestId={dataTestId}
                       onError={() => setFallback(true)} />;
}
