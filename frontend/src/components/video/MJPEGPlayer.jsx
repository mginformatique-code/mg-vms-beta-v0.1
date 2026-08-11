import React, { useEffect, useRef, useState } from "react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * video-pipeline-v2 · Player MJPEG (broker ffmpeg PARTAGÉ côté backend).
 * <img> multipart/x-mixed-replace + retry automatique (backoff 2.5 s).
 */
export default function MJPEGPlayer({ cameraId, className = "", dataTestId = "mjpeg-player", onError }) {
  const [reloadKey, setReloadKey] = useState(0);
  const [failCount, setFailCount] = useState(0);
  const retryTimer = useRef(null);
  const token = localStorage.getItem("mg_token") || "";
  const src = `${API}/video/${cameraId}/mjpeg?token=${encodeURIComponent(token)}&r=${reloadKey}`;

  useEffect(() => () => { if (retryTimer.current) clearTimeout(retryTimer.current); }, []);
  useEffect(() => { setReloadKey((k) => k + 1); setFailCount(0); }, [cameraId]);

  const handleError = () => {
    if (retryTimer.current) clearTimeout(retryTimer.current);
    // 3 échecs consécutifs (broker mort, upstream RTSP HS…) → escalade au parent
    // qui bascule sur le fallback universel MJPEG legacy (via go2rtc).
    setFailCount((n) => {
      const next = n + 1;
      if (next >= 3) onError?.("Broker MJPEG v2 indisponible après 3 tentatives");
      return next;
    });
    retryTimer.current = setTimeout(() => setReloadKey((k) => k + 1), 2500);
  };

  return (
    <img src={src} alt="" onError={handleError}
         className={`object-contain bg-black ${className}`} data-testid={dataTestId} />
  );
}
