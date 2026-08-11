import React, { useEffect, useRef, useState } from "react";
import WebRTCPlayer from "@/components/WebRTCPlayer";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;

/**
 * Pipeline legacy go2rtc (choix explicite admin) : WebRTC go2rtc, avec repli
 * MJPEG proxifié go2rtc (/api/stream/{id}/live.mjpeg) — les deux chemins
 * passent par go2rtc, cohérent avec le pipeline choisi.
 */
export default function Go2RTCPlayer({ cameraId, className = "", dataTestId = "go2rtc-player" }) {
  const [useMjpeg, setUseMjpeg] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const retryTimer = useRef(null);
  const token = localStorage.getItem("mg_token") || "";

  useEffect(() => () => { if (retryTimer.current) clearTimeout(retryTimer.current); }, []);
  useEffect(() => { setUseMjpeg(false); setReloadKey((k) => k + 1); }, [cameraId]);

  if (!useMjpeg) {
    return <WebRTCPlayer cameraId={cameraId} className={className} dataTestId={dataTestId}
                          onError={() => setUseMjpeg(true)} />;
  }
  return (
    <img src={`${API}/stream/${cameraId}/live.mjpeg?token=${encodeURIComponent(token)}&r=${reloadKey}`}
         alt="" className={`object-contain bg-black ${className}`} data-testid={dataTestId}
         onError={() => {
           if (retryTimer.current) clearTimeout(retryTimer.current);
           retryTimer.current = setTimeout(() => setReloadKey((k) => k + 1), 2500);
         }} />
  );
}
