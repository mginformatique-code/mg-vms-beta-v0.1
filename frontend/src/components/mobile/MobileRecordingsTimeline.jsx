/**
 * MobileRecordingsTimeline — barre d'enregistrements du jour, sous la
 * rangée d'icônes de MobileLive.jsx (v3.103, demande explicite : "en
 * dessous des boutons faudrait ajouter la timeline des camera stp, que
 * les elements de la timeline soit cliquables aussi stp").
 *
 * Réutilise TEL QUEL l'endpoint `GET /recordings/timeline` déjà utilisé
 * par la page desktop `Recordings.jsx` — jour courant uniquement (pas de
 * sélecteur de date), pas d'export (reste une action desktop/technicien).
 *
 * v3.109 · Pincement à deux doigts pour zoomer/dézoomer (demande explicite :
 * "le zoom sur l'enregistrement avec les doigts ne fonctionne pas") + un
 * doigt pour naviguer une fois zoomé — même logique que le zoom molette de
 * `Recordings.jsx` desktop (fenêtre `viewStart`/`viewEnd`, ancrée sur le
 * point médian des deux doigts plutôt que recentrée), traduite en gestes
 * tactiles. Le zoom d'un pincement à l'autre est un facteur multiplicatif
 * (distance actuelle / distance de départ du geste), pas une valeur absolue.
 */
import React, { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { useApp } from "@/context/AppContext";
import { MODE_COLORS } from "@/pages/Recordings";
import { Film, X, Loader2, RotateCcw } from "lucide-react";

const DAY_SEC = 86400;
const MIN_SPAN_SEC = 60;
const TICK_STEPS = [60, 300, 600, 900, 1800, 3600, 2 * 3600, 4 * 3600, 6 * 3600, 12 * 3600, DAY_SEC];

function pickTickStep(spanSec) {
  for (const step of TICK_STEPS) if (spanSec / step <= 6) return step;
  return DAY_SEC;
}
function fmtTick(sec, step) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
  return step < 60 ? `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    : `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`;
}
function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}
function dist(t1, t2) {
  return Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY);
}

export default function MobileRecordingsTimeline({ cameraId }) {
  const { t } = useApp();
  const [data, setData] = useState(null);
  const [playing, setPlaying] = useState(null);
  const [viewStart, setViewStart] = useState(0);
  const [viewEnd, setViewEnd] = useState(DAY_SEC);
  const barRef = useRef(null);
  const pinchRef = useRef(null);
  const panRef = useRef(null);

  useEffect(() => {
    setData(null);
    setViewStart(0); setViewEnd(DAY_SEC);
    const today = new Date().toISOString().slice(0, 10);
    api.get("/recordings/timeline", { params: { camera_id: cameraId, date: today } })
      .then((r) => setData(r.data))
      .catch(() => setData({ segments: [] }));
  }, [cameraId]);

  const segments = data?.segments || [];
  const viewSpan = viewEnd - viewStart;
  const zoomed = viewSpan < DAY_SEC - 1;

  const segPos = (seg) => {
    const s = new Date(seg.start);
    const startSec = s.getHours() * 3600 + s.getMinutes() * 60 + s.getSeconds();
    const left = ((startSec - viewStart) / viewSpan) * 100;
    const width = (seg.duration_sec / viewSpan) * 100;
    return { left: `${left}%`, width: `${Math.max(width, 0.4)}%` };
  };

  const xToSec = (clientX) => {
    const rect = barRef.current.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return viewStart + ratio * viewSpan;
  };

  const resetZoom = () => { setViewStart(0); setViewEnd(DAY_SEC); };

  const onTouchStart = (e) => {
    if (e.touches.length === 2) {
      const [t1, t2] = e.touches;
      pinchRef.current = { startDist: dist(t1, t2), startSpan: viewSpan, anchorSec: xToSec((t1.clientX + t2.clientX) / 2) };
      panRef.current = null;
    } else if (e.touches.length === 1) {
      panRef.current = { startX: e.touches[0].clientX, startStart: viewStart, startEnd: viewEnd };
      pinchRef.current = null;
    }
  };

  const onTouchMove = (e) => {
    if (e.touches.length === 2 && pinchRef.current) {
      e.preventDefault();
      const [t1, t2] = e.touches;
      const scale = dist(t1, t2) / pinchRef.current.startDist;
      const newSpan = Math.min(DAY_SEC, Math.max(MIN_SPAN_SEC, pinchRef.current.startSpan / scale));
      const rect = barRef.current.getBoundingClientRect();
      const midX = (t1.clientX + t2.clientX) / 2;
      const midRatio = Math.min(1, Math.max(0, (midX - rect.left) / rect.width));
      let newStart = pinchRef.current.anchorSec - midRatio * newSpan;
      let newEnd = newStart + newSpan;
      if (newStart < 0) { newEnd -= newStart; newStart = 0; }
      if (newEnd > DAY_SEC) { newStart -= (newEnd - DAY_SEC); newEnd = DAY_SEC; }
      setViewStart(Math.max(0, newStart)); setViewEnd(newEnd);
    } else if (e.touches.length === 1 && panRef.current) {
      const span = panRef.current.startEnd - panRef.current.startStart;
      if (span >= DAY_SEC - 1) return; // rien à faire, vue déjà pleine journée
      e.preventDefault();
      const rect = barRef.current.getBoundingClientRect();
      const dxSec = ((e.touches[0].clientX - panRef.current.startX) / rect.width) * span;
      let newStart = panRef.current.startStart - dxSec;
      let newEnd = panRef.current.startEnd - dxSec;
      if (newStart < 0) { newEnd -= newStart; newStart = 0; }
      if (newEnd > DAY_SEC) { newStart -= (newEnd - DAY_SEC); newEnd = DAY_SEC; }
      setViewStart(Math.max(0, newStart)); setViewEnd(newEnd);
    }
  };

  const onTouchEnd = (e) => {
    if (e.touches.length === 0) { pinchRef.current = null; panRef.current = null; }
    else if (e.touches.length === 1) {
      panRef.current = { startX: e.touches[0].clientX, startStart: viewStart, startEnd: viewEnd };
      pinchRef.current = null;
    }
  };

  const tickStep = pickTickStep(viewSpan);
  const ticks = [];
  for (let s = Math.ceil(viewStart / tickStep) * tickStep; s <= viewEnd; s += tickStep) ticks.push(s);

  return (
    <div className="px-3 py-3 border-t border-border" data-testid="mobile-live-timeline">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
          <Film size={12} /> {t("mobile.live_timeline_title")}
        </div>
        {zoomed && (
          <button onClick={resetZoom} data-testid="mobile-timeline-reset-zoom"
                  className="flex items-center gap-1 text-[10px] uppercase text-[#0044FF]">
            <RotateCcw size={11} /> {t("mobile.timeline_reset_zoom")}
          </button>
        )}
      </div>
      {data === null ? (
        <div className="flex items-center justify-center py-4"><Loader2 size={16} className="animate-spin text-muted-foreground" /></div>
      ) : segments.length === 0 ? (
        <div className="text-xs text-muted-foreground text-center py-3">{t("mobile.timeline_empty")}</div>
      ) : (
        <>
          <div ref={barRef} className="relative h-9 bg-secondary/50 rounded-lg overflow-hidden select-none"
               style={{ touchAction: "none" }} data-testid="mobile-timeline-bar"
               onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd} onTouchCancel={onTouchEnd}>
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
            {ticks.map((s) => (
              <span key={s} className="absolute text-[9px] mono text-muted-foreground -translate-x-1/2"
                    style={{ left: `${((s - viewStart) / viewSpan) * 100}%` }}>
                {fmtTick(s, tickStep)}
              </span>
            ))}
          </div>
          {!zoomed && (
            <div className="text-[9px] text-muted-foreground text-center mt-1">{t("mobile.timeline_pinch_hint")}</div>
          )}
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
