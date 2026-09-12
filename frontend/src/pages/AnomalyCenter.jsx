import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import { Loader2, Sparkles, Car, Users, TrendingUp, CheckCircle2, RefreshCw, ShieldAlert, Ban, CheckSquare, Square, MapPin, ZoomIn } from "lucide-react";
import { toast } from "sonner";
import { VehicleDrawer } from "@/pages/Vehicles";
import { useApp } from "@/context/AppContext";

/**
 * v3.44 · Anomalies IA — menu dédié demandé explicitement (04/09), en
 * remplacement du simple widget "Anomalies récentes" du dashboard qui
 * n'affichait que des tags bruts (off_hours/off_days). Cadrage acté avec
 * l'utilisateur : le moteur de règles existant (habitudes réelles par
 * véhicule) reste le signal, Qwen le transforme en explication concrète ;
 * périmètre étendu aux corrélations multi-véhicules/caméras (convoi,
 * vague) dès cette v1 — voir backend/routes/vehicle_anomaly_ai.py.
 */
function kindMeta(t) {
  return {
    per_vehicle: { label: t("anomctr.kind_per_vehicle_label"), icon: Car, hint: t("anomctr.kind_per_vehicle_hint") },
    convoy: { label: t("anomctr.kind_convoy_label"), icon: Users, hint: t("anomctr.kind_convoy_hint") },
    wave: { label: t("anomctr.kind_wave_label"), icon: TrendingUp, hint: t("anomctr.kind_wave_hint") },
    plate_confusion: { label: t("anomctr.kind_plate_confusion_label"), icon: ShieldAlert, hint: t("anomctr.kind_plate_confusion_hint") },
    cross_site_impossible: { label: t("anomctr.kind_cross_site_label"), icon: Ban, hint: t("anomctr.kind_cross_site_hint") },
    long_parking: { label: t("anomctr.kind_long_parking_label"), icon: MapPin, hint: t("anomctr.kind_long_parking_hint") },
  };
}

function severityStyle(t) {
  return {
    high: { border: "#FF3333", bg: "rgba(255,51,51,0.06)", label: t("anomctr.sev_high") },
    warning: { border: "#FFB800", bg: "rgba(255,184,0,0.06)", label: t("anomctr.sev_warning") },
    info: { border: "#3B82F6", bg: "rgba(59,130,246,0.06)", label: t("anomctr.sev_info") },
  };
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR"); } catch { return iso; }
}

function ReportCard({ report, onAcknowledged, selected, onToggleSelect, onOpenPlate }) {
  const { t } = useApp();
  const KIND_META = kindMeta(t);
  const SEVERITY_STYLE = severityStyle(t);
  const meta = KIND_META[report.kind] || KIND_META.per_vehicle;
  const sev = SEVERITY_STYLE[report.severity] || SEVERITY_STYLE.info;
  const Icon = meta.icon;
  const [busy, setBusy] = useState(false);

  const ack = async () => {
    setBusy(true);
    try {
      await api.post(`/vehicles/anomaly-ai/${report.id}/acknowledge`);
      onAcknowledged(report.id);
    } catch (e) {
      toast.error(t("anomctr.err_ack_failed"));
    } finally { setBusy(false); }
  };

  return (
    <div className="border p-4 space-y-2" style={{ borderColor: sev.border, background: sev.bg }}
         data-testid={`anomaly-report-${report.id}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {!report.acknowledged && (
            <input type="checkbox" checked={!!selected} onChange={() => onToggleSelect(report.id)}
                   className="shrink-0" data-testid={`anomaly-select-${report.id}`} />
          )}
          <Icon size={14} style={{ color: sev.border }} />
          <span className="text-[10px] uppercase tracking-wider font-medium" style={{ color: sev.border }}>
            {sev.label}
          </span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground border border-border px-1.5 py-0.5">
            {meta.label}
          </span>
        </div>
        <span className="text-[10px] text-muted-foreground mono">{fmtDateTime(report.created_at)}</span>
      </div>

      <p className="text-sm">{report.message}</p>

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="flex flex-wrap gap-1 text-[10px] mono text-muted-foreground">
          {(report.plates || []).map((p) => (
            <button key={p} onClick={() => onOpenPlate(p)}
                    className="flex items-center gap-1 px-1.5 py-0.5 border border-border hover:border-[#0044FF] hover:text-[#0044FF] transition-colors"
                    title={t("anomctr.plate_tooltip")}
                    data-testid={`anomaly-plate-${p}`}>
              <ZoomIn size={10} /> {p}
            </button>
          ))}
        </div>
        {!report.acknowledged && (
          <button onClick={ack} disabled={busy}
                  className="shrink-0 flex items-center gap-1 px-2 py-1 border border-border text-[10px] uppercase tracking-wider hover:bg-secondary/60 disabled:opacity-40"
                  data-testid={`ack-btn-${report.id}`}>
            {busy ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />} {t("anomctr.acknowledge_btn")}
          </button>
        )}
      </div>
    </div>
  );
}

export default function AnomalyCenter() {
  const { t } = useApp();
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("pending");
  const [kind, setKind] = useState("");
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [aiEnabled, setAiEnabled] = useState(true);
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [openPlate, setOpenPlate] = useState(null);
  // v3.71 · Deep-link depuis une alerte "ai_anomaly" (fil d'Alertes) —
  // voir _publish_anomaly_alert (backend/routes/vehicle_anomaly_ai.py).
  const [params] = useSearchParams();
  const focusReportId = params.get("report");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { status };
      if (kind) params.kind = kind;
      const { data } = await api.get("/vehicles/anomaly-ai", { params });
      setItems(data.items || []);
      setSelected(new Set());
    } catch (e) {
      // 400 ANOMALY_AI_DISABLED n'est renvoyé que par /run, la liste répond toujours —
      // on lit juste la config LLM pour afficher le bon message si rien n'apparaît jamais.
    } finally { setLoading(false); }
  }, [status, kind]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.get("/settings/llm").then(({ data }) => setAiEnabled(!!data.anomaly_ai_enabled)).catch(() => {});
  }, []);
  useEffect(() => {
    if (!focusReportId || items.length === 0) return;
    const el = document.querySelector(`[data-testid="anomaly-report-${focusReportId}"]`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.style.outline = "2px solid #0044FF";
    el.style.outlineOffset = "2px";
    const timer = setTimeout(() => { el.style.outline = ""; el.style.outlineOffset = ""; }, 3000);
    return () => clearTimeout(timer);
  }, [focusReportId, items]);

  const pendingIds = items.filter((r) => !r.acknowledged).map((r) => r.id);
  const allSelected = pendingIds.length > 0 && pendingIds.every((id) => selected.has(id));

  const toggleSelectAll = () => setSelected(allSelected ? new Set() : new Set(pendingIds));
  const toggleSelectOne = (id) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const bulkAcknowledge = async () => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    try {
      await api.post("/vehicles/anomaly-ai/bulk-acknowledge", { ids: Array.from(selected) });
      setItems((prev) => prev.filter((r) => !selected.has(r.id)));
      setSelected(new Set());
      toast.success(`${selected.size} ${t("anomctr.reports_processed_suffix")}`);
    } catch (e) {
      toast.error(t("anomctr.err_bulk_ack_failed"));
    } finally { setBulkBusy(false); }
  };

  const runNow = async () => {
    setRunning(true);
    try {
      await api.post("/vehicles/anomaly-ai/run");
      toast.success(t("anomctr.run_started_toast"));
      setTimeout(load, 15000);
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || t("anomctr.err_run_failed"));
    } finally { setRunning(false); }
  };

  const onAcknowledged = (id) => setItems((prev) => prev.filter((r) => r.id !== id));

  return (
    <div className="p-4 max-w-4xl" data-testid="anomaly-center-page">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Sparkles size={22} className="text-[#0044FF]" /> {t("anomctr.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("anomctr.subtitle")}
          </p>
        </div>
        <button onClick={runNow} disabled={running || !aiEnabled}
                className="shrink-0 flex items-center gap-2 px-3 py-2 border border-border text-sm hover:bg-secondary disabled:opacity-40"
                data-testid="anomaly-run-now-btn">
          {running ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} {t("anomctr.run_now_btn")}
        </button>
      </div>

      {!aiEnabled && (
        <div className="border border-[#FFB800] bg-[#FFB800]/5 p-3 text-sm mb-4" data-testid="anomaly-ai-disabled-notice">
          {t("anomctr.ai_disabled_notice")}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex border border-border">
          {[["pending", t("anomctr.status_pending")], ["acknowledged", t("anomctr.status_acknowledged")], ["all", t("anomctr.status_all")]].map(([v, l]) => (
            <button key={v} onClick={() => setStatus(v)}
                    className={`px-3 py-1.5 text-xs ${status === v ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}
                    data-testid={`status-filter-${v}`}>
              {l}
            </button>
          ))}
        </div>
        <div className="flex border border-border">
          {[["", t("anomctr.kind_all")], ["per_vehicle", t("anomctr.kind_per_vehicle_label")], ["convoy", t("anomctr.kind_convoy_label")], ["wave", t("anomctr.kind_wave_label")], ["plate_confusion", t("anomctr.kind_plate_confusion_label")], ["cross_site_impossible", t("anomctr.kind_cross_site_label")], ["long_parking", t("anomctr.kind_long_parking_label")]].map(([v, l]) => (
            <button key={v || "all"} onClick={() => setKind(v)}
                    className={`px-3 py-1.5 text-xs ${kind === v ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}
                    data-testid={`kind-filter-${v || "all"}`}>
              {l}
            </button>
          ))}
        </div>
        {loading && <Loader2 size={14} className="animate-spin text-muted-foreground" />}
      </div>

      {pendingIds.length > 0 && (
        <div className="flex items-center gap-2 mb-3" data-testid="anomaly-bulk-toolbar">
          <button onClick={toggleSelectAll}
                  className="flex items-center gap-1.5 px-2 py-1 border border-border text-xs hover:bg-secondary/60"
                  data-testid="anomaly-select-all-btn">
            {allSelected ? <CheckSquare size={13} /> : <Square size={13} />}
            {allSelected ? t("anomctr.deselect_all") : t("anomctr.select_all")}
          </button>
          {selected.size > 0 && (
            <button onClick={bulkAcknowledge} disabled={bulkBusy}
                    className="flex items-center gap-1.5 px-2 py-1 border border-border text-xs hover:bg-secondary/60 disabled:opacity-40"
                    data-testid="anomaly-bulk-ack-btn">
              {bulkBusy ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
              {t("anomctr.ack_selection")} ({selected.size})
            </button>
          )}
        </div>
      )}

      <div className="space-y-2">
        {items.map((r) => (
          <ReportCard key={r.id} report={r} onAcknowledged={onAcknowledged}
                      selected={selected.has(r.id)} onToggleSelect={toggleSelectOne}
                      onOpenPlate={setOpenPlate} />
        ))}
        {items.length === 0 && !loading && (
          <div className="text-sm text-muted-foreground text-center py-8" data-testid="anomaly-empty">
            {status === "pending" ? t("anomctr.no_reports_pending") : status === "acknowledged" ? t("anomctr.no_reports_acknowledged") : t("anomctr.no_reports_all")}
          </div>
        )}
      </div>

      {/* v3.48 · Fiche véhicule complète (photo HD, loupe, validation/edition
          de plaque, blacklist/whitelist) — même composant que partout
          ailleurs dans l'app (Events/Vehicles), ouvert depuis n'importe
          quelle plaque citée dans un rapport d'anomalie, tous types confondus. */}
      <VehicleDrawer plate={openPlate} onClose={() => setOpenPlate(null)} />
    </div>
  );
}
