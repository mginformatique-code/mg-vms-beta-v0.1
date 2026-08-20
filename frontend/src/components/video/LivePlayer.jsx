import React, { useEffect, useRef, useState } from "react";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;
const WHEP_TIMEOUT_MS = 8000;

function mjpegUrl(cameraId, hd) {
  const token = localStorage.getItem("mg_token") || "";
  return `${API}/stream/${cameraId}/live.mjpeg?token=${encodeURIComponent(token)}&hd=${hd ? 1 : 0}`;
}

/**
 * LivePlayer — WebRTC (WHEP/aiortc) en priorité pour la qualité/latence.
 * Si WHEP échoue ou n'aboutit pas sous WHEP_TIMEOUT_MS, PAS de bascule
 * automatique et silencieuse vers MJPEG (ça masquait un vrai problème de
 * configuration — ex. pas de sous-flux H264 — derrière un mode dégradé
 * que l'utilisateur ne comprenait pas) : on affiche le message d'erreur
 * renvoyé par le backend + un bouton explicite pour basculer sur MJPEG.
 * Le badge reflète TOUJOURS la source réellement active — jamais un mensonge.
 */
export default function LivePlayer({ camera, hd = false, className = "", dataTestId = "live-player" }) {
  const videoRef = useRef(null);
  const pcRef = useRef(null);
  const [mode, setMode] = useState("connecting"); // "connecting" | "webrtc" | "mjpeg" | "error"
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    if (!camera?.id) return;
    let cancelled = false;
    let watchdog = null;
    setMode("connecting");
    setErrorMsg("");

    const showError = (msg) => {
      if (cancelled) return;
      if (watchdog) { clearTimeout(watchdog); watchdog = null; }
      if (pcRef.current) {
        try { pcRef.current.close(); } catch { /* ignore */ }
        pcRef.current = null;
      }
      setErrorMsg(msg || "Connexion WebRTC impossible");
      setMode("error");
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
          showError("Connexion WebRTC perdue (ICE)");
        }
      };
      watchdog = setTimeout(() => showError("Délai de connexion WebRTC dépassé"), WHEP_TIMEOUT_MS);

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
        if (!r.ok) {
          let detail = "";
          try { detail = (await r.json())?.detail || ""; } catch { /* corps non-JSON */ }
          showError(detail || `WebRTC indisponible (HTTP ${r.status})`);
          return;
        }
        const answerSdp = await r.text();
        if (cancelled) return;
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
      } catch {
        showError("Connexion WebRTC impossible");
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
      : mode === "error"
        ? { txt: "ERREUR", color: "#FF3333" }
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
      {mode === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/80 px-3 text-center"
             data-testid={`${dataTestId}-error`}>
          <span className="text-[11px] text-[#FF3333] max-w-full">{errorMsg}</span>
          <button
            onClick={(e) => { e.stopPropagation(); setMode("mjpeg"); }}
            className="px-2.5 py-1 text-[10px] uppercase tracking-wider border border-[#FFAA00] text-[#FFAA00] hover:bg-[#FFAA00]/10"
            data-testid={`${dataTestId}-switch-mjpeg-btn`}
          >
            Basculer en MJPEG
          </button>
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
