import React, { useEffect, useState, useRef, useMemo } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Maximize2, Camera as CamIcon, Move, ZoomIn, ZoomOut, Circle, Eye, EyeOff, X, ChevronLeft, ChevronRight } from "lucide-react";

const LAYOUTS = [1, 4, 9, 16, 25, 36, 49, 64];
const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Palette IA — une couleur distincte par classe
const CLASS_COLORS = {
  "Personne":   "#00E676",  // vert
  "Voiture":    "#0044FF",  // bleu
  "Camion":     "#FFB800",  // orange
  "Bus":        "#FFB800",
  "Moto":       "#FF66CC",  // rose
  "Vélo":       "#00E1FF",  // cyan
  "Animal":     "#B47CFF",  // violet
  "Chien":      "#B47CFF",
  "Chat":       "#B47CFF",
};
const colorFor = (label) => CLASS_COLORS[label] || "#FF3333";

function streamUrl(camId, hd = false) {
  const token = localStorage.getItem("mg_token");
  return `${API}/stream/${camId}/live.mjpeg?token=${encodeURIComponent(token || "")}&hd=${hd ? 1 : 0}`;
}

function OverlayCanvas({ cam, boxes, showOverlay }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!showOverlay) return;
    const canvas = ref.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;
    // Ajuste taille canvas à celle de l'élément parent (le <img>)
    const w = parent.clientWidth, h = parent.clientHeight;
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    if (!boxes || !boxes.length) return;
    ctx.lineWidth = 2;
    ctx.font = "bold 11px ui-monospace, monospace";
    for (const b of boxes) {
      const [x1, y1, x2, y2] = b.bbox_norm;
      const rx = x1 * w, ry = y1 * h, rw = (x2 - x1) * w, rh = (y2 - y1) * h;
      const color = colorFor(b.label);
      ctx.strokeStyle = color;
      ctx.strokeRect(rx, ry, rw, rh);
      // Label
      const label = `${b.label} ${(b.confidence * 100).toFixed(0)}%${b.vehicle_color ? " · " + b.vehicle_color : ""}${b.track_id ? " #" + b.track_id : ""}`;
      const metrics = ctx.measureText(label);
      const th = 15;
      ctx.fillStyle = color;
      ctx.fillRect(rx, Math.max(0, ry - th), metrics.width + 8, th);
      ctx.fillStyle = "#000";
      ctx.fillText(label, rx + 4, Math.max(11, ry - 3));
    }
  }, [boxes, showOverlay, cam?.id]);
  if (!showOverlay) return null;
  return <canvas ref={ref} className="absolute inset-0 w-full h-full pointer-events-none" data-testid="ai-overlay" />;
}

function Feed({ cam, idx, canPtz, hd, showOverlay, aiState, focused, onToggleFocus }) {
  const [hover, setHover] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const retryTimer = useRef(null);
  const online = cam?.status === "online";
  // Reset reloadKey lors d'un changement de caméra OU d'un toggle HD/SD (force le rechargement du <img>).
  useEffect(() => { setReloadKey((k) => k + 1); }, [cam?.id, hd]);
  useEffect(() => () => { if (retryTimer.current) clearTimeout(retryTimer.current); }, []);
  const handleError = () => {
    if (retryTimer.current) clearTimeout(retryTimer.current);
    retryTimer.current = setTimeout(() => setReloadKey((k) => k + 1), 2500);
  };
  const ptz = async (command) => { try { await api.post(`/cameras/${cam.id}/ptz?command=${command}`); } catch (e) { /* ignore */ } };

  const boxes = aiState?.boxes || [];
  const counts = aiState?.counts || {};
  const totalDetected = Object.values(counts).reduce((a, b) => a + b, 0);
  // Détection sous-flux (résolution < 1280x720) — le user a probablement gardé un sub-stream
  const [subW, subH] = (cam?.resolution || "").split(/x/i).map((n) => parseInt(n, 10) || 0);
  const isSubStream = online && subW > 0 && subH > 0 && (subW < 1280 || subH < 720);

  return (
    <div
      className={`relative bg-black overflow-hidden group aspect-video cursor-pointer transition-shadow ${focused ? "ring-2 ring-[#00E5FF]" : "hover:ring-1 hover:ring-[#0044FF]/60"}`}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      onClick={(e) => { if (!e.target.closest("[data-ptz-btn]")) onToggleFocus?.(cam?.id); }}
      title={cam ? (focused ? "Cliquez pour revenir à la mosaïque" : "Cliquez pour agrandir") : ""}
      data-testid="video-feed"
    >
      {online ? (
        <>
          <img
            src={`${streamUrl(cam.id, hd)}&r=${reloadKey}`}
            alt="" className="w-full h-full object-contain bg-black"
            onError={handleError} data-testid="live-stream"
          />
          {cam?.detect_enabled && <OverlayCanvas cam={cam} boxes={boxes} showOverlay={showOverlay} />}
        </>
      ) : (
        <div className="w-full h-full flex items-center justify-center bg-[#0a0a0a]">
          <div className="text-center"><CamIcon size={24} className="mx-auto text-[#FF3333] mb-1" /><span className="text-[10px] uppercase tracking-wider text-[#FF3333]">{cam ? "No Signal" : "—"}</span></div>
        </div>
      )}
      <div className="absolute top-0 inset-x-0 flex items-center justify-between px-2 py-1 bg-gradient-to-b from-black/70 to-transparent">
        <span className="text-[10px] mono text-white truncate">{cam?.name || `CAM-${idx + 1}`}</span>
        <div className="flex items-center gap-1.5">
          {online && cam?.detect_enabled && showOverlay && totalDetected > 0 && (
            <span className="text-[9px] mono px-1.5 py-0.5 bg-black/70 text-white" data-testid="feed-ai-counter">
              {Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(" · ")}
            </span>
          )}
          {online && cam?.resolution && (
            <span className="text-[9px] mono px-1 text-white/80 bg-black/50" data-testid="feed-resolution">{cam.resolution}</span>
          )}
          {online && <span data-testid="feed-quality" className="text-[8px] mono px-1 font-bold" style={{ color: hd ? "#00E676" : "#FFB800" }}>{hd ? "HD" : "SD"}</span>}
          {online && <span className="flex items-center gap-1 text-[9px] mono text-[#00E676]"><Circle size={6} className="fill-[#00E676] rec-dot" /> LIVE</span>}
          {focused && <X size={13} className="text-white/80" />}
        </div>
      </div>
      {isSubStream && (
        <div className="absolute top-8 inset-x-0 px-2" data-testid="substream-warning">
          <div className="text-[10px] mono px-2 py-1 bg-[#FFB800]/95 text-black flex items-center gap-1.5">
            ⚠ Sous-flux détecté ({cam.resolution}) — ouvrez le diagnostic pour re-sélectionner le profil principal.
          </div>
        </div>
      )}
      <div className="absolute bottom-0 inset-x-0 px-2 py-1 bg-gradient-to-t from-black/70 to-transparent flex justify-between">
        <span className="text-[9px] mono text-white/70">{cam?.site_name || ""}</span>
        <span className="text-[9px] mono text-white/70">{new Date().toLocaleTimeString()}</span>
      </div>
      {hover && online && cam?.ptz_enabled && canPtz && (
        <div className="absolute inset-0 flex items-center justify-center gap-1 bg-black/30" data-testid="ptz-controls">
          <div className="grid grid-cols-3 gap-0.5">
            {[[ZoomIn, "zoom_in"], [Move, "home"], [ZoomOut, "zoom_out"]].map(([Ic, cmd], i) => (
              <button key={i} data-ptz-btn onClick={(e) => { e.stopPropagation(); ptz(cmd); }} className="w-7 h-7 bg-black/60 hover:bg-[#0044FF] flex items-center justify-center text-white"><Ic size={14} /></button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FocusTimeline({ cameraId, onSelect }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!cameraId) return;
    let alive = true;
    const load = async () => {
      setLoading(true);
      try {
        const { data } = await api.get(`/events?camera_id=${cameraId}&limit=10`);
        if (alive) setEvents(Array.isArray(data) ? data : (data.items || []));
      } catch (e) { if (alive) setEvents([]); }
      finally { if (alive) setLoading(false); }
    };
    load();
    const iv = setInterval(load, 8000);  // rafraîchissement des 10 derniers événements toutes les 8 s
    return () => { alive = false; clearInterval(iv); };
  }, [cameraId]);

  if (!cameraId) return null;
  return (
    <div className="absolute bottom-6 inset-x-2 pointer-events-auto" data-testid="focus-timeline">
      <div className="bg-black/80 border border-white/10 px-2 py-1.5">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[9px] uppercase tracking-wider text-white/60 mono">
            10 derniers événements {loading && <span className="text-[#00E5FF]">…</span>}
          </span>
          <span className="text-[9px] mono text-white/40">{events.length}</span>
        </div>
        {events.length === 0 ? (
          <div className="text-[10px] text-white/40 py-1">Aucun événement récent pour cette caméra.</div>
        ) : (
          <div className="flex gap-1 overflow-x-auto">
            {events.map((ev) => {
              const label = ev.type || ev.label || "?";
              const ts = ev.timestamp ? new Date(ev.timestamp) : null;
              const time = ts ? ts.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
              const thumb = ev.thumbnail || ev.crop_thumbnail;
              return (
                <button key={ev.id} onClick={() => onSelect?.(ev)}
                        data-testid={`timeline-event-${ev.id}`}
                        className="flex-shrink-0 w-28 border border-white/10 hover:border-[#00E5FF] bg-black/60 text-left group"
                        title={`${label} · ${time}`}>
                  {thumb ? (
                    <img src={thumb} alt={label} className="w-full h-14 object-cover" />
                  ) : (
                    <div className="w-full h-14 bg-black/70 flex items-center justify-center text-white/30 text-xs">—</div>
                  )}
                  <div className="px-1.5 py-0.5">
                    <div className="text-[9px] mono text-white truncate">{label}</div>
                    <div className="text-[8px] mono text-white/50">{time}</div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function LiveView() {
  const { t, can, aiDetections } = useApp();
  const [cams, setCams] = useState([]);
  const [layout, setLayout] = useState(4);
  const [hd, setHd] = useState(false);
  const [showOverlay, setShowOverlay] = useState(() => localStorage.getItem("mg_ai_overlay") !== "off");
  const [focusedId, setFocusedId] = useState(null);  // camera_id focalisée (single-view) — null = mosaïque
  const [showTimeline, setShowTimeline] = useState(true);
  const [previewEvent, setPreviewEvent] = useState(null);  // événement cliqué depuis la timeline
  const canPtz = can("technician");

  useEffect(() => {
    api.get("/cameras").then((r) => setCams(r.data));
    const iv = setInterval(() => api.get("/cameras").then((r) => setCams(r.data)).catch(() => { /* ignore */ }), 20000);
    return () => clearInterval(iv);
  }, []);
  useEffect(() => { localStorage.setItem("mg_ai_overlay", showOverlay ? "on" : "off"); }, [showOverlay]);

  // Liste des caméras naviguables (celles présentes dans la mosaïque, dans l'ordre affiché)
  const gridCams = useMemo(() => {
    if (!focusedId) return cams;
    // Slice à la taille du layout courant (les slots vides ne comptent pas)
    return cams.slice(0, Math.max(layout, cams.length));
  }, [cams, focusedId, layout]);
  const focusedIndex = focusedId ? gridCams.findIndex((c) => c?.id === focusedId) : -1;
  const gotoDelta = (delta) => {
    if (focusedIndex < 0 || !gridCams.length) return;
    const n = gridCams.length;
    let next = (focusedIndex + delta + n) % n;
    // Skip les slots null (cams undefined si le tableau contient moins d'entrées que le layout)
    let safety = n;
    while (!gridCams[next]?.id && safety > 0) { next = (next + delta + n) % n; safety--; }
    if (gridCams[next]?.id) setFocusedId(gridCams[next].id);
  };

  // Raccourcis clavier en mode focus : ESC (sortie), ← (précédent), → (suivant), T (toggle timeline).
  useEffect(() => {
    if (!focusedId) return;
    const onKey = (e) => {
      // Ignore si l'utilisateur est en train de taper dans un champ
      const tag = (e.target?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      if (e.key === "Escape") { setFocusedId(null); setPreviewEvent(null); }
      else if (e.key === "ArrowRight") { e.preventDefault(); gotoDelta(+1); }
      else if (e.key === "ArrowLeft")  { e.preventDefault(); gotoDelta(-1); }
      else if (e.key.toLowerCase() === "t") { setShowTimeline((v) => !v); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedId, focusedIndex, gridCams.length]);

  const goFull = () => { const el = document.getElementById("live-grid"); if (el?.requestFullscreen) el.requestFullscreen(); };
  const focusedCam = focusedId ? cams.find((c) => c.id === focusedId) : null;
  const toggleFocus = (id) => { if (!id) return; setFocusedId((cur) => cur === id ? null : id); setPreviewEvent(null); };

  // Grille rectangulaire (16:9 par tuile) — pas d'étirement/rognage.
  const cols = focusedCam ? 1 : Math.ceil(Math.sqrt(layout));
  const gridStyle = focusedCam
    ? { display: "grid", gridTemplateColumns: "1fr", gap: 2 }
    : { display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: 2 };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("live.title")}</h1>
        <div className="flex items-center gap-2">
          {focusedCam && (
            <>
              <button onClick={() => gotoDelta(-1)} data-testid="focus-prev" title="Caméra précédente (←)"
                      className="p-1.5 border border-border hover:bg-secondary">
                <ChevronLeft size={14} />
              </button>
              <span className="text-[10px] mono text-muted-foreground px-1">
                {focusedIndex + 1}/{gridCams.filter((c) => c?.id).length}
              </span>
              <button onClick={() => gotoDelta(+1)} data-testid="focus-next" title="Caméra suivante (→)"
                      className="p-1.5 border border-border hover:bg-secondary">
                <ChevronRight size={14} />
              </button>
              <button onClick={() => setShowTimeline((v) => !v)} data-testid="focus-timeline-toggle"
                      title="Afficher/masquer la timeline des événements (T)"
                      className={`px-2.5 py-1.5 text-xs border flex items-center gap-1 ${showTimeline ? "bg-[#00E5FF]/20 border-[#00E5FF] text-[#00E5FF]" : "border-border hover:bg-secondary"}`}>
                Timeline
              </button>
              <button onClick={() => { setFocusedId(null); setPreviewEvent(null); }} data-testid="exit-focus"
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-[#00E5FF] text-[#00E5FF] hover:bg-[#00E5FF] hover:text-black">
                <X size={13} /> Fermer le focus
              </button>
            </>
          )}
          <button onClick={() => setShowOverlay((v) => !v)} data-testid="toggle-ai-overlay"
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs border ${showOverlay ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border hover:bg-secondary"}`}
            title="Afficher/masquer les détections IA">
            {showOverlay ? <Eye size={13} /> : <EyeOff size={13} />} Overlay IA
          </button>
          <button onClick={() => setHd(!hd)} data-testid="hd-toggle" className={`px-2.5 py-1.5 text-xs border ${hd ? "bg-[#00E676] text-black border-[#00E676]" : "border-border"} hover:opacity-80`}>{hd ? "HD" : "SD"}</button>
          {!focusedCam && LAYOUTS.map((n) => (
            <button key={n} onClick={() => setLayout(n)} data-testid={`layout-${n}`}
              className={`px-2.5 py-1.5 text-xs mono ${layout === n ? "bg-[#0044FF] text-white" : "border border-border hover:bg-secondary"}`}>{n}</button>
          ))}
          <button onClick={goFull} data-testid="fullscreen-btn" className="px-2.5 py-1.5 text-xs border border-border hover:bg-secondary flex items-center gap-1"><Maximize2 size={13} /> {t("live.fullscreen")}</button>
        </div>
      </div>

      <div id="live-grid" className="bg-background relative" style={gridStyle}>
        {focusedCam ? (
          <>
            <Feed cam={focusedCam} idx={0} canPtz={canPtz} hd={hd} showOverlay={showOverlay}
                  aiState={aiDetections[focusedCam.id]} focused={true} onToggleFocus={toggleFocus} />
            {showTimeline && <FocusTimeline cameraId={focusedCam.id} onSelect={setPreviewEvent} />}
          </>
        ) : (
          Array.from({ length: layout }).map((_, i) => (
            <Feed key={i} cam={cams[i]} idx={i} canPtz={canPtz} hd={hd}
                  showOverlay={showOverlay} focused={false}
                  aiState={cams[i] ? aiDetections[cams[i].id] : null}
                  onToggleFocus={toggleFocus} />
          ))
        )}
      </div>

      {previewEvent && (
        <div className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-8" onClick={() => setPreviewEvent(null)} data-testid="event-preview-modal">
          <div className="max-w-5xl w-full" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-white font-head font-semibold text-lg">{previewEvent.type || previewEvent.label || "Événement"}</div>
                <div className="text-white/60 text-xs mono">
                  {previewEvent.timestamp ? new Date(previewEvent.timestamp).toLocaleString("fr-FR") : ""}
                  {previewEvent.camera_name ? ` · ${previewEvent.camera_name}` : ""}
                  {previewEvent.confidence ? ` · ${(previewEvent.confidence * 100).toFixed(0)}%` : ""}
                </div>
              </div>
              <button onClick={() => setPreviewEvent(null)} className="p-2 hover:bg-white/10 text-white" data-testid="event-preview-close">
                <X size={18} />
              </button>
            </div>
            {previewEvent.thumbnail && (
              <img src={previewEvent.thumbnail} alt={previewEvent.type} className="w-full max-h-[80vh] object-contain bg-black" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
