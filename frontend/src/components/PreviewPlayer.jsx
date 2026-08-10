/**
 * PreviewPlayer — v1.0-rc4
 *
 * Wrapper qui dispatche vers WebRTCPlayer (via Go2RTC) OU MJPEG direct
 * selon `camera.live_preview_source` :
 *   - "go2rtc" : WebRTC via Go2RTC (fluide, ~200-500 ms)
 *   - "direct" : <img src="/api/cameras/{id}/mjpeg-direct"> — multipart
 *                MJPEG produit par un subprocess ffmpeg local (ZÉRO Go2RTC).
 *   - "auto"   : tente Go2RTC ; fallback direct sur erreur.
 *
 * Affiche un badge « LIVE · DIRECT » ou « LIVE · GO2RTC » qui reflète la
 * source RÉELLEMENT utilisée (jamais un mensonge).
 */
import React, { useState } from "react";
import WebRTCPlayer from "@/components/WebRTCPlayer";

const API_BASE = process.env.REACT_APP_BACKEND_URL || "";

export default function PreviewPlayer({ cameraId, className = "" }) {
  const [source, setSource] = useState(null);        // "go2rtc" | "direct" | null
  const [effective, setEffective] = useState(null);  // idem
  const [err, setErr] = useState(null);

  // Charge le mode préféré à partir du backend
  React.useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/api/cameras/${cameraId}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("mg_token") || ""}` },
    })
      .then((r) => r.json())
      .then((cam) => {
        if (!alive) return;
        const pref = (cam?.live_preview_source || "auto").toLowerCase();
        setSource(pref === "auto" ? "go2rtc" : pref); // auto → go2rtc en 1er
        setEffective(pref === "auto" ? "go2rtc" : pref);
      })
      .catch(() => { if (alive) { setSource("go2rtc"); setEffective("go2rtc"); } });
    return () => { alive = false; };
  }, [cameraId]);

  const onDirectError = () => {
    // Fallback auto : direct KO → go2rtc
    if (source === "direct") {
      setErr("Flux DIRECT indisponible — fallback GO2RTC");
      setSource("go2rtc");
      setEffective("go2rtc");
    }
  };

  const badge = effective === "direct"
    ? { txt: "LIVE · DIRECT", color: "text-[#00E676] border-[#00E676]/40 bg-[#00E676]/15" }
    : effective === "go2rtc"
      ? { txt: "LIVE · GO2RTC", color: "text-[#00E5FF] border-[#00E5FF]/40 bg-[#00E5FF]/15" }
      : { txt: "…", color: "text-muted-foreground border-border" };

  if (!source) return <div className={`bg-black flex items-center justify-center text-xs text-muted-foreground ${className}`}>Chargement preview…</div>;

  return (
    <div className={`relative ${className}`} data-testid={`preview-player-${cameraId}`}>
      <span
        className={`absolute top-2 left-2 z-10 text-[10px] mono uppercase tracking-wider px-2 py-0.5 border ${badge.color}`}
        data-testid={`preview-effective-${cameraId}`}
      >
        {badge.txt}
      </span>
      {err && (
        <span className="absolute top-2 right-2 z-10 text-[10px] mono uppercase px-2 py-0.5 border border-[#FFB800]/40 bg-[#FFB800]/15 text-[#FFB800]">
          {err}
        </span>
      )}
      {source === "direct" ? (
        <img
          src={`${API_BASE}/api/cameras/${cameraId}/mjpeg-direct?fps=8&q=5`}
          alt="Live direct"
          className="w-full h-full object-contain bg-black"
          onError={onDirectError}
          data-testid={`preview-img-direct-${cameraId}`}
        />
      ) : (
        <WebRTCPlayer cameraId={cameraId} className="w-full h-full" />
      )}
    </div>
  );
}
