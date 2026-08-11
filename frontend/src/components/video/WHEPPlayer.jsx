import React, { useEffect, useRef, useState } from "react";
import api from "@/lib/api";

/**
 * video-pipeline-v2 · Player WebRTC MediaMTX via WHEP officiel.
 * Signaling proxifié par le backend (POST /api/video/{id}/whep, SDP brut) —
 * le navigateur ne voit jamais MediaMTX ni les credentials RTSP.
 */
export default function WHEPPlayer({ cameraId, className = "", dataTestId = "whep-player", onError, onConnected }) {
  const videoRef = useRef(null);
  const pcRef = useRef(null);
  const sessionRef = useRef(null);
  const [state, setState] = useState("connecting");

  useEffect(() => {
    let cancelled = false;
    let watchdog = null;

    const cleanup = () => {
      if (watchdog) clearTimeout(watchdog);
      try { pcRef.current?.close(); } catch (e) { /* noop */ }
      pcRef.current = null;
      if (sessionRef.current) {
        api.delete(`/video/${cameraId}/whep`, { params: { session: sessionRef.current } }).catch(() => {});
        sessionRef.current = null;
      }
    };

    const start = async () => {
      try {
        const pc = new RTCPeerConnection({ iceServers: [] });
        pcRef.current = pc;
        pc.addTransceiver("video", { direction: "recvonly" });
        pc.addTransceiver("audio", { direction: "recvonly" });
        pc.ontrack = (ev) => {
          if (videoRef.current && ev.streams && ev.streams[0]) {
            videoRef.current.srcObject = ev.streams[0];
          }
        };
        pc.onconnectionstatechange = () => {
          if (cancelled) return;
          if (pc.connectionState === "connected") {
            if (watchdog) clearTimeout(watchdog);
            setState("connected");
            onConnected?.();
          } else if (["failed", "closed"].includes(pc.connectionState)) {
            setState("error");
            onError?.(`WebRTC ${pc.connectionState}`);
          }
        };
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        // Attendre la fin (ou 1 s max) du gathering ICE local
        await new Promise((resolve) => {
          if (pc.iceGatheringState === "complete") return resolve();
          const t = setTimeout(resolve, 1000);
          pc.onicegatheringstatechange = () => {
            if (pc.iceGatheringState === "complete") { clearTimeout(t); resolve(); }
          };
        });
        const r = await api.post(`/video/${cameraId}/whep`, pc.localDescription.sdp, {
          headers: { "Content-Type": "application/sdp" },
          responseType: "text",
          transformResponse: [(d) => d],
        });
        sessionRef.current = r.headers?.["x-whep-session"] || null;
        if (cancelled) return cleanup();
        await pc.setRemoteDescription({ type: "answer", sdp: r.data });
        // Watchdog : pas de connexion média en 10 s → erreur explicite
        watchdog = setTimeout(() => {
          if (!cancelled && pc.connectionState !== "connected") {
            setState("error");
            onError?.("WebRTC : négociation OK mais média non connecté (ICE/UDP bloqué ?)");
          }
        }, 10000);
      } catch (e) {
        if (cancelled) return;
        setState("error");
        onError?.(e?.response?.data?.detail || e?.message || "WHEP failed");
      }
    };
    start();
    return () => { cancelled = true; cleanup(); };
  }, [cameraId]);

  return (
    <div className={`relative ${className}`} data-testid={dataTestId}>
      <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-contain bg-black" />
      {state === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-[10px] mono uppercase tracking-wider text-white/50" data-testid="whep-connecting">Connexion WebRTC…</span>
        </div>
      )}
    </div>
  );
}
