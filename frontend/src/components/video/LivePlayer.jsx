import React, { useEffect, useRef, useState } from "react";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;

/**
 * video-engine-v3 · Live Player UNIQUE (WHEP aiortc, RTSP-native).
 *
 * Remplace : WHEPPlayer, MJPEGPlayer, Go2RTCPlayer, WebRTCPlayer, DirectRTSPCard.
 * Aucun fallback MJPEG légitime en prod : si WHEP échoue, on affiche une
 * erreur claire — pas de masquage.
 */
export default function LivePlayer({ camera, className = "", dataTestId = "live-player" }) {
  const videoRef = useRef(null);
  const pcRef = useRef(null);
  const [state, setState] = useState("connecting");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!camera?.id) return;
    let cancelled = false;
    let watchdog = null;

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
          setState("playing");
        } else if (s === "failed" || s === "disconnected") {
          setState("error");
          setErr(`ICE ${s} (UDP filtré ? testez en LAN)`);
        }
      };

      watchdog = setTimeout(() => {
        if (!cancelled && pc.iceConnectionState !== "connected"
            && pc.iceConnectionState !== "completed") {
          setState("error");
          setErr(`ICE=${pc.iceConnectionState} (UDP filtré ? testez en LAN)`);
        }
      }, 12000);

      try {
        // Démarre le Video Core côté serveur si pas déjà actif
        const token = localStorage.getItem("mg_token") || "";
        await fetch(`${API}/live/${camera.id}/start`, {
          method: "POST",
          headers: { "Authorization": `Bearer ${token}` },
        }).catch(() => {});

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const r = await fetch(`${API}/live/${camera.id}/whep`, {
          method: "POST",
          headers: {
            "Content-Type": "application/sdp",
            "Authorization": `Bearer ${token}`,
          },
          body: offer.sdp,
        });
        if (!r.ok) {
          const body = await r.text();
          throw new Error(`WHEP HTTP ${r.status} — ${body.slice(0, 200)}`);
        }
        const answerSdp = await r.text();
        if (cancelled) return;
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
      } catch (e) {
        if (!cancelled) {
          setState("error");
          setErr(String(e.message || e));
        }
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

  return (
    <div className={`relative bg-black overflow-hidden ${className}`} data-testid={dataTestId}>
      <video ref={videoRef} autoPlay playsInline muted
              className="w-full h-full object-contain"
              data-testid={`${dataTestId}-video`} />
      {state !== "playing" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center
                          text-white/70 text-xs mono pointer-events-none"
              data-testid={`${dataTestId}-state`}>
          {state === "connecting" && <>Connexion WebRTC…</>}
          {state === "error" && (
            <>
              <span className="text-[#FF5252] mb-1">Erreur WebRTC</span>
              <span className="opacity-70 max-w-[80%] text-center">{err}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Compat : le nom `VideoPlayer` reste utilisé partout, on ré-exporte le même composant.
export const pipelineOf = () => "rtsp_native";
