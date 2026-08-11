import React, { useEffect, useRef, useState } from "react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * video-pipeline-v2 · Player MJPEG (broker ffmpeg PARTAGÉ côté backend).
 * <img> multipart/x-mixed-replace + retry automatique (backoff 2.5 s).
 */
export default function MJPEGPlayer({ cameraId, className = "", dataTestId = "mjpeg-player", onError }) {
  const [reloadKey, setReloadKey] = useState(0);
  const retryTimer = useRef(null);
  const token = localStorage.getItem("mg_token") || "";
  const src = `${API}/video/${cameraId}/mjpeg?token=${encodeURIComponent(token)}&r=${reloadKey}`;

  useEffect(() => () => { if (retryTimer.current) clearTimeout(retryTimer.current); }, []);
  useEffect(() => { setReloadKey((k) => k + 1); }, [cameraId]);

  const handleError = () => {
    onError?.("Flux MJPEG interrompu — reconnexion…");
    if (retryTimer.current) clearTimeout(retryTimer.current);
    retryTimer.current = setTimeout(() => setReloadKey((k) => k + 1), 2500);
  };

  return (
    <img src={src} alt="" onError={handleError}
         className={`object-contain bg-black ${className}`} data-testid={dataTestId} />
  );
}
