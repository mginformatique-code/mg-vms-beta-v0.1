import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import {
  Puzzle, ScanLine, Brain, Activity, ScanFace, Car, Thermometer, Radar, Plane, Radio, DoorOpen, Lock,
  CheckCircle2, XCircle, AlertTriangle, PowerOff, RefreshCw, Clock,
} from "lucide-react";
import { toast } from "sonner";
import PluginManagerNG from "@/pages/PluginManagerNG";

const ICONS = {
  anpr: ScanLine, ai_detection: Brain, tracking: Activity, face_recognition: ScanFace,
  parking: Car, thermal: Thermometer, radar: Radar, drone: Plane, mqtt: Radio, access_control: DoorOpen,
};
const CAT_COLOR = { Vision: "#0044FF", Capteurs: "#FFB800", "Métier": "#00E676", "Intégration": "#A855F7" };

const STATUS_META = {
  ok:             { color: "#00E676", label: "OK",             Ic: CheckCircle2 },
  error:          { color: "#FF3333", label: "Erreur",         Ic: XCircle },
  not_configured: { color: "#FFB800", label: "Non configuré",  Ic: AlertTriangle },
  disabled:       { color: "#666",    label: "Désactivé",      Ic: PowerOff },
};

export default function Plugins() {
  const { t, can } = useApp();
  const [plugins, setPlugins] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const isAdmin = can("admin");

  const load = async () => {
    setRefreshing(true);
    try { const { data } = await api.get("/plugins"); setPlugins(data); }
    catch (e) { /* ignore */ } finally { setRefreshing(false); }
  };
  useEffect(() => { load(); const iv = setInterval(load, 20000); return () => clearInterval(iv); }, []);

  const toggle = async (p, enabled) => {
    try { await api.put(`/plugins/${p.id}`, { enabled }); toast.success(`${p.name} ${enabled ? "activé" : "désactivé"}`); load(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2"><Puzzle size={22} /> {t("plugins.title")}</h1>
        <button onClick={load} data-testid="plugins-refresh"
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-border hover:bg-secondary">
          <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} /> Rafraîchir
        </button>
      </div>
      <p className="text-sm text-muted-foreground mb-4">{t("plugins.subtitle")}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {plugins.map((p) => {
          const Icon = ICONS[p.id] || Puzzle;
          const meta = STATUS_META[p.status] || STATUS_META.not_configured;
          const StatusIc = meta.Ic;
          const h = p.health || {};
          return (
            <div key={p.id} className="bg-card border p-4 transition-colors" style={{ borderColor: meta.color }} data-testid="plugin-card">
              {/* Header */}
              <div className="flex items-start justify-between mb-2 gap-2">
                <div className="flex items-center gap-2">
                  <div className="w-9 h-9 bg-secondary flex items-center justify-center shrink-0">
                    <Icon size={18} style={{ color: CAT_COLOR[p.category] || "#0044FF" }} />
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className="font-head font-semibold">{p.name}</span>
                      <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border" style={{ borderColor: CAT_COLOR[p.category], color: CAT_COLOR[p.category] }}>{p.category}</span>
                    </div>
                    <div className="text-[10px] mono text-muted-foreground">v{p.version}{p.core ? " · cœur" : ""}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {p.core ? <Lock size={13} className="text-muted-foreground" title="Plugin cœur (non désactivable)" /> : null}
                  <Switch checked={p.enabled} onCheckedChange={(v) => toggle(p, v)} disabled={!isAdmin || p.core} data-testid={`plugin-toggle-${p.id}`} />
                </div>
              </div>

              {/* Description */}
              <div className="text-xs text-muted-foreground mb-3 leading-relaxed">{p.description}</div>

              {/* Statut global */}
              <div className="flex items-center gap-1.5 mb-2 pb-2 border-b border-border">
                <StatusIc size={14} style={{ color: meta.color }} />
                <span className="text-xs font-medium" style={{ color: meta.color }} data-testid={`plugin-status-${p.id}`}>{meta.label}</span>
                {h.warning && <span className="ml-auto text-[10px] text-[#FFB800] mono truncate max-w-[180px]" title={h.warning}>{h.warning}</span>}
              </div>

              {/* Checklist */}
              {h.checks && h.checks.length > 0 && (
                <ul className="space-y-1 mb-2" data-testid={`plugin-checks-${p.id}`}>
                  {h.checks.map((c, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-[11px]">
                      {c.ok ? <CheckCircle2 size={12} className="text-[#00E676] mt-0.5 shrink-0" /> : <XCircle size={12} className="text-[#FF3333] mt-0.5 shrink-0" />}
                      <span className="flex-1">
                        <span className="text-foreground">{c.name}</span>
                        <span className="text-muted-foreground mono ml-1 text-[10px]">{c.detail}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {/* Métriques */}
              {p.enabled && (h.events_total > 0 || h.last_event_at) && (
                <div className="mt-2 pt-2 border-t border-border grid grid-cols-3 gap-1 text-center">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">Total</div>
                    <div className="mono text-sm font-bold">{h.events_total}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground">24 h</div>
                    <div className="mono text-sm font-bold">{h.events_24h || 0}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center justify-center gap-0.5"><Clock size={9} /> Dernier</div>
                    <div className="mono text-[10px]">{h.last_event_at ? new Date(h.last_event_at).toLocaleTimeString("fr-FR") : "—"}</div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Plugin Manager NG (Preview) — bus, policy multi-ANPR, test panel */}
      <PluginManagerNG />
    </div>
  );
}
