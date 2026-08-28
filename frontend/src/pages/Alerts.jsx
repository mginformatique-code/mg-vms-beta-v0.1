import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Bell, Check, AlertTriangle, Info, ShieldAlert, BrainCircuit, Eye } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import EventViewer from "@/components/EventViewer";

const SEV = {
  critical: { color: "#FF3333", icon: ShieldAlert },
  warning: { color: "#FFB800", icon: AlertTriangle },
  info: { color: "#0044FF", icon: Info },
};

function AiRulesDialog({ open, onClose }) {
  const { t } = useApp();
  const [rules, setRules] = useState(null);
  const [arming, setArming] = useState(null);
  const [saving, setSaving] = useState(false);
  const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

  useEffect(() => {
    if (open) {
      api.get("/ai/alert-rules").then((r) => setRules(r.data)).catch(() => {});
      api.get("/ai/arming").then((r) => setArming(r.data)).catch(() => {});
    }
  }, [open]);

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/ai/alert-rules", rules);
      await api.put("/ai/arming", arming);
      toast.success("Règles IA et armement enregistrés");
      onClose();
    }
    catch (e) { toast.error("Erreur d'enregistrement"); } finally { setSaving(false); }
  };

  const toggleDay = (d) => {
    const days = arming.days.includes(d) ? arming.days.filter((x) => x !== d) : [...arming.days, d];
    setArming({ ...arming, days });
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="rounded-none border-border max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><BrainCircuit size={18} /> {t("alr.ai_rules")}</DialogTitle></DialogHeader>
        {!rules || !arming ? <div className="text-sm text-muted-foreground py-6">Chargement...</div> : (
          <div className="space-y-2">
            <div className="border border-border p-3 space-y-2" data-testid="arming-section">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{t("alr.arming")}</span>
                <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 border ${arming.armed_now ? "border-[#00E676] text-[#00E676]" : "border-[#FF3333] text-[#FF3333]"}`} data-testid="armed-status">
                  {arming.armed_now ? "Armé" : "Désarmé"}
                </span>
              </div>
              <select value={arming.mode} data-testid="arming-mode-select"
                onChange={(e) => setArming({ ...arming, mode: e.target.value })}
                className="w-full px-2 py-1.5 bg-card border border-input text-sm">
                <option value="always">{t("alr.always_armed")}</option>
                <option value="schedule">Selon planning</option>
                <option value="off">{t("alr.disarmed")}</option>
              </select>
              {arming.mode === "schedule" && (
                <>
                  <div className="flex gap-1 flex-wrap">
                    {DAYS.map((lbl, d) => (
                      <button key={d} onClick={() => toggleDay(d)} data-testid={`arming-day-${d}`}
                        className={`px-2 py-1 text-xs border ${arming.days.includes(d) ? "bg-[#0044FF] text-white border-[#0044FF]" : "border-border text-muted-foreground"}`}>{lbl}</button>
                    ))}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">De</span>
                    <input type="number" min="0" max="23" value={arming.start_h} data-testid="arming-start"
                      onChange={(e) => setArming({ ...arming, start_h: +e.target.value })} className="w-16 px-2 py-1 bg-card border border-input text-sm" />
                    <span className="text-xs text-muted-foreground">{t("alr.hours_to")}</span>
                    <input type="number" min="0" max="24" value={arming.end_h} data-testid="arming-end"
                      onChange={(e) => setArming({ ...arming, end_h: +e.target.value })} className="w-16 px-2 py-1 bg-card border border-input text-sm" />
                    <span className="text-xs text-muted-foreground">h (UTC)</span>
                  </div>
                </>
              )}
            </div>
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
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [filter, setFilter] = useState("all");
  const [rulesOpen, setRulesOpen] = useState(false);
  // v3.1.8 · Suivi par id, pas par index — `alertPing` (websocket temps réel,
  // voir AppContext) déclenche `load()` sur CHAQUE nouvelle alerte, qui
  // remplace entièrement `alerts` : un index de position pointerait alors
  // sur une alerte différente sans que l'utilisateur n'ait rien touché.
  const [viewerId, setViewerId] = useState(null);

  // Adapte les alertes pour EventViewer (mêmes clés que event/plate)
  // Hybridation ANPR : préserve `plate_crop` + `vehicle_crop` pour l'affichage
  // en insets à côté de la scène HD (thumbnail).
  const viewerItems = alerts.map((a) => ({
    id: a.id, thumbnail: a.thumbnail || a.vehicle_crop || a.plate_crop,
    plate_crop: a.plate_crop, vehicle_crop: a.vehicle_crop,
    camera_id: a.camera_id, camera_name: a.camera_name, site_name: a.site_name,
    timestamp: a.timestamp, plugin: a.plugin || (a.scenario ? `IA · ${a.scenario}` : "Alerte"),
    type: a.type || a.scenario || "alert", label: a.message,
    plate: a.plate, list_status: a.list_status,
  }));

  const viewerIdx = viewerId !== null ? viewerItems.findIndex((x) => x.id === viewerId) : -1;

  // v3.19 · Limite d'affichage — 9 377 alertes en base, tout remontait
  // d'un coup sans pagination (limit=100 par défaut côté API, mais aucun
  // bouton pour aller au-delà, et 100 lignes rendues à chaque nouvelle
  // alerte via alertPing). Même principe que Événements/Véhicules/
  // Enregistrements : petite page + "Charger plus".
  const PAGE_SIZE = 30;
  const buildQuery = (extra) => {
    const params = new URLSearchParams({ limit: PAGE_SIZE, ...extra });
    if (filter !== "all") params.set("acknowledged", filter === "acked");
    return params.toString();
  };
  const load = () => {
    api.get(`/alerts?${buildQuery({ offset: 0 })}`).then((r) => {
      setAlerts(r.data);
      setTotal(parseInt(r.headers["x-total-count"] || r.data.length, 10));
    });
  };
  const loadMore = async () => {
    setLoadingMore(true);
    try {
      const r = await api.get(`/alerts?${buildQuery({ offset: alerts.length })}`);
      setAlerts((prev) => [...prev, ...r.data]);
    } finally { setLoadingMore(false); }
  };
  useEffect(load, [filter]);
  useEffect(() => { if (alertPing) load(); }, [alertPing]);

  const ack = async (id) => { try { await api.post(`/alerts/${id}/ack`); toast.success(t("alerts.acked")); load(); } catch (e) { toast.error("Erreur"); } };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2"><Bell size={22} /> {t("alerts.title")}</h1>
        <div className="flex items-center gap-2">
          {can("technician") && <button onClick={() => setRulesOpen(true)} data-testid="ai-rules-btn" className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border hover:bg-secondary"><BrainCircuit size={14} /> {t("alr.ai_rules_short")}</button>}
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
              {img && (
                <button onClick={() => setViewerId(a.id)} className="w-20 h-12 shrink-0 border border-border overflow-hidden hover:ring-2 hover:ring-[#0044FF] transition" data-testid="alert-thumb-btn" title="Voir en HD">
                  <img src={img} alt="" className="w-full h-full object-cover bg-black" data-testid="alert-thumbnail" />
                </button>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{a.message}</div>
                <div className="text-xs text-muted-foreground mono">{a.camera_name} · {a.site_name} · {new Date(a.timestamp).toLocaleString()}</div>
              </div>
              <span className="text-[9px] uppercase tracking-wider px-2 py-0.5 border" style={{ borderColor: s.color, color: s.color }}>{a.severity}</span>
              <button onClick={() => setViewerId(a.id)} className="flex items-center gap-1 px-2 py-1.5 text-xs border border-border hover:bg-secondary" data-testid="alert-view-btn" title="Ouvrir la visionneuse"><Eye size={13} /></button>
              {!a.acknowledged && can("client") && (
                <button onClick={() => ack(a.id)} data-testid="alert-ack-btn" className="flex items-center gap-1 px-3 py-1.5 text-xs border border-border hover:bg-secondary"><Check size={13} /> {t("alerts.ack")}</button>
              )}
            </div>
          );
        })}
        {alerts.length === 0 && <div className="text-center text-muted-foreground py-12 text-sm">—</div>}
      </div>

      {alerts.length < total && alerts.length > 0 && (
        <div className="flex justify-center pt-3">
          <button onClick={loadMore} disabled={loadingMore} data-testid="alerts-load-more"
                  className="px-4 py-2 text-xs uppercase tracking-wider border border-border hover:bg-secondary disabled:opacity-40">
            {loadingMore ? "Chargement…" : `Charger plus (${alerts.length} / ${total})`}
          </button>
        </div>
      )}

      <AiRulesDialog open={rulesOpen} onClose={() => setRulesOpen(false)} />
      {viewerIdx >= 0 && (
        <EventViewer items={viewerItems} index={viewerIdx} onIndex={(i) => setViewerId(viewerItems[i]?.id ?? null)}
                      onClose={() => setViewerId(null)} kind="event" />
      )}
    </div>
  );
}
