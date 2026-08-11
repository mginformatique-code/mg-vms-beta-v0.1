import React, { useEffect, useRef, useState } from "react";
import WebRTCPlayer from "@/components/WebRTCPlayer";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;

/**
 * Pipeline legacy go2rtc (choix explicite admin) : WebRTC go2rtc, avec repli
 * MJPEG proxifié go2rtc (/api/stream/{id}/live.mjpeg) — les deux chemins
 * passent par go2rtc, cohérent avec le pipeline choisi.
 */
export default function Go2RTCPlayer({ cameraId, hd = false, className = "", dataTestId = "go2rtc-player", onError }) {
  const [useMjpeg, setUseMjpeg] = useState(false);
  const [failCount, setFailCount] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const retryTimer = useRef(null);
  const token = localStorage.getItem("mg_token") || "";

  useEffect(() => () => { if (retryTimer.current) clearTimeout(retryTimer.current); }, []);
  useEffect(() => { setUseMjpeg(false); setFailCount(0); setReloadKey((k) => k + 1); }, [cameraId]);

  if (!useMjpeg) {
    return <WebRTCPlayer cameraId={cameraId} className={className} dataTestId={dataTestId}
                          onError={() => setUseMjpeg(true)} />;
  }
  const src = `${API}/stream/${cameraId}/live.mjpeg?token=${encodeURIComponent(token)}&hd=${hd ? 1 : 0}&r=${reloadKey}`;
  return (
    <img src={src}
         alt="" className={`object-contain bg-black ${className}`} data-testid={dataTestId}
         onError={() => {
           if (retryTimer.current) clearTimeout(retryTimer.current);
           // Après 3 échecs consécutifs de l'`<img>` (upstream mort, go2rtc HS…),
           // on remonte l'erreur au VideoPlayer parent → fallback universel.
           setFailCount((n) => {
             const next = n + 1;
             if (next >= 3) onError?.("MJPEG go2rtc indisponible après 3 tentatives");
             return next;
           });
           retryTimer.current = setTimeout(() => setReloadKey((k) => k + 1), 2500);
         }} />
  );
}
