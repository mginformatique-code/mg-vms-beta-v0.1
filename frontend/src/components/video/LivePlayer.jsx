import React, { useEffect, useRef, useState } from "react";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;
const WHEP_TIMEOUT_MS = 8000;

function mjpegUrl(cameraId, hd) {
  const token = localStorage.getItem("mg_token") || "";
  return `${API}/stream/${cameraId}/live.mjpeg?token=${encodeURIComponent(token)}&hd=${hd ? 1 : 0}`;
}

/**
 * LivePlayer — WebRTC (WHEP/aiortc) en priorité pour la qualité/latence,
 * avec repli AUTOMATIQUE sur MJPEG (Go2RTC ou pont direct_rtsp selon
 * stream_mode côté backend) si WHEP échoue ou n'aboutit pas sous
 * WHEP_TIMEOUT_MS. Le badge reflète TOUJOURS la source réellement active
 * — jamais un mensonge.
 */
export default function LivePlayer({ camera, hd = false, className = "", dataTestId = "live-player" }) {
  const videoRef = useRef(null);
  const pcRef = useRef(null);
  const [mode, setMode] = useState("connecting"); // "connecting" | "webrtc" | "mjpeg"

  useEffect(() => {
    if (!camera?.id) return;
    let cancelled = false;
    let watchdog = null;
    setMode("connecting");

    const fallbackToMjpeg = () => {
      if (cancelled) return;
      if (watchdog) { clearTimeout(watchdog); watchdog = null; }
      if (pcRef.current) {
        try { pcRef.current.close(); } catch { /* ignore */ }
        pcRef.current = null;
      }
      setMode("mjpeg");
    };

    (async () => {
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      });
      pcRef.current = pc;

      pc.addTransceiver("video", { direction: "recvonly" });
      pc.ontrack = (event) => {
        if (cancelled) return;
        if (videoRef.current && !videoRef.current.srcObject) {
          videoRef.current.srcObject = event.streams[0];
        }
      };
      pc.oniceconnectionstatechange = () => {
        if (cancelled) return;
        const s = pc.iceConnectionState;
        if (s === "connected" || s === "completed") {
          if (watchdog) { clearTimeout(watchdog); watchdog = null; }
          setMode("webrtc");
        } else if (s === "failed" || s === "disconnected") {
          fallbackToMjpeg();
        }
      };
      watchdog = setTimeout(fallbackToMjpeg, WHEP_TIMEOUT_MS);

      try {
        const token = localStorage.getItem("mg_token") || "";
        await fetch(`${API}/live/${camera.id}/start`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }).catch(() => {});

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const r = await fetch(`${API}/live/${camera.id}/whep`, {
          method: "POST",
          headers: { "Content-Type": "application/sdp", Authorization: `Bearer ${token}` },
          body: offer.sdp,
        });
        if (!r.ok) { fallbackToMjpeg(); return; }
        const answerSdp = await r.text();
        if (cancelled) return;
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
      } catch {
        fallbackToMjpeg();
      }
    })();

    return () => {
      cancelled = true;
      if (watchdog) clearTimeout(watchdog);
      if (pcRef.current) {
        try { pcRef.current.close(); } catch { /* ignore */ }
        pcRef.current = null;
      }
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [camera?.id]);

  const badge = mode === "webrtc"
    ? { txt: "WEBRTC", color: "#00E5FF" }
    : mode === "mjpeg"
      ? { txt: "MJPEG", color: "#FFAA00" }
      : { txt: "…", color: "#888" };

  return (
    <div className={`relative bg-black overflow-hidden ${className}`} data-testid={dataTestId}>
      {mode === "mjpeg" ? (
        <img src={mjpegUrl(camera.id, hd)} alt="Live" className="w-full h-full object-contain"
             data-testid={`${dataTestId}-img`} />
      ) : (
        <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-contain"
               data-testid={`${dataTestId}-video`} />
      )}
      {mode === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center text-white/70 text-xs mono pointer-events-none"
             data-testid={`${dataTestId}-state`}>
          Connexion…
        </div>
      )}
      <span
        className="absolute top-2 left-2 z-10 text-[9px] mono uppercase tracking-wider px-1.5 py-0.5 border pointer-events-none"
        style={{ color: badge.color, borderColor: `${badge.color}80`, background: `${badge.color}15` }}
        data-testid={`${dataTestId}-badge`}
      >
        {badge.txt}
      </span>
    </div>
  );
}
