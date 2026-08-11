import React, { useState } from "react";
import WHEPPlayer from "@/components/video/WHEPPlayer";
import MJPEGPlayer from "@/components/video/MJPEGPlayer";
import DirectRTSPCard from "@/components/video/DirectRTSPCard";
import Go2RTCPlayer from "@/components/video/Go2RTCPlayer";
import { AlertTriangle, RefreshCw } from "lucide-react";

/**
 * video-pipeline-v2 · Dispatcher UNIQUE : rend EXACTEMENT le player du pipeline
 * choisi pour la caméra (camera.stream_pipeline). AUCUNE logique parallèle,
 * AUCUN fallback caché.
 *   - mediamtx    → WHEPPlayer (WebRTC MediaMTX)
 *   - mjpeg       → MJPEGPlayer (broker partagé)
 *   - direct_rtsp → DirectRTSPCard (état honnête, pas de preview navigateur)
 */
export function pipelineOf(camera) {
  const p = (camera?.stream_pipeline || "").toLowerCase();
  if (["direct_rtsp", "mjpeg", "mediamtx", "go2rtc"].includes(p)) return p;
  const legacy = (camera?.stream_mode || "auto").toLowerCase();
  return legacy === "direct_rtsp" ? "direct_rtsp" : "mediamtx";
}

export default function VideoPlayer({ camera, className = "", dataTestId = "video-player" }) {
  const [error, setError] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const pipeline = pipelineOf(camera);

  if (!camera?.id) return <div className={`bg-black ${className}`} data-testid={dataTestId} />;

  if (pipeline === "direct_rtsp") {
    return <DirectRTSPCard cameraId={camera.id} className={className} dataTestId={dataTestId} />;
  }

  if (pipeline === "go2rtc") {
    return <Go2RTCPlayer key={`${camera.id}-${retryKey}`} cameraId={camera.id}
                          className={className} dataTestId={dataTestId} />;
  }

  if (error) {
    return (
      <div className={`flex items-center justify-center bg-[#0a0a0a] ${className}`} data-testid={`${dataTestId}-error`}>
        <div className="text-center space-y-1.5 px-3">
          <AlertTriangle size={20} className="mx-auto text-[#FF3333]" />
          <div className="text-[10px] mono uppercase tracking-wider text-white/60">
            Pipeline : {pipeline === "mediamtx" ? "MediaMTX (WebRTC)" : "MJPEG"}
          </div>
          <div className="text-[9px] mono text-[#FF3333]/90 max-w-[260px]" data-testid="video-player-error-msg">{String(error)}</div>
          <button onClick={() => { setError(null); setRetryKey((k) => k + 1); }}
                  className="text-[9px] mono uppercase px-2 py-1 border border-border text-white/70 hover:text-white inline-flex items-center gap-1"
                  data-testid="video-player-retry">
            <RefreshCw size={10} /> Réessayer
          </button>
        </div>
      </div>
    );
  }

  if (pipeline === "mediamtx") {
    return <WHEPPlayer key={`${camera.id}-${retryKey}`} cameraId={camera.id}
                        className={className} dataTestId={dataTestId}
                        onError={(msg) => setError(msg)} />;
  }
  return <MJPEGPlayer key={`${camera.id}-${retryKey}`} cameraId={camera.id}
                       className={className} dataTestId={dataTestId} />;
}
