import React, { useEffect, useState, useCallback } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Zap, RefreshCw, Camera as CamIcon } from "lucide-react";
import EventViewer from "@/components/EventViewer";

const TYPE_COLORS = {
  "Personne": "#FF3333", "Voiture": "#0044FF", "Camion": "#0044FF", "Bus": "#0044FF",
  "Moto": "#0044FF", "Vélo": "#00E676", "Animal": "#FFB800", "Mouvement": "#FFB800",
};
const TYPES = ["Mouvement", "Personne", "Voiture", "Camion", "Bus", "Moto", "Vélo", "Animal"];

export default function Events() {
  const { t } = useApp();
  const [events, setEvents] = useState([]);
  const [cams, setCams] = useState([]);
  const [type, setType] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [viewerIdx, setViewerIdx] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 60 };
      if (type) params.type = type;
      if (cameraId) params.camera_id = cameraId;
      const r = await api.get("/events", { params });
      setEvents(r.data);
      setTotal(parseInt(r.headers["x-total-count"] || r.data.length, 10));
    } catch (e) {} finally { setLoading(false); }
  }, [type, cameraId]);

  useEffect(() => { api.get("/cameras").then((r) => setCams(r.data)).catch(() => {}); }, []);
  useEffect(() => { load(); const iv = setInterval(load, 15000); return () => clearInterval(iv); }, [load]);

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="events-page">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Zap size={22} className="text-[#0044FF]" /> Événements IA
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">Détections IA temps réel — <span className="mono">{total}</span> au total</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select data-testid="events-type-filter" value={type} onChange={(e) => setType(e.target.value)} className="border border-border bg-card text-sm px-2 py-2 outline-none">
            <option value="">Tous les types</option>
            {TYPES.map((ty) => <option key={ty} value={ty}>{ty}</option>)}
          </select>
          <select data-testid="events-camera-filter" value={cameraId} onChange={(e) => setCameraId(e.target.value)} className="border border-border bg-card text-sm px-2 py-2 outline-none">
            <option value="">Toutes les caméras</option>
            {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={load} data-testid="events-refresh-btn" className="p-2 border border-border hover:bg-secondary"><RefreshCw size={15} className={loading ? "animate-spin" : ""} /></button>
        </div>
      </div>

      {events.length === 0 ? (
        <div className="text-muted-foreground text-sm py-20 text-center">Aucun événement détecté pour ces filtres.</div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
          {events.map((e, i) => (
            <button key={e.id} onClick={() => setViewerIdx(i)} className="border border-border bg-card overflow-hidden text-left hover:border-[#0044FF] transition-colors" data-testid="event-card">
              <div className="relative bg-black aspect-video cursor-zoom-in">
                {e.thumbnail ? (
                  <img src={e.thumbnail} alt={e.type} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center"><CamIcon size={20} className="text-white/30" /></div>
                )}
                <span className="absolute top-1.5 left-1.5 text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 text-white" style={{ backgroundColor: TYPE_COLORS[e.type] || "#0044FF" }}>{e.type}</span>
                {e.confidence != null && <span className="absolute top-1.5 right-1.5 text-[10px] mono px-1.5 py-0.5 bg-black/70 text-white">{Math.round(e.confidence * 100)}%</span>}
              </div>
              <div className="px-2.5 py-2 space-y-0.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs truncate">{e.camera_name}</span>
                  {e.vehicle_color && <span className="text-[10px] px-1.5 border border-border text-muted-foreground shrink-0">{e.vehicle_color}</span>}
                  {e.motion_pct != null && <span className="text-[10px] mono text-muted-foreground shrink-0">{e.motion_pct}%</span>}
                </div>
                <div className="text-[10px] mono text-muted-foreground" data-testid="event-timestamp">{new Date(e.timestamp).toLocaleString("fr-FR")}</div>
              </div>
            </button>
          ))}
        </div>
      )}

      {viewerIdx !== null && (
        <EventViewer items={events} index={viewerIdx} onIndex={setViewerIdx} onClose={() => setViewerIdx(null)} kind="event" />
      )}
    </div>
  );
}
