import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar } from "recharts";
import { Cctv, Wifi, WifiOff, Building2, Activity, Bell, ScanLine, Cpu, MemoryStick, HardDrive, Thermometer, Gauge, Clock } from "lucide-react";
import EventViewer from "@/components/EventViewer";

const PIE_COLORS = ["#0044FF", "#00E676", "#FFB800", "#FF3333", "#A855F7", "#06B6D4", "#EC4899", "#84CC16", "#F97316"];

function Kpi({ icon: Icon, label, value, accent, delay }) {
  return (
    <div className="bg-card border border-border p-4 fade-up" style={{ animationDelay: `${delay}ms` }} data-testid={`kpi-${label}`}>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2">{label}</div>
          <div className="font-head font-black text-3xl tracking-tight" style={{ color: accent }}>{value}</div>
        </div>
        <Icon size={20} strokeWidth={1.5} style={{ color: accent }} className="opacity-70" />
      </div>
    </div>
  );
}

function Health({ icon: Icon, label, value, unit, max = 100 }) {
  const pct = Math.min(100, (value / max) * 100);
  const color = pct > 80 ? "#FF3333" : pct > 65 ? "#FFB800" : "#00E676";
  return (
    <div className="flex items-center gap-3 py-2">
      <Icon size={16} strokeWidth={1.5} className="text-muted-foreground shrink-0" />
      <span className="text-xs w-24 text-muted-foreground">{label}</span>
      <div className="flex-1 h-2 bg-secondary overflow-hidden">
        <div style={{ width: `${pct}%`, backgroundColor: color }} className="h-full transition-all duration-500" />
      </div>
      <span className="text-xs mono w-16 text-right">{value}{unit}</span>
    </div>
  );
}

export default function Dashboard() {
  const { t, theme, liveMetrics, alertPing } = useApp();
  const [stats, setStats] = useState(null);
  const [ts, setTs] = useState({ hourly: [], breakdown: [] });
  const [alerts, setAlerts] = useState([]);
  const [viewerIdx, setViewerIdx] = useState(null);
  const viewerItems = alerts.map((a) => ({
    id: a.id, thumbnail: a.thumbnail || a.plate_crop,
    camera_id: a.camera_id, camera_name: a.camera_name, site_name: a.site_name,
    timestamp: a.timestamp, plugin: a.plugin || (a.scenario ? `IA · ${a.scenario}` : "Alerte"),
    type: a.type || a.scenario || "alert", label: a.message, plate: a.plate,
  }));

  const loadAll = () => {
    api.get("/dashboard/stats").then((r) => setStats(r.data)).catch(() => {});
    api.get("/alerts?limit=6").then((r) => setAlerts(r.data)).catch(() => {});
  };
  useEffect(() => {
    loadAll();
    api.get("/dashboard/timeseries").then((r) => setTs(r.data)).catch(() => {});
  }, []);

  // Temps réel : métriques live + rechargement sur nouvelle alerte
  useEffect(() => {
    if (liveMetrics) setStats((s) => (s ? { ...s, system: liveMetrics } : s));
  }, [liveMetrics]);
  useEffect(() => { if (alertPing) loadAll(); }, [alertPing]);

  const grid = theme === "dark" ? "#1a1a1a" : "#e4e4e7";
  const sev = { critical: "#FF3333", warning: "#FFB800", info: "#0044FF" };

  if (!stats) return <div className="p-8 text-muted-foreground">{t("common.loading")}</div>;

  return (
    <div className="p-4">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-4">{t("dash.title")}</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2 mb-4">
        <Kpi icon={Cctv} label={t("dash.cameras_total")} value={stats.cameras_total} delay={0} />
        <Kpi icon={Wifi} label={t("dash.online")} value={stats.cameras_online} accent="#00E676" delay={40} />
        <Kpi icon={WifiOff} label={t("dash.offline")} value={stats.cameras_offline} accent="#FF3333" delay={80} />
        <Kpi icon={Building2} label={t("dash.sites")} value={stats.sites} delay={120} />
        <Kpi icon={Activity} label={t("dash.events")} value={stats.events_today} accent="#0044FF" delay={160} />
        <Kpi icon={Bell} label={t("dash.alerts")} value={stats.alerts_active} accent="#FFB800" delay={200} />
        <Kpi icon={ScanLine} label={t("dash.plates")} value={stats.plates_today} delay={240} />
      </div>

      <div className="grid grid-cols-1 gap-2 mb-2">
        <div className="bg-card border border-border p-4">
          <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-4">{t("dash.activity")}</div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={ts.hourly}>
              <defs>
                <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#0044FF" stopOpacity={0.5} /><stop offset="100%" stopColor="#0044FF" stopOpacity={0} /></linearGradient>
                <linearGradient id="g2" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#00E676" stopOpacity={0.4} /><stop offset="100%" stopColor="#00E676" stopOpacity={0} /></linearGradient>
              </defs>
              <CartesianGrid stroke={grid} strokeDasharray="2 2" vertical={false} />
              <XAxis dataKey="time" stroke="#71717a" fontSize={10} tickLine={false} />
              <YAxis stroke="#71717a" fontSize={10} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: theme === "dark" ? "#0E0E0E" : "#fff", border: `1px solid ${grid}`, borderRadius: 0, fontSize: 12 }} />
              <Area type="monotone" dataKey="events" stroke="#0044FF" fill="url(#g1)" strokeWidth={2} name={t("dash.events")} />
              <Area type="monotone" dataKey="plates" stroke="#00E676" fill="url(#g2)" strokeWidth={2} name={t("dash.plates")} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-2">
        <div className="bg-card border border-border p-4">
          <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-4">{t("dash.breakdown")}</div>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={ts.breakdown} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={45} outerRadius={80} paddingAngle={2}>
                {ts.breakdown.map((e, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: theme === "dark" ? "#0E0E0E" : "#fff", border: `1px solid ${grid}`, borderRadius: 0, fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
            {ts.breakdown.map((e, i) => (
              <span key={i} className="text-[10px] text-muted-foreground flex items-center gap-1">
                <span className="w-2 h-2" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />{e.name}
              </span>
            ))}
          </div>
        </div>

        <div className="xl:col-span-2 bg-card border border-border p-4">
          <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-3">{t("dash.recent_alerts")}</div>
          <div className="divide-y divide-border">
            {alerts.map((a, idx) => (
              <button key={a.id} onClick={() => setViewerIdx(idx)} className="w-full text-left flex items-center gap-3 py-2.5 hover:bg-secondary/50 px-1 transition" data-testid="dash-alert-row">
                <span className="w-2 h-2 rounded-full shrink-0 rec-dot" style={{ background: sev[a.severity] }} />
                <span className="text-sm flex-1 truncate">{a.message}</span>
                <span className="text-xs text-muted-foreground hidden sm:inline">{a.camera_name}</span>
                <span className="text-[10px] mono text-muted-foreground">{new Date(a.timestamp).toLocaleString()}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      {viewerIdx !== null && (
        <EventViewer items={viewerItems} index={viewerIdx} onIndex={setViewerIdx}
                      onClose={() => setViewerIdx(null)} kind="event" />
      )}
    </div>
  );
}
