import React, { useEffect, useState, useRef } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Maximize2, Camera as CamIcon, Move, ZoomIn, ZoomOut, Circle } from "lucide-react";

const LAYOUTS = [1, 4, 9, 16, 25, 36, 49, 64];
const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function streamUrl(camId) {
  const token = localStorage.getItem("mg_token");
  return `${API}/stream/${camId}/live.mjpeg?token=${encodeURIComponent(token || "")}`;
}

function Feed({ cam, idx, canPtz, hd }) {
  const [hover, setHover] = useState(false);
  const [failed, setFailed] = useState(false);
  const online = cam?.status === "online";
  const showStream = online && !failed;
  useEffect(() => { setFailed(false); }, [cam?.id]);
  const ptz = async (command) => { try { await api.post(`/cameras/${cam.id}/ptz?command=${command}`); } catch (e) {} };
  return (
    <div className="relative bg-black overflow-hidden group" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} data-testid="video-feed">
      {showStream ? (
        <img src={streamUrl(cam.id)} alt="" className="w-full h-full object-cover"
          onError={() => setFailed(true)} data-testid="live-stream" />
      ) : (
        <div className="w-full h-full flex items-center justify-center bg-[#0a0a0a]">
          <div className="text-center"><CamIcon size={24} className="mx-auto text-[#FF3333] mb-1" /><span className="text-[10px] uppercase tracking-wider text-[#FF3333]">{cam ? "No Signal" : "—"}</span></div>
        </div>
      )}
      <div className="absolute top-0 inset-x-0 flex items-center justify-between px-2 py-1 bg-gradient-to-b from-black/70 to-transparent">
        <span className="text-[10px] mono text-white truncate">{cam?.name || `CAM-${idx + 1}`}</span>
        <div className="flex items-center gap-1.5">
          {showStream && <span data-testid="feed-quality" className="text-[8px] mono px-1 font-bold" style={{ color: hd ? "#00E676" : "#FFB800" }}>{hd ? "HD" : "SD"}</span>}
          {showStream && <span className="flex items-center gap-1 text-[9px] mono text-[#00E676]"><Circle size={6} className="fill-[#00E676] rec-dot" /> LIVE</span>}
        </div>
      </div>
      <div className="absolute bottom-0 inset-x-0 px-2 py-1 bg-gradient-to-t from-black/70 to-transparent flex justify-between">
        <span className="text-[9px] mono text-white/70">{cam?.site_name || ""}</span>
        <span className="text-[9px] mono text-white/70">{new Date().toLocaleTimeString()}</span>
      </div>
      {hover && showStream && cam?.ptz_enabled && canPtz && (
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
  const { t, hasPerm } = useApp();
  const [cams, setCams] = useState([]);
  const [layout, setLayout] = useState(4);
  const ref = useRef(null);
  const canPtz = hasPerm("ptz_control");
  const hd = hasPerm("stream_hd");

  useEffect(() => {
    api.get("/cameras").then((r) => {
      const sorted = [...r.data].sort((a, b) =>
        (b.id === "demo-cam-001") - (a.id === "demo-cam-001") ||
        (b.status === "online") - (a.status === "online"));
      setCams(sorted);
    }).catch(() => {});
  }, []);

  const cols = Math.sqrt(layout);
  const slots = Array.from({ length: layout });

  return (
    <div className="p-4 h-full flex flex-col">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("live.title")}</h1>
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-muted-foreground mr-1">{t("live.layout")}</span>
          {LAYOUTS.map((l) => (
            <button key={l} onClick={() => setLayout(l)} data-testid={`layout-${l}`}
              className={`w-9 h-8 text-xs mono border transition-colors ${layout === l ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border hover:bg-secondary"}`}>{l}</button>
          ))}
          <button onClick={() => ref.current?.requestFullscreen?.()} data-testid="fullscreen-btn" className="w-9 h-8 border border-border hover:bg-secondary flex items-center justify-center"><Maximize2 size={15} /></button>
        </div>
      </div>
      <div ref={ref} className="flex-1 grid gap-1 bg-background" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))`, gridAutoRows: "1fr" }}>
        {slots.map((_, i) => <Feed key={cams[i]?.id || `empty-${i}`} cam={cams[i]} idx={i} canPtz={canPtz} hd={hd} />)}
      </div>
    </div>
  );
}
