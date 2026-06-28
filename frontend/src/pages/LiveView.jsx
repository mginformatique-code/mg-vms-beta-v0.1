import React, { useEffect, useState, useRef } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Maximize2, Camera as CamIcon, Move, ZoomIn, ZoomOut, Circle, Volume2 } from "lucide-react";

const LAYOUTS = [1, 4, 9, 16, 25, 36, 49, 64];
const FEEDS = [
  "https://images.unsplash.com/photo-1707829248830-578d2b0cbe65?w=600&q=70",
  "https://images.unsplash.com/photo-1693541684739-e714db2637e2?w=600&q=70",
];

function Feed({ cam, idx }) {
  const [hover, setHover] = useState(false);
  const online = cam?.status === "online";
  const img = FEEDS[idx % FEEDS.length];
  return (
    <div className="relative bg-black overflow-hidden group" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} data-testid="video-feed">
      {online ? (
        <img src={img} alt="" className="w-full h-full object-cover opacity-90" />
      ) : (
        <div className="w-full h-full flex items-center justify-center bg-[#0a0a0a]">
          <div className="text-center"><CamIcon size={24} className="mx-auto text-[#FF3333] mb-1" /><span className="text-[10px] uppercase tracking-wider text-[#FF3333]">No Signal</span></div>
        </div>
      )}
      <div className="absolute top-0 inset-x-0 flex items-center justify-between px-2 py-1 bg-gradient-to-b from-black/70 to-transparent">
        <span className="text-[10px] mono text-white truncate">{cam?.name || `CAM-${idx + 1}`}</span>
        {online && <span className="flex items-center gap-1 text-[9px] mono text-[#FF3333]"><Circle size={6} className="fill-[#FF3333] rec-dot" /> REC</span>}
      </div>
      <div className="absolute bottom-0 inset-x-0 px-2 py-1 bg-gradient-to-t from-black/70 to-transparent flex justify-between">
        <span className="text-[9px] mono text-white/70">{cam?.site_name || ""}</span>
        <span className="text-[9px] mono text-white/70">{new Date().toLocaleTimeString()}</span>
      </div>
      {hover && online && cam?.ptz_enabled && (
        <div className="absolute inset-0 flex items-center justify-center gap-1 bg-black/30">
          <div className="grid grid-cols-3 gap-0.5">
            {[ZoomIn, Move, ZoomOut].map((Ic, i) => (
              <button key={i} className="w-7 h-7 bg-black/60 hover:bg-[#0044FF] flex items-center justify-center text-white"><Ic size={14} /></button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function LiveView() {
  const { t } = useApp();
  const [cams, setCams] = useState([]);
  const [layout, setLayout] = useState(9);
  const ref = useRef(null);

  useEffect(() => { api.get("/cameras").then((r) => setCams(r.data)).catch(() => {}); }, []);

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
        {slots.map((_, i) => <Feed key={i} cam={cams[i % (cams.length || 1)]} idx={i} />)}
      </div>
    </div>
  );
}
