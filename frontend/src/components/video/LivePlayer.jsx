import React, { useEffect, useRef, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;
const WHEP_TIMEOUT_MS = 8000;
// Délai avant de conclure « connecté mais aucune image » (chien de garde média)
const MEDIA_TIMEOUT_MS = 6000;

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
  // Codec du flux principal quand le HD demandé a dû être refusé (ex. "hevc")
  const [qualityNote, setQualityNote] = useState("");
  // v3.19 · Son caméra (micro) — autoplay navigateur exige muted=true par
  // défaut, l'utilisateur active le son explicitement via le bouton
  // haut-parleur (voir #audio=opus côté go2rtc, streaming.py). Caméras
  // sans piste audio : la case reste sans effet audible, mais le bouton
  // ne gêne pas — pas de détection de piste côté navigateur ici (surcoût
  // inutile pour un simple toggle).
  const [muted, setMuted] = useState(true);

  useEffect(() => {
    if (!camera?.id) return;
    let cancelled = false;
    let watchdog = null;
    let mediaWatchdog = null;
    setMode("connecting");
    setErrorMsg("");
    setQualityNote("");

    const showError = (msg) => {
      if (cancelled) return;
      if (watchdog) { clearTimeout(watchdog); watchdog = null; }
      if (mediaWatchdog) { clearTimeout(mediaWatchdog); mediaWatchdog = null; }
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
          // v3.9 · Chien de garde MÉDIA, en plus du chien de garde ICE.
          // ICE « connected » ne garantit PAS qu'une image arrive : si le
          // profil H264 négocié ne peut pas porter le flux réel (typiquement
          // un flux principal 4K High profile négocié en Baseline 3.1, qui
          // plafonne vers 720p), la connexion s'établit et l'écran reste
          // NOIR, sans erreur. On vérifie donc que des images sont
          // réellement décodées, et on bascule sinon.
          mediaWatchdog = setTimeout(async () => {
            if (cancelled) return;
            let decoded = 0;
            try {
              const stats = await pc.getStats();
              stats.forEach((r) => {
                if (r.type === "inbound-rtp" && r.kind === "video") {
                  decoded = r.framesDecoded || 0;
                }
              });
            } catch { /* getStats indisponible : on ne conclut pas */ return; }
            if (decoded === 0) {
              showError(hd
                ? "Flux HD non décodable par ce navigateur — repassez en SD"
                : "Connexion établie mais aucune image reçue");
            }
          }, MEDIA_TIMEOUT_MS);
        } else if (s === "failed" || s === "disconnected") {
          showError("Connexion WebRTC perdue (ICE)");
        }
      };
      watchdog = setTimeout(() => showError("Délai de connexion WebRTC dépassé"), WHEP_TIMEOUT_MS);

      try {
        const token = localStorage.getItem("mg_token") || "";
        // v3.9.1 · L'appel à `/live/{id}/start` a été retiré. Il déclenchait
        // `VideoCoreManager.ensure_camera()`, qui ouvre une connexion RTSP
        // Python sur le flux PRINCIPAL — pour CHAQUE tuile affichée. Or plus
        // rien n'en a besoin : le passthrough est servi par go2rtc, et le
        // repli aiortc ouvre lui-même sa source (`ensure_webrtc_source`).
        // Vérifié : `recorder.py`, `ai_engine.py` et `frame_source.py`
        // n'utilisent pas VideoCoreManager, ils lisent le RTSP directement.
        // C'était donc une connexion caméra pure perte, coûteuse sur les
        // appareils qui n'acceptent que quelques sessions RTSP simultanées
        // (une Reolink 2 canaux en ouvrait jusqu'à 2 de plus par mosaïque).
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // v3.9 · `hd` est transmis au WHEP : depuis le passage au passthrough
        // go2rtc, le WebRTC est le chemin normal, or `hd` n'était utilisé que
        // dans l'URL MJPEG — le bouton HD/SD du mur vidéo n'avait donc plus
        // aucun effet. Le backend ignore hd=1 si le flux principal est en
        // HEVC (non transportable par WebRTC vers un navigateur).
        const r = await fetch(`${API}/live/${camera.id}/whep?hd=${hd ? 1 : 0}`, {
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
        // v3.9.1 · Le serveur signale ici qu'il n'a PAS pu servir le HD
        // demandé (flux principal en HEVC, que WebRTC ne transporte pas vers
        // un navigateur). Sans ce retour, le bouton HD semblait simplement
        // cassé sur ces caméras alors que le repli est volontaire.
        const q = r.headers.get("X-Stream-Quality") || "";
        if (!cancelled) setQualityNote(q.startsWith("sd_forced") ? q.replace("sd_forced_", "") : "");

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
      if (mediaWatchdog) clearTimeout(mediaWatchdog);
      if (pcRef.current) {
        try { pcRef.current.close(); } catch { /* ignore */ }
        pcRef.current = null;
      }
      if (videoRef.current) videoRef.current.srcObject = null;
    };
    // `hd` fait partie des dépendances : basculer HD/SD doit relancer la
    // négociation WHEP (la qualité se choisit à la connexion, côté go2rtc).
  }, [camera?.id, hd]);

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
        <video ref={videoRef} autoPlay playsInline muted={muted} className="w-full h-full object-contain"
               data-testid={`${dataTestId}-video`} />
      )}
      {mode === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center text-white/70 text-xs mono pointer-events-none"
             data-testid={`${dataTestId}-state`}>
          Connexion…
        </div>
      )}
      {mode === "webrtc" && qualityNote && (
        <div className="absolute top-1 right-1 px-1.5 py-0.5 text-[9px] mono uppercase tracking-wider
                        bg-black/70 text-[#FFAA00] border border-[#FFAA00]/50 pointer-events-none"
             title={`Le flux principal de cette caméra est en ${qualityNote.toUpperCase()}, que WebRTC ne sait pas transmettre à un navigateur. Le sous-flux H264 est utilisé à la place.`}
             data-testid={`${dataTestId}-quality-note`}>
          HD indispo ({qualityNote.toUpperCase()})
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
      {mode === "webrtc" && (
        <button
          onClick={(e) => { e.stopPropagation(); setMuted((m) => !m); }}
          className="absolute bottom-2 right-2 z-10 p-1 bg-black/60 hover:bg-black/80 text-white/90 border border-white/20"
          title={muted ? "Activer le son" : "Couper le son"}
          data-testid={`${dataTestId}-mute-btn`}
        >
          {muted ? <VolumeX size={13} /> : <Volume2 size={13} />}
        </button>
      )}
    </div>
  );
}
