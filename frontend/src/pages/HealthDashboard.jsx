/**
 * HealthDashboard — Page dédiée /diagnostics/dashboard (P1 stabilisation).
 * Poll toutes les 5s l'endpoint /api/diagnostics/health-dashboard et affiche
 * système, mongo, IA, plugins, caméras, recorder en un coup d'œil.
 */
import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import {
  Activity, Cpu, HardDrive, Database, Zap, Video, Package,
  AlertTriangle, CheckCircle2, XCircle, RefreshCw,
} from "lucide-react";

const OK = "#00E676";
const WARN = "#FFB800";
const ERR = "#FF3333";

function Metric({ label, value, unit = "", color, warn, err, icon: Icon }) {
  let c = color || OK;
  if (typeof value === "number") {
    if (err !== undefined && value >= err) c = ERR;
    else if (warn !== undefined && value >= warn) c = WARN;
  }
  return (
    <div className="border border-border p-3 bg-card">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-muted-foreground">
        {Icon && <Icon size={11} />} {label}
      </div>
      <div className="text-2xl font-head font-bold mono mt-1" style={{ color: c }}>
        {value}{unit}
      </div>
    </div>
  );
}

export default function HealthDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const load = async () => {
    try {
      const r = await api.get("/diagnostics/health-dashboard");
      setData(r.data);
      setError(null);
      setLastUpdate(new Date());
    } catch (e) {
      setError(e?.response?.data?.detail || e.message);
    }
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, []);

  if (!data && !error) {
    return <div className="p-6 text-sm text-muted-foreground">Chargement Health Dashboard…</div>;
  }
  if (error) {
    return <div className="p-6 text-sm text-[#FF3333]">Erreur : {error}</div>;
  }

  const s = data.system || {};
  const m = data.mongo || {};
  const ai = data.ai || {};
  const p = data.plugins || {};
  const cams = data.cameras || [];
  const rec = data.recorder || {};

  return (
    <div className="p-4 space-y-4" data-testid="health-dashboard-page">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-2">
        <div>
          <h1 className="font-head font-bold text-2xl flex items-center gap-2">
            <Activity size={20} className="text-[#00E676]" />
            Health Dashboard
            <span className="text-[10px] px-1.5 py-0.5 border border-[#00E676] text-[#00E676] mono uppercase">P1</span>
          </h1>
          <p className="text-xs text-muted-foreground">
            Vue temps-réel de la stabilité du VMS · refresh 5s
          </p>
        </div>
        <div className="flex items-center gap-2 text-[10px] mono text-muted-foreground">
          <RefreshCw size={11} className="animate-spin" />
          {lastUpdate && <span>Dernière MAJ : {lastUpdate.toLocaleTimeString()}</span>}
        </div>
      </div>

      {/* Système */}
      <section>
        <h2 className="font-head font-semibold text-sm mb-2 flex items-center gap-1.5">
          <Cpu size={14} className="text-[#0044FF]" /> Système
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Metric label="CPU" value={s.cpu_percent?.toFixed(1)} unit="%" warn={70} err={90} icon={Cpu} />
          <Metric label="RAM" value={s.ram_percent?.toFixed(1)} unit="%" warn={80} err={95} icon={Cpu} />
          <Metric label="Disque" value={s.disk_percent?.toFixed(1)} unit="%" warn={80} err={95} icon={HardDrive} />
          <Metric label="Uptime" value={Math.floor((s.uptime_seconds || 0) / 60)} unit=" min" icon={Activity} />
        </div>
      </section>

      {/* Mongo + AI + Plugins */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-2">
        <div className="border border-border p-3 bg-card" data-testid="mongo-panel">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            <Database size={11} /> MongoDB
          </div>
          <div className="mt-1">
            <span className="text-xl mono font-bold" style={{ color: m.status === "ok" ? OK : ERR }}>
              {m.status?.toUpperCase() || "?"}
            </span>
            <span className="text-[11px] text-muted-foreground ml-2">ping {m.ping_ms}ms</span>
          </div>
          {m.collections && (
            <div className="text-[10px] mono text-muted-foreground mt-1">
              cams: {m.collections.cameras} · events: {m.collections.events} · rec: {m.collections.recordings}
            </div>
          )}
        </div>
        <div className="border border-border p-3 bg-card" data-testid="ai-panel">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            <Zap size={11} /> IA
          </div>
          <div className="mt-1 space-y-0.5 text-[11px] mono">
            <div>
              YOLO : <span style={{ color: ai.yolo_loaded ? OK : ERR }}>{ai.yolo_loaded ? "loaded" : "off"}</span>
              {ai.yolo_device && <span className="text-muted-foreground"> ({ai.yolo_device})</span>}
            </div>
            <div>
              ALPR : <span style={{ color: ai.alpr_loaded ? OK : ERR }}>{ai.alpr_loaded ? "loaded" : "off"}</span>
            </div>
            {ai.yolo_error && <div className="text-[#FF3333] truncate" title={ai.yolo_error}>err: {ai.yolo_error}</div>}
          </div>
        </div>
        <div className="border border-border p-3 bg-card" data-testid="plugins-panel">
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            <Package size={11} /> Plugins
          </div>
          <div className="mt-1 text-[11px] mono">
            <span className="text-xl font-bold text-foreground">{p.total || 0}</span>
            <span className="text-muted-foreground"> total · </span>
            <span className="text-[#00E676] font-bold">{p.dispatchable || 0}</span>
            <span className="text-muted-foreground"> dispatchable</span>
          </div>
          {p.by_state && (
            <div className="text-[9px] mono text-muted-foreground mt-1 space-y-0.5">
              {Object.entries(p.by_state).map(([st, n]) => (
                <span key={st} className="mr-2">
                  {st}: <b className="text-foreground">{n}</b>
                </span>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Caméras */}
      <section>
        <h2 className="font-head font-semibold text-sm mb-2 flex items-center gap-1.5">
          <Video size={14} className="text-[#FFB800]" /> Caméras ({cams.length})
        </h2>
        {cams.length === 0 ? (
          <div className="text-xs text-muted-foreground py-4 text-center border border-border">
            Aucune caméra configurée
          </div>
        ) : (
          <div className="border border-border overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead className="bg-secondary/40 text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="text-left p-2">Caméra</th>
                  <th className="text-left p-2">État</th>
                  <th className="text-right p-2">Coupures 24h</th>
                  <th className="text-right p-2">Reco moy.</th>
                  <th className="text-left p-2">Dernier segment</th>
                </tr>
              </thead>
              <tbody>
                {cams.map((c) => {
                  const status = c.status || "unknown";
                  const cErr = status === "down" || status === "error";
                  const cWarn = status === "warning";
                  return (
                    <tr key={c.id} className="border-t border-border" data-testid={`cam-row-${c.id}`}>
                      <td className="p-2 font-semibold">{c.name} <span className="text-[10px] mono text-muted-foreground">{c.id}</span></td>
                      <td className="p-2">
                        <span className="mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 border"
                              style={{ borderColor: cErr ? ERR : cWarn ? WARN : OK,
                                        color: cErr ? ERR : cWarn ? WARN : OK }}>
                          {status}
                        </span>
                      </td>
                      <td className="p-2 text-right mono" style={{ color: (c.disconnects_24h || 0) > 3 ? WARN : "inherit" }}>
                        {c.disconnects_24h ?? 0}
                      </td>
                      <td className="p-2 text-right mono text-muted-foreground">
                        {c.avg_reconnect_s ? `${c.avg_reconnect_s}s` : "—"}
                      </td>
                      <td className="p-2 text-[10px] mono text-muted-foreground">
                        {c.last_segment?.end_ts || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Recorder */}
      <section>
        <h2 className="font-head font-semibold text-sm mb-2 flex items-center gap-1.5">
          <HardDrive size={14} className="text-[#A855F7]" /> Recorder ({rec.ffmpeg_processes?.length || 0} FFmpeg vivants)
        </h2>
        {(rec.cameras || []).length === 0 ? (
          <div className="text-xs text-muted-foreground py-2 text-center border border-border">
            Aucun enregistrement actif
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {rec.cameras.map((c) => {
              const gapWarn = c.gap_warning;
              return (
                <div key={c.camera_id}
                     className="border p-2 text-[11px]"
                     style={{ borderColor: gapWarn ? WARN : "hsl(var(--border))",
                              borderLeftColor: gapWarn ? WARN : "hsl(var(--border))", borderLeftWidth: 3 }}
                     data-testid={`recorder-${c.camera_id}`}>
                  <div className="font-semibold">{c.name}</div>
                  <div className="mono text-[10px] text-muted-foreground">
                    Dernier : {c.last_segment_end || "—"}
                  </div>
                  <div className="mono text-[10px]" style={{ color: gapWarn ? WARN : OK }}>
                    Gap : {c.gap_seconds !== null ? `${Math.round(c.gap_seconds)}s` : "—"}
                    {gapWarn && <span className="ml-1"><AlertTriangle size={9} className="inline" /> alerte gap</span>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Erreurs plugins */}
      {(p.errors || []).length > 0 && (
        <section className="border border-[#FFB800]/40 bg-[#FFB800]/5 p-3">
          <h2 className="font-head font-semibold text-sm mb-2 flex items-center gap-1.5 text-[#FFB800]">
            <AlertTriangle size={14} /> Plugins avec erreurs ({p.errors.length})
          </h2>
          <div className="space-y-1">
            {p.errors.map((e) => (
              <div key={e.name} className="text-[11px] mono flex items-center gap-2">
                <XCircle size={10} className="text-[#FF3333]" />
                <b>{e.name}</b>
                <span className="text-muted-foreground">[{e.state}]</span>
                <span className="truncate">{e.msg}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
