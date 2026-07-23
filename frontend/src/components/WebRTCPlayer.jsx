import React, { useEffect, useRef, useState } from "react";
import api from "@/lib/api";

/**
 * Player WebRTC — récupère un flux H.264 pass-through depuis go2rtc.
 *
 * Contrat :
 *  - `cameraId`   : uuid caméra
 *  - `onError`    : callback (msg) — appelé si la négociation ICE échoue.
 *                    Le parent bascule alors en MJPEG (fallback).
 *  - `onConnected`: callback — appelé au premier frame vidéo décodé.
 *
 * Latence typique H.264 pass-through : 200-500 ms (vs 1-2 s MJPEG).
 * Aucune consommation CPU/GPU côté serveur (aucun transcodage).
 */
export default function WebRTCPlayer({ cameraId, className = "", muted = true,
                                        onError, onConnected, dataTestId }) {
  const videoRef = useRef(null);
  const pcRef = useRef(null);
  const [state, setState] = useState("connecting");  // connecting | playing | error

  useEffect(() => {
    let cancelled = false;

    const negotiate = async () => {
      // 1) Crée la PeerConnection avec un serveur STUN Google (gratuit, public)
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
      });
      pcRef.current = pc;

      // 2) Prépare pour recevoir vidéo (recvonly)
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.addTransceiver("audio", { direction: "recvonly" });

      // 3) Attache le stream reçu au <video>
      pc.ontrack = (event) => {
        if (cancelled) return;
        if (videoRef.current && !videoRef.current.srcObject) {
          videoRef.current.srcObject = event.streams[0];
        }
      };

      // 4) Log ICE state
      pc.oniceconnectionstatechange = () => {
        if (cancelled) return;
        const s = pc.iceConnectionState;
        if (s === "connected" || s === "completed") {
          setState("playing");
          onConnected?.();
        } else if (s === "failed" || s === "disconnected") {
          setState("error");
          onError?.(`ICE state: ${s}`);
        }
      };

      try {
        // 5) Créer offer local + attendre gathering ICE complet (trickle=false → simple)
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // Attend que ICE gathering soit terminé (2 s max) — utile pour go2rtc
        // qui n'implémente pas le trickle ICE.
        await new Promise((resolve) => {
          if (pc.iceGatheringState === "complete") return resolve();
          const cb = () => {
            if (pc.iceGatheringState === "complete") {
              pc.removeEventListener("icegatheringstatechange", cb);
              resolve();
            }
          };
          pc.addEventListener("icegatheringstatechange", cb);
          setTimeout(resolve, 2000);
        });

        if (cancelled) { pc.close(); return; }

        // 6) POST l'offer au backend (proxy vers go2rtc `/api/webrtc?src=cam_XXX`)
        const localDesc = pc.localDescription;
        const { data: answer } = await api.post(`/pipeline/webrtc/${cameraId}`, {
          type: localDesc.type,
          sdp: localDesc.sdp,
        });

        if (cancelled) { pc.close(); return; }

        // 7) Applique la SDP answer de go2rtc
        await pc.setRemoteDescription(new RTCSessionDescription({
          type: answer.type, sdp: answer.sdp,
        }));
      } catch (e) {
        if (cancelled) return;
        setState("error");
        onError?.(e.response?.data?.detail || e.message || "WebRTC handshake failed");
        try { pc.close(); } catch { /* ignore */ }
      }
    };

    negotiate();
    return () => {
      cancelled = true;
      if (pcRef.current) {
        try { pcRef.current.close(); } catch { /* ignore */ }
        pcRef.current = null;
      }
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [cameraId]);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`relative ${className}`} data-testid={dataTestId}>
      <video ref={videoRef} autoPlay playsInline muted={muted}
              className="w-full h-full object-contain bg-black" />
      {state === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/50 pointer-events-none">
          <span className="text-[10px] mono text-white/80 animate-pulse">Négociation WebRTC…</span>
        </div>
      )}
    </div>
  );
}
