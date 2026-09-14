/**
 * MobileRecordingsTimeline — barre d'enregistrements du jour, sous la
 * rangée d'icônes de MobileLive.jsx (v3.103, demande explicite : "en
 * dessous des boutons faudrait ajouter la timeline des camera stp, que
 * les elements de la timeline soit cliquables aussi stp").
 *
 * Réutilise TEL QUEL l'endpoint `GET /recordings/timeline` déjà utilisé
 * par la page desktop `Recordings.jsx` (zoom/molette/export, hors
 * périmètre mobile v1) — ici une version condensée non-zoomable : la
 * journée entière tient dans la largeur de l'écran, chaque segment est un
 * bouton (couleur = mode, même `MODE_COLORS` que desktop) qui ouvre la
 * vidéo correspondante en plein écran. Portée volontairement réduite par
 * rapport au desktop : jour courant uniquement (pas de sélecteur de
 * date), pas de zoom/export — l'export reste une action desktop/technicien.
 */
import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { MODE_COLORS } from "@/pages/Recordings";
import { Film, X, Loader2 } from "lucide-react";

const DAY_SEC = 86400;
const TICK_HOURS = [0, 4, 8, 12, 16, 20];

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}
function segPos(seg) {
  const s = new Date(seg.start);
  const startSec = s.getHours() * 3600 + s.getMinutes() * 60 + s.getSeconds();
  return { left: `${(startSec / DAY_SEC) * 100}%`, width: `${Math.max((seg.duration_sec / DAY_SEC) * 100, 0.4)}%` };
}

export default function MobileRecordingsTimeline({ cameraId }) {
  const { t } = useApp();
  const [data, setData] = useState(null);
  const [playing, setPlaying] = useState(null);

  useEffect(() => {
    setData(null);
    const today = new Date().toISOString().slice(0, 10);
    api.get("/recordings/timeline", { params: { camera_id: cameraId, date: today } })
      .then((r) => setData(r.data))
      .catch(() => setData({ segments: [] }));
  }, [cameraId]);

  const segments = data?.segments || [];

  return (
    <div className="px-3 py-3 border-t border-border" data-testid="mobile-live-timeline">
      <div className="flex items-center gap-1.5 mb-2 text-[10px] uppercase tracking-wider text-muted-foreground">
        <Film size={12} /> {t("mobile.live_timeline_title")}
      </div>
      {data === null ? (
        <div className="flex items-center justify-center py-4"><Loader2 size={16} className="animate-spin text-muted-foreground" /></div>
      ) : segments.length === 0 ? (
        <div className="text-xs text-muted-foreground text-center py-3">{t("mobile.timeline_empty")}</div>
      ) : (
        <>
          <div className="relative h-8 bg-secondary/50 rounded-lg overflow-hidden" data-testid="mobile-timeline-bar">
            {segments.map((seg) => (
              <button key={seg.id} onClick={() => setPlaying(seg)} data-testid={`mobile-timeline-seg-${seg.id}`}
                      title={fmtTime(seg.start)}
                      style={{ ...segPos(seg), backgroundColor: MODE_COLORS[seg.mode] || MODE_COLORS.continuous }}
                      className="absolute top-1 bottom-1 rounded-sm">
                {seg.has_event && <span className="absolute -top-1 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-[#FF3333]" />}
              </button>
            ))}
          </div>
          <div className="relative h-3 mt-1">
            {TICK_HOURS.map((h) => (
              <span key={h} className="absolute text-[9px] mono text-muted-foreground -translate-x-1/2"
                    style={{ left: `${(h / 24) * 100}%` }}>
                {String(h).padStart(2, "0")}h
              </span>
            ))}
          </div>
        </>
      )}

      {playing && (
        <div className="fixed inset-0 z-[60] bg-background flex flex-col" data-testid="mobile-timeline-player">
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-border shrink-0">
            <span className="text-sm text-foreground mono">{fmtTime(playing.start)} – {fmtTime(playing.end)}</span>
            <button onClick={() => setPlaying(null)} data-testid="mobile-timeline-player-close" className="p-1 text-foreground">
              <X size={20} />
            </button>
          </div>
          <div className="flex-1 flex items-center justify-center bg-black">
            <video key={playing.id} controls autoPlay className="w-full h-full object-contain"
                   src={`${process.env.REACT_APP_BACKEND_URL}/api/recordings/${playing.id}/media?token=${encodeURIComponent(localStorage.getItem("mg_token") || "")}`} />
          </div>
        </div>
      )}
    </div>
  );
}
