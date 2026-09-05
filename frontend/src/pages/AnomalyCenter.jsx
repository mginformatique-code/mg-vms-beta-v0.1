import React, { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { Loader2, Sparkles, Car, Users, TrendingUp, CheckCircle2, RefreshCw, ShieldAlert, Ban } from "lucide-react";
import { toast } from "sonner";

/**
 * v3.44 · Anomalies IA — menu dédié demandé explicitement (04/09), en
 * remplacement du simple widget "Anomalies récentes" du dashboard qui
 * n'affichait que des tags bruts (off_hours/off_days). Cadrage acté avec
 * l'utilisateur : le moteur de règles existant (habitudes réelles par
 * véhicule) reste le signal, Qwen le transforme en explication concrète ;
 * périmètre étendu aux corrélations multi-véhicules/caméras (convoi,
 * vague) dès cette v1 — voir backend/routes/vehicle_anomaly_ai.py.
 */
const KIND_META = {
  per_vehicle: { label: "Véhicule", icon: Car, hint: "Écart aux habitudes réelles de ce véhicule" },
  convoy: { label: "Convoi", icon: Users, hint: "Deux véhicules vus ensemble, de façon répétée" },
  wave: { label: "Vague", icon: TrendingUp, hint: "Pic de véhicules distincts inhabituel sur une caméra" },
  plate_confusion: { label: "Plaque suspecte", icon: ShieldAlert, hint: "Plusieurs marques réelles différentes détectées sous la même plaque — probable confusion ANPR" },
  cross_site_impossible: { label: "Trajet impossible", icon: Ban, hint: "Même plaque vue sur 2 sites distincts en un temps trop court pour être plausible" },
};

const SEVERITY_STYLE = {
  high: { border: "#FF3333", bg: "rgba(255,51,51,0.06)", label: "CRITIQUE" },
  warning: { border: "#FFB800", bg: "rgba(255,184,0,0.06)", label: "ATTENTION" },
  info: { border: "#3B82F6", bg: "rgba(59,130,246,0.06)", label: "INFO" },
};

function fmtDateTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR"); } catch { return iso; }
}

function ReportCard({ report, onAcknowledged }) {
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
      toast.error("Échec du traitement");
    } finally { setBusy(false); }
  };

  return (
    <div className="border p-4 space-y-2" style={{ borderColor: sev.border, background: sev.bg }}
         data-testid={`anomaly-report-${report.id}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
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
            <span key={p} className="px-1.5 py-0.5 border border-border">{p}</span>
          ))}
        </div>
        {!report.acknowledged && (
          <button onClick={ack} disabled={busy}
                  className="shrink-0 flex items-center gap-1 px-2 py-1 border border-border text-[10px] uppercase tracking-wider hover:bg-secondary/60 disabled:opacity-40"
                  data-testid={`ack-btn-${report.id}`}>
            {busy ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />} Traiter
          </button>
        )}
      </div>
    </div>
  );
}

export default function AnomalyCenter() {
  const [items, setItems] = useState([]);
  const [status, setStatus] = useState("pending");
  const [kind, setKind] = useState("");
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [aiEnabled, setAiEnabled] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { status };
      if (kind) params.kind = kind;
      const { data } = await api.get("/vehicles/anomaly-ai", { params });
      setItems(data.items || []);
    } catch (e) {
      // 400 ANOMALY_AI_DISABLED n'est renvoyé que par /run, la liste répond toujours —
      // on lit juste la config LLM pour afficher le bon message si rien n'apparaît jamais.
    } finally { setLoading(false); }
  }, [status, kind]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.get("/settings/llm").then(({ data }) => setAiEnabled(!!data.anomaly_ai_enabled)).catch(() => {});
  }, []);

  const runNow = async () => {
    setRunning(true);
    try {
      await api.post("/vehicles/anomaly-ai/run");
      toast.success("Recherche lancée en arrière-plan — les nouveaux rapports apparaîtront progressivement (jusqu'à quelques minutes).");
      setTimeout(load, 15000);
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || "Échec du lancement");
    } finally { setRunning(false); }
  };

  const onAcknowledged = (id) => setItems((prev) => prev.filter((r) => r.id !== id));

  return (
    <div className="p-4 max-w-4xl" data-testid="anomaly-center-page">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Sparkles size={22} className="text-[#0044FF]" /> Anomalies IA
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Écarts aux habitudes réelles d'un véhicule, convois répétés, pics de trafic inhabituels — expliqués en langage clair par IA, pas de simples tags.
          </p>
        </div>
        <button onClick={runNow} disabled={running || !aiEnabled}
                className="shrink-0 flex items-center gap-2 px-3 py-2 border border-border text-sm hover:bg-secondary disabled:opacity-40"
                data-testid="anomaly-run-now-btn">
          {running ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Rechercher maintenant
        </button>
      </div>

      {!aiEnabled && (
        <div className="border border-[#FFB800] bg-[#FFB800]/5 p-3 text-sm mb-4" data-testid="anomaly-ai-disabled-notice">
          IA anomalies désactivée — active-la dans Administration → LLM (MG-IA) pour générer de nouveaux rapports. Les rapports déjà générés restent visibles ci-dessous.
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex border border-border">
          {[["pending", "En attente"], ["acknowledged", "Traitées"], ["all", "Toutes"]].map(([v, l]) => (
            <button key={v} onClick={() => setStatus(v)}
                    className={`px-3 py-1.5 text-xs ${status === v ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}
                    data-testid={`status-filter-${v}`}>
              {l}
            </button>
          ))}
        </div>
        <div className="flex border border-border">
          {[["", "Tout type"], ["per_vehicle", "Véhicule"], ["convoy", "Convoi"], ["wave", "Vague"], ["plate_confusion", "Plaque suspecte"], ["cross_site_impossible", "Trajet impossible"]].map(([v, l]) => (
            <button key={v || "all"} onClick={() => setKind(v)}
                    className={`px-3 py-1.5 text-xs ${kind === v ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}
                    data-testid={`kind-filter-${v || "all"}`}>
              {l}
            </button>
          ))}
        </div>
        {loading && <Loader2 size={14} className="animate-spin text-muted-foreground" />}
      </div>

      <div className="space-y-2">
        {items.map((r) => <ReportCard key={r.id} report={r} onAcknowledged={onAcknowledged} />)}
        {items.length === 0 && !loading && (
          <div className="text-sm text-muted-foreground text-center py-8" data-testid="anomaly-empty">
            Aucun rapport {status === "pending" ? "en attente" : status === "acknowledged" ? "traité" : ""}.
          </div>
        )}
      </div>
    </div>
  );
}
