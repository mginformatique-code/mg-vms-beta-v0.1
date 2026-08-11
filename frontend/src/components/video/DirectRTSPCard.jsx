import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { Cable } from "lucide-react";

/**
 * video-pipeline-v2 · Pipeline DIRECT RTSP : un navigateur ne lit pas le RTSP.
 * Ce composant l'affiche HONNÊTEMENT (DISPONIBLE / NON DISPONIBLE + URL masquée)
 * au lieu de simuler une preview.
 */
export default function DirectRTSPCard({ cameraId, className = "", dataTestId = "direct-rtsp-card" }) {
  const [st, setSt] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.get(`/cameras/${cameraId}/video-status`)
      .then((r) => { if (alive) setSt(r.data); })
      .catch(() => { if (alive) setSt({ status: "offline", error: "statut indisponible" }); });
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [cameraId]);

  const available = st?.status === "online";
  return (
    <div className={`flex items-center justify-center bg-[#0a0a0a] ${className}`} data-testid={dataTestId}>
      <div className="text-center space-y-1.5 px-4" data-testid="direct-rtsp-card">
        <Cable size={22} className={`mx-auto ${available ? "text-[#00E676]" : "text-[#FF3333]"}`} />
        <div className="text-[10px] mono uppercase tracking-wider text-white/60">Pipeline : Direct RTSP</div>
        <div className={`text-[11px] mono font-bold uppercase ${available ? "text-[#00E676]" : "text-[#FF3333]"}`}
             data-testid="direct-rtsp-state">
          {st === null ? "…" : available ? "Disponible" : "Non disponible"}
        </div>
        {available && st?.codec && (
          <div className="text-[9px] mono text-white/50">
            {st.codec.toUpperCase()}{st.resolution ? ` · ${st.resolution}` : ""}{st.fps ? ` · ${st.fps} fps` : ""}
          </div>
        )}
        {!available && st?.error && (
          <div className="text-[9px] mono text-[#FF3333]/80 max-w-[260px]" data-testid="direct-rtsp-error">{st.error}</div>
        )}
        {st?.rtsp_url_masked && (
          <div className="text-[9px] mono text-white/40 break-all max-w-[280px]">{st.rtsp_url_masked}</div>
        )}
        <div className="text-[9px] text-white/40 max-w-[280px]">
          Flux RTSP natif non lisible par ce navigateur — utilisez VLC/NVR, ou choisissez MJPEG / MediaMTX.
        </div>
      </div>
    </div>
  );
}
