import React, { useEffect, useMemo, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Film, Play, Calendar, Clock, HardDrive, Activity, Cctv, AlertTriangle, Circle } from "lucide-react";

const MODE_COLORS = { continuous: "#0044FF", motion: "#FFB800", ai: "#00E676" };
const HOURS = Array.from({ length: 25 });

function fmtDur(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m.toString().padStart(2, "0")}` : `${m} min`;
}
function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 border border-border bg-card" data-testid={`rec-stat-${label}`}>
      <Icon size={16} className="text-[#0044FF]" strokeWidth={1.5} />
      <div className="leading-tight">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-sm font-head font-bold mono">{value}</div>
      </div>
    </div>
  );
}

export default function Recordings() {
  const { t } = useApp();
  const [cams, setCams] = useState([]);
  const [cameraId, setCameraId] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    api.get("/cameras", { params: { status: "online" } })
      .then((r) => { setCams(r.data); if (r.data[0]) setCameraId(r.data[0].id); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!cameraId) return;
    setLoading(true);
    setSelected(null);
    api.get("/recordings/timeline", { params: { camera_id: cameraId, date } })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [cameraId, date]);

  const segments = data?.segments || [];

  const segPos = (seg) => {
    const s = new Date(seg.start);
    const startSec = s.getHours() * 3600 + s.getMinutes() * 60 + s.getSeconds();
    const left = (startSec / 86400) * 100;
    const width = (seg.duration_sec / 86400) * 100;
    return { left: `${left}%`, width: `${Math.max(width, 0.3)}%` };
  };

  const play = (seg) => {
    setSelected(seg);
    api.get(`/recordings/${seg.id}/playback`).catch(() => {});
  };

  return (
    <div className="p-4 md:p-6 space-y-5" data-testid="recordings-page">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Film size={22} className="text-[#0044FF]" /> {t("rec.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">{t("rec.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1.5 border border-border bg-card px-2">
            <Cctv size={15} className="text-muted-foreground" />
            <select data-testid="rec-camera-select" value={cameraId} onChange={(e) => setCameraId(e.target.value)}
              className="bg-transparent text-sm py-2 outline-none min-w-[180px]">
              {cams.map((c) => <option key={c.id} value={c.id}>{c.name} — {c.site_name}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-1.5 border border-border bg-card px-2">
            <Calendar size={15} className="text-muted-foreground" />
            <input data-testid="rec-date-input" type="date" value={date} max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setDate(e.target.value)} className="bg-transparent text-sm py-2 outline-none" />
          </div>
        </div>
      </div>

      {!cameraId ? (
        <div className="text-muted-foreground text-sm py-20 text-center">{t("rec.no_camera")}</div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <Stat icon={Clock} label={t("rec.coverage")} value={data ? fmtDur(data.coverage_sec) : "—"} />
            <Stat icon={HardDrive} label={t("rec.size")} value={data ? `${data.total_size_mb} MB` : "—"} />
            <Stat icon={Activity} label={t("rec.segments")} value={segments.length} />
            <Stat icon={AlertTriangle} label={t("rec.events")} value={data?.event_count ?? 0} />
          </div>

          <div className="grid lg:grid-cols-3 gap-4">
            {/* Player */}
            <div className="lg:col-span-2 space-y-3">
              <div className="relative bg-black aspect-video overflow-hidden border border-border" data-testid="rec-player">
                {selected ? (
                  <>
                    <img src={selected.thumbnail} alt="" className="w-full h-full object-cover opacity-80" />
                    <div className="absolute inset-0 flex items-center justify-center">
                      <div className="w-16 h-16 rounded-full bg-[#0044FF]/80 flex items-center justify-center">
                        <Play size={28} className="text-white ml-1" fill="white" />
                      </div>
                    </div>
                    <div className="absolute top-0 inset-x-0 flex items-center justify-between px-3 py-2 bg-gradient-to-b from-black/80 to-transparent">
                      <span className="text-xs mono text-white">{data?.camera?.name}</span>
                      <span className="flex items-center gap-1 text-[10px] mono text-[#FF3333]">
                        <Circle size={7} className="fill-[#FF3333] rec-dot" /> {t("rec.playing")}
                      </span>
                    </div>
                    <div className="absolute bottom-0 inset-x-0 px-3 py-2 bg-gradient-to-t from-black/80 to-transparent">
                      <div className="text-xs mono text-white">{fmtTime(selected.start)} – {fmtTime(selected.end)} · {fmtDur(selected.duration_sec)}</div>
                      <div className="text-[10px] text-white/60 mt-0.5">{t("rec.simulated")}</div>
                    </div>
                  </>
                ) : (
                  <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-white/40">
                    <Film size={32} />
                    <span className="text-xs">{t("rec.select_segment")}</span>
                  </div>
                )}
              </div>

              {/* Timeline 24h */}
              <div className="border border-border bg-card p-3" data-testid="rec-timeline">
                <div className="relative h-10 bg-secondary/50 overflow-hidden">
                  {/* hour grid */}
                  {HOURS.map((_, h) => (
                    <div key={h} className="absolute top-0 bottom-0 border-l border-border/40"
                      style={{ left: `${(h / 24) * 100}%` }} />
                  ))}
                  {/* segments */}
                  {segments.map((seg) => (
                    <button key={seg.id} data-testid={`rec-segment-${seg.id}`} title={`${fmtTime(seg.start)} · ${t(`rec.mode.${seg.mode}`)}`}
                      onClick={() => play(seg)} style={{ ...segPos(seg), backgroundColor: MODE_COLORS[seg.mode] }}
                      className={`absolute top-2 bottom-2 hover:brightness-125 transition-all ${selected?.id === seg.id ? "ring-2 ring-white z-10" : ""}`}>
                      {seg.has_event && <span className="absolute -top-1.5 left-1/2 -translate-x-1/2 w-1.5 h-1.5 rounded-full bg-[#FF3333]" />}
                    </button>
                  ))}
                </div>
                {/* hour labels */}
                <div className="relative h-4 mt-1">
                  {[0, 4, 8, 12, 16, 20, 24].map((h) => (
                    <span key={h} className="absolute text-[9px] mono text-muted-foreground -translate-x-1/2"
                      style={{ left: `${(h / 24) * 100}%` }}>{h.toString().padStart(2, "0")}:00</span>
                  ))}
                </div>
                {/* legend */}
                <div className="flex items-center gap-4 mt-3 flex-wrap">
                  {Object.entries(MODE_COLORS).map(([k, c]) => (
                    <span key={k} className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                      <span className="w-3 h-2" style={{ backgroundColor: c }} /> {t(`rec.mode.${k}`)}
                    </span>
                  ))}
                  <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#FF3333]" /> {t("rec.event_marker")}
                  </span>
                </div>
              </div>
            </div>

            {/* Segment list */}
            <div className="border border-border bg-card flex flex-col max-h-[560px]" data-testid="rec-segment-list">
              <div className="px-3 py-2 border-b border-border text-xs uppercase tracking-wider text-muted-foreground font-medium">
                {t("rec.segments")} · {segments.length}
              </div>
              <div className="flex-1 overflow-y-auto divide-y divide-border">
                {loading ? (
                  <div className="p-4 text-sm text-muted-foreground">{t("common.loading")}</div>
                ) : segments.length === 0 ? (
                  <div className="p-4 text-sm text-muted-foreground">{t("rec.no_segments")}</div>
                ) : segments.map((seg) => (
                  <button key={seg.id} data-testid={`rec-listitem-${seg.id}`} onClick={() => play(seg)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-secondary transition-colors ${selected?.id === seg.id ? "bg-secondary" : ""}`}>
                    <img src={seg.thumbnail} alt="" className="w-14 h-9 object-cover bg-black shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="text-xs mono">{fmtTime(seg.start)} – {fmtTime(seg.end)}</div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[9px] uppercase tracking-wider px-1 py-0.5" style={{ color: MODE_COLORS[seg.mode] }}>{t(`rec.mode.${seg.mode}`)}</span>
                        <span className="text-[10px] text-muted-foreground mono">{seg.size_mb} MB</span>
                        {seg.has_event && <AlertTriangle size={11} className="text-[#FF3333]" />}
                      </div>
                    </div>
                    <Play size={14} className="text-muted-foreground shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
