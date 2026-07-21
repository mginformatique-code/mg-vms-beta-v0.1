import React, { useEffect, useState, useRef } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Maximize2, Camera as CamIcon, Move, ZoomIn, ZoomOut, Circle, Eye, EyeOff } from "lucide-react";

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

function streamUrl(camId) {
  const token = localStorage.getItem("mg_token");
  return `${API}/stream/${camId}/live.mjpeg?token=${encodeURIComponent(token || "")}`;
}

function OverlayCanvas({ cam, boxes, showOverlay }) {
  const ref = useRef(null);
  const box = useRef(null);
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

function Feed({ cam, idx, canPtz, hd, showOverlay, aiState }) {
  const [hover, setHover] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const retryTimer = useRef(null);
  const online = cam?.status === "online";
  useEffect(() => { setReloadKey(0); }, [cam?.id]);
  useEffect(() => () => { if (retryTimer.current) clearTimeout(retryTimer.current); }, []);
  const handleError = () => {
    if (retryTimer.current) clearTimeout(retryTimer.current);
    retryTimer.current = setTimeout(() => setReloadKey((k) => k + 1), 2500);
  };
  const ptz = async (command) => { try { await api.post(`/cameras/${cam.id}/ptz?command=${command}`); } catch (e) {} };

  const boxes = aiState?.boxes || [];
  const counts = aiState?.counts || {};
  const totalDetected = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="relative bg-black overflow-hidden group" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} data-testid="video-feed">
      {online ? (
        <>
          <img
            src={`${streamUrl(cam.id)}&r=${reloadKey}`}
            alt="" className="w-full h-full object-cover"
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
          {online && <span data-testid="feed-quality" className="text-[8px] mono px-1 font-bold" style={{ color: hd ? "#00E676" : "#FFB800" }}>{hd ? "HD" : "SD"}</span>}
          {online && <span className="flex items-center gap-1 text-[9px] mono text-[#00E676]"><Circle size={6} className="fill-[#00E676] rec-dot" /> LIVE</span>}
        </div>
      </div>
      <div className="absolute bottom-0 inset-x-0 px-2 py-1 bg-gradient-to-t from-black/70 to-transparent flex justify-between">
        <span className="text-[9px] mono text-white/70">{cam?.site_name || ""}</span>
        <span className="text-[9px] mono text-white/70">{new Date().toLocaleTimeString()}</span>
      </div>
      {hover && online && cam?.ptz_enabled && canPtz && (
        <div className="absolute inset-0 flex items-center justify-center gap-1 bg-black/30" data-testid="ptz-controls">
          <div className="grid grid-cols-3 gap-0.5">
            {[[ZoomIn, "zoom_in"], [Move, "home"], [ZoomOut, "zoom_out"]].map(([Ic, cmd], i) => (
              <button key={i} onClick={() => ptz(cmd)} className="w-7 h-7 bg-black/60 hover:bg-[#0044FF] flex items-center justify-center text-white"><Ic size={14} /></button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function LiveView() {
  const { t, can, aiDetections } = useApp();
  const [cams, setCams] = useState([]);
  const [layout, setLayout] = useState(4);
  const [hd, setHd] = useState(false);
  const [showOverlay, setShowOverlay] = useState(() => localStorage.getItem("mg_ai_overlay") !== "off");
  const canPtz = can("technician");

  useEffect(() => {
    api.get("/cameras").then((r) => setCams(r.data));
    const iv = setInterval(() => api.get("/cameras").then((r) => setCams(r.data)).catch(() => {}), 20000);
    return () => clearInterval(iv);
  }, []);
  useEffect(() => { localStorage.setItem("mg_ai_overlay", showOverlay ? "on" : "off"); }, [showOverlay]);

  const goFull = () => { const el = document.getElementById("live-grid"); if (el?.requestFullscreen) el.requestFullscreen(); };
  const cols = Math.ceil(Math.sqrt(layout));
  const gridStyle = { display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gridAutoRows: "1fr", gap: 2, aspectRatio: `${cols} / ${Math.ceil(layout / cols)}` };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("live.title")}</h1>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowOverlay((v) => !v)} data-testid="toggle-ai-overlay"
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs border ${showOverlay ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border hover:bg-secondary"}`}
            title="Afficher/masquer les détections IA">
            {showOverlay ? <Eye size={13} /> : <EyeOff size={13} />} Overlay IA
          </button>
          <button onClick={() => setHd(!hd)} data-testid="hd-toggle" className={`px-2.5 py-1.5 text-xs border ${hd ? "bg-[#00E676] text-black border-[#00E676]" : "border-border"} hover:opacity-80`}>{hd ? "HD" : "SD"}</button>
          {LAYOUTS.map((n) => (
            <button key={n} onClick={() => setLayout(n)} data-testid={`layout-${n}`}
              className={`px-2.5 py-1.5 text-xs mono ${layout === n ? "bg-[#0044FF] text-white" : "border border-border hover:bg-secondary"}`}>{n}</button>
          ))}
          <button onClick={goFull} data-testid="fullscreen-btn" className="px-2.5 py-1.5 text-xs border border-border hover:bg-secondary flex items-center gap-1"><Maximize2 size={13} /> {t("live.fullscreen")}</button>
        </div>
      </div>

      <div id="live-grid" className="bg-background" style={gridStyle}>
        {Array.from({ length: layout }).map((_, i) => (
          <Feed key={i} cam={cams[i]} idx={i} canPtz={canPtz} hd={hd}
                showOverlay={showOverlay}
                aiState={cams[i] ? aiDetections[cams[i].id] : null} />
        ))}
      </div>
    </div>
  );
}
