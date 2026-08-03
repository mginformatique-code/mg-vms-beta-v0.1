import React, { useState, useEffect, useMemo } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Clock, Camera as CamIcon, RefreshCw, Loader2, ZoomIn, ZoomOut } from "lucide-react";

const LAYER_META = {
  event:     { label: "Événement", color: "#0044FF" },
  alert:     { label: "Alerte",    color: "#FF3333" },
  plate:     { label: "Plaque",    color: "#FFB800" },
  recording: { label: "Segment",   color: "#666" },
};

const RANGE_PRESETS = [
  { label: "1h", hours: 1 },
  { label: "6h", hours: 6 },
  { label: "12h", hours: 12 },
  { label: "24h", hours: 24 },
  { label: "7j", hours: 168 },
];

export default function Timeline() {
  const [cameras, setCameras] = useState([]);
  const [selectedCams, setSelectedCams] = useState([]);
  const [hours, setHours] = useState(24);
  const [enabledLayers, setEnabledLayers] = useState(
    { event: true, alert: true, plate: true, recording: true },
  );
  const [data, setData] = useState({ since: null, until: null, event: [], alert: [], plate: [], recording: [] });
  const [loading, setLoading] = useState(true);
  const [hovered, setHovered] = useState(null);

  useEffect(() => {
    api.get("/cameras")
      .then((r) => { setCameras(r.data); setSelectedCams(r.data.map((c) => c.id)); })
      .catch(() => {});
  }, []);

  const load = async () => {
    if (selectedCams.length === 0) { setData({ event: [], alert: [], plate: [], recording: [] }); return; }
    setLoading(true);
    try {
      const layers = Object.entries(enabledLayers).filter(([, v]) => v).map(([k]) => (
        k === "event" ? "events" : k === "alert" ? "alerts" : k === "plate" ? "plates" : "recordings"
      )).join(",");
      const until = new Date().toISOString();
      const since = new Date(Date.now() - hours * 3600 * 1000).toISOString();
      const { data: d } = await api.get("/timeline", {
        params: {
          since, until,
          camera_ids: selectedCams.join(","),
          layers,
          limit_per_layer: 1000,
        },
      });
      setData({
        since: d.since, until: d.until,
        event: d.events || [],
        alert: d.alerts || [],
        plate: d.plates || [],
        recording: d.recordings || [],
      });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [selectedCams.join(","), hours, JSON.stringify(enabledLayers)]);

  const timeRange = useMemo(() => {
    if (!data.since || !data.until) return { start: 0, end: 1 };
    return { start: new Date(data.since).getTime(), end: new Date(data.until).getTime() };
  }, [data.since, data.until]);

  const posPct = (iso) => {
    const t = new Date(iso).getTime();
    const span = timeRange.end - timeRange.start;
    if (span <= 0) return 0;
    return Math.max(0, Math.min(100, ((t - timeRange.start) / span) * 100));
  };

  const totalCount = ["event", "alert", "plate", "recording"]
    .filter((k) => enabledLayers[k]).reduce((s, k) => s + (data[k]?.length || 0), 0);

  return (
    <div className="p-4 md:p-6" data-testid="timeline-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="font-head font-bold text-2xl flex items-center gap-2">
            <Clock size={22} className="text-[#0044FF]" /> Timeline
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Événements · alertes · plaques · segments — <span className="mono">{totalCount}</span> marqueurs
          </p>
        </div>
        <button onClick={load} data-testid="timeline-refresh"
                className="flex items-center gap-1.5 px-3 py-1.5 border border-border text-xs hover:bg-secondary">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Rafraîchir
        </button>
      </div>

      {/* Controls */}
      <div className="border border-border p-3 bg-card mb-4 space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Fenêtre :</span>
          {RANGE_PRESETS.map((p) => (
            <button key={p.label}
                    onClick={() => setHours(p.hours)}
                    data-testid={`range-${p.label}`}
                    className={`px-2 py-1 text-xs mono border ${
                      hours === p.hours ? "border-[#0044FF] text-[#0044FF]" : "border-border"}`}>
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Couches :</span>
          {Object.entries(LAYER_META).map(([k, m]) => (
            <label key={k} className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input type="checkbox"
                     checked={enabledLayers[k]}
                     onChange={(e) => setEnabledLayers({ ...enabledLayers, [k]: e.target.checked })}
                     data-testid={`layer-${k}`} />
              <span style={{ color: m.color }}>●</span> {m.label} ({data[k]?.length || 0})
            </label>
          ))}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Caméras :</span>
          <button onClick={() => setSelectedCams(cameras.map((c) => c.id))}
                  className="text-[10px] px-1.5 py-0.5 border border-border">Toutes</button>
          <button onClick={() => setSelectedCams([])}
                  className="text-[10px] px-1.5 py-0.5 border border-border">Aucune</button>
          <div className="flex gap-1 flex-wrap">
            {cameras.map((c) => {
              const on = selectedCams.includes(c.id);
              return (
                <button key={c.id}
                        onClick={() => setSelectedCams(on
                          ? selectedCams.filter((x) => x !== c.id)
                          : [...selectedCams, c.id])}
                        data-testid={`cam-toggle-${c.id}`}
                        className={`text-[10px] px-1.5 py-0.5 border ${
                          on ? "border-[#00E676] text-[#00E676]" : "border-border text-muted-foreground"}`}>
                  {c.name}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Timeline scrub par caméra */}
      {loading && !data.event.length ? (
        <div className="text-center text-muted-foreground py-12">
          <Loader2 size={20} className="animate-spin inline mr-2" /> Chargement…
        </div>
      ) : selectedCams.length === 0 ? (
        <div className="border border-dashed border-border p-8 text-center text-muted-foreground text-sm">
          Sélectionne au moins une caméra
        </div>
      ) : (
        <div className="space-y-2">
          {selectedCams.map((cid) => {
            const cam = cameras.find((c) => c.id === cid);
            return (
              <TimelineRow
                key={cid}
                camera={cam || { id: cid, name: cid }}
                items={["event", "alert", "plate", "recording"].flatMap(
                  (k) => (enabledLayers[k] ? data[k].filter((x) => x.camera_id === cid) : [])
                )}
                posPct={posPct}
                onHover={setHovered}
              />
            );
          })}
        </div>
      )}

      {/* Tooltip */}
      {hovered && (
        <div className="fixed bottom-4 right-4 border border-border p-3 bg-card shadow-lg max-w-md z-10"
             data-testid="timeline-tooltip">
          <div className="flex items-center gap-2 text-xs mono">
            <span style={{ color: LAYER_META[hovered.kind]?.color }}>●</span>
            {LAYER_META[hovered.kind]?.label} · {hovered.label}
          </div>
          <div className="text-[10px] text-muted-foreground mono mt-1">
            {new Date(hovered.timestamp).toLocaleString("fr-FR")} · {hovered.camera_name || hovered.camera_id}
          </div>
          {hovered.message && <div className="text-xs mt-1">{hovered.message}</div>}
          {hovered.engine && (
            <div className="text-[10px] mono text-[#0044FF] mt-1">Moteur : {hovered.engine}</div>
          )}
          {hovered.detectors?.length > 0 && (
            <div className="text-[10px] mono text-muted-foreground mt-1">
              Détecteurs : {hovered.detectors.join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


function TimelineRow({ camera, items, posPct, onHover }) {
  return (
    <div className="flex items-stretch gap-2 border border-border bg-card">
      <div className="w-40 flex-shrink-0 px-3 py-2 border-r border-border flex items-center gap-2">
        <CamIcon size={12} className="text-muted-foreground" />
        <span className="text-xs truncate" title={camera.name}>{camera.name}</span>
        <span className="mono text-[10px] text-muted-foreground ml-auto">{items.length}</span>
      </div>
      <div className="flex-1 relative h-10 bg-black/40" data-testid={`row-${camera.id}`}>
        {items.map((it, i) => (
          <div
            key={`${it.kind}-${it.id}-${i}`}
            onMouseEnter={() => onHover(it)}
            onMouseLeave={() => onHover(null)}
            className="absolute top-0 bottom-0 w-1 hover:w-2 cursor-pointer transition-all"
            style={{
              left: `${posPct(it.timestamp)}%`,
              background: LAYER_META[it.kind]?.color || "#fff",
              boxShadow: it.severity === "critical" ? "0 0 4px #FF3333" : "none",
            }}
            title={`${LAYER_META[it.kind]?.label} · ${it.label} · ${new Date(it.timestamp).toLocaleTimeString()}`}
            data-testid={`marker-${it.kind}-${it.id}`}
          />
        ))}
      </div>
    </div>
  );
}
