import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Bell, Check, AlertTriangle, Info, ShieldAlert, Zap, BrainCircuit } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const SEV = {
  critical: { color: "#FF3333", icon: ShieldAlert },
  warning: { color: "#FFB800", icon: AlertTriangle },
  info: { color: "#0044FF", icon: Info },
};

function AiRulesDialog({ open, onClose }) {
  const [rules, setRules] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => { if (open) api.get("/ai/alert-rules").then((r) => setRules(r.data)).catch(() => {}); }, [open]);

  const save = async () => {
    setSaving(true);
    try { await api.put("/ai/alert-rules", rules); toast.success("Règles IA enregistrées"); onClose(); }
    catch (e) { toast.error("Erreur d'enregistrement"); } finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none border-border max-w-lg">
        <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><BrainCircuit size={18} /> Règles d'alertes IA</DialogTitle></DialogHeader>
        {!rules ? <div className="text-sm text-muted-foreground py-6">Chargement...</div> : (
          <div className="space-y-2">
            {Object.entries(rules).map(([key, r]) => (
              <div key={key} className="flex items-center justify-between border border-border px-3 py-2" data-testid={`ai-rule-${key}`}>
                <div className="min-w-0 mr-3">
                  <div className="text-sm">{r.label}</div>
                  <div className="text-[10px] uppercase tracking-wider" style={{ color: (SEV[r.severity] || SEV.info).color }}>{r.severity}</div>
                </div>
                <input type="checkbox" checked={!!r.enabled} data-testid={`ai-rule-toggle-${key}`}
                  onChange={(e) => setRules({ ...rules, [key]: { ...r, enabled: e.target.checked } })} />
              </div>
            ))}
            <div className="flex items-center gap-3 pt-1">
              <label className="text-xs text-muted-foreground">Plage nocturne :</label>
              <input type="number" min="0" max="23" value={rules.intrusion_nocturne?.night_start ?? 22}
                onChange={(e) => setRules({ ...rules, intrusion_nocturne: { ...rules.intrusion_nocturne, night_start: +e.target.value }, vol_vehicule: { ...rules.vol_vehicule, night_start: +e.target.value } })}
                className="w-16 px-2 py-1 bg-card border border-input text-sm" data-testid="ai-rule-night-start" />
              <span className="text-xs text-muted-foreground">h →</span>
              <input type="number" min="0" max="23" value={rules.intrusion_nocturne?.night_end ?? 6}
                onChange={(e) => setRules({ ...rules, intrusion_nocturne: { ...rules.intrusion_nocturne, night_end: +e.target.value }, vol_vehicule: { ...rules.vol_vehicule, night_end: +e.target.value } })}
                className="w-16 px-2 py-1 bg-card border border-input text-sm" data-testid="ai-rule-night-end" />
              <span className="text-xs text-muted-foreground">h (UTC)</span>
            </div>
            <button onClick={save} disabled={saving} data-testid="ai-rules-save-btn" className="w-full mt-2 px-4 py-2 bg-[#0044FF] text-white text-sm">{saving ? "..." : "Enregistrer"}</button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function Alerts() {
  const { t, can, alertPing } = useApp();
  const [alerts, setAlerts] = useState([]);
  const [filter, setFilter] = useState("all");
  const [rulesOpen, setRulesOpen] = useState(false);

  const load = () => {
    const q = filter === "all" ? "" : `?acknowledged=${filter === "acked"}`;
    api.get(`/alerts${q}`).then((r) => setAlerts(r.data));
  };
  useEffect(load, [filter]);
  useEffect(() => { if (alertPing) load(); }, [alertPing]);

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
          {can("technician") && <button onClick={() => setRulesOpen(true)} data-testid="ai-rules-btn" className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border hover:bg-secondary"><BrainCircuit size={14} /> Règles IA</button>}
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
          const img = a.thumbnail || a.plate_crop;
          return (
            <div key={a.id} className={`bg-card border-l-2 border border-border flex items-center gap-3 px-4 py-3 fade-up ${a.acknowledged ? "opacity-55" : ""}`} style={{ borderLeftColor: s.color }} data-testid="alert-item">
              <Icon size={18} style={{ color: s.color }} className={a.acknowledged ? "" : "rec-dot"} />
              {img && <img src={img} alt="" className="w-20 h-12 object-cover bg-black shrink-0 border border-border" data-testid="alert-thumbnail" />}
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

      <AiRulesDialog open={rulesOpen} onClose={() => setRulesOpen(false)} />
    </div>
  );
}
