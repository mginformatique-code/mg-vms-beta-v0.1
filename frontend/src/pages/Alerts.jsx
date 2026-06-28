import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Bell, Check, AlertTriangle, Info, ShieldAlert, Zap } from "lucide-react";
import { toast } from "sonner";

const SEV = {
  critical: { color: "#FF3333", icon: ShieldAlert },
  warning: { color: "#FFB800", icon: AlertTriangle },
  info: { color: "#0044FF", icon: Info },
};

export default function Alerts() {
  const { t, can } = useApp();
  const [alerts, setAlerts] = useState([]);
  const [filter, setFilter] = useState("all");

  const load = () => {
    const q = filter === "all" ? "" : `?acknowledged=${filter === "acked"}`;
    api.get(`/alerts${q}`).then((r) => setAlerts(r.data));
  };
  useEffect(load, [filter]);

  const ack = async (id) => { try { await api.post(`/alerts/${id}/ack`); toast.success(t("alerts.acked")); load(); } catch (e) { toast.error("Erreur"); } };
  const trigger = async () => {
    try { await api.post("/alerts", { message: "Intrusion détectée — zone périmètre", severity: "critical" }); toast.success(t("notif.trigger_sent")); load(); }
    catch (e) { toast.error("Erreur"); }
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2"><Bell size={22} /> {t("alerts.title")}</h1>
        <div className="flex items-center gap-2">
          {can("technician") && <button onClick={trigger} data-testid="trigger-alert-btn" className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10"><Zap size={14} /> {t("notif.trigger")}</button>}
          <div className="flex border border-border">
            {[["all", t("common.all")], ["unacked", t("alerts.unacked")], ["acked", t("alerts.acked")]].map(([k, lbl]) => (
              <button key={k} onClick={() => setFilter(k)} data-testid={`alert-filter-${k}`}
                className={`px-3 py-1.5 text-xs uppercase tracking-wider ${filter === k ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}>{lbl}</button>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-1.5">
        {alerts.map((a) => {
          const s = SEV[a.severity] || SEV.info; const Icon = s.icon;
          return (
            <div key={a.id} className={`bg-card border-l-2 border border-border flex items-center gap-3 px-4 py-3 fade-up ${a.acknowledged ? "opacity-55" : ""}`} style={{ borderLeftColor: s.color }} data-testid="alert-item">
              <Icon size={18} style={{ color: s.color }} className={a.acknowledged ? "" : "rec-dot"} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{a.message}</div>
                <div className="text-xs text-muted-foreground mono">{a.camera_name} · {a.site_name} · {new Date(a.timestamp).toLocaleString()}</div>
              </div>
              <span className="text-[9px] uppercase tracking-wider px-2 py-0.5 border" style={{ borderColor: s.color, color: s.color }}>{a.severity}</span>
              {!a.acknowledged && can("client") && (
                <button onClick={() => ack(a.id)} data-testid="alert-ack-btn" className="flex items-center gap-1 px-3 py-1.5 text-xs border border-border hover:bg-secondary"><Check size={13} /> {t("alerts.ack")}</button>
              )}
            </div>
          );
        })}
        {alerts.length === 0 && <div className="text-center text-muted-foreground py-12 text-sm">—</div>}
      </div>
    </div>
  );
}
