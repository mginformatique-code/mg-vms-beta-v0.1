import React, { useCallback, useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, Brain, ChevronDown, ChevronRight, CheckCircle2, XCircle } from "lucide-react";

/**
 * v3.27 · Logs LLM — remplace l'ancien menu "Log ANPR" (un simple tableau
 * des plaques les plus lues, sans aucun rapport avec l'IA — demande
 * explicite de l'utilisateur : "cette partie là n'est pas boosté par IA").
 * Journal détaillé de chaque appel réseau vers Qwen (couleur/marque/
 * anomalies/dédoublonnage/réglage ANPR/recherche IA), succès ou échec,
 * avec latence — pensé pour le debug après plusieurs pannes qui n'avaient
 * laissé aucune trace exploitable (toggle désactivé, 404 muet).
 */
function fmtDateTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR"); } catch { return iso; }
}

const SOURCE_LABELS = {
  color_ai: "llmlog.source_color_ai",
  make_ai: "llmlog.source_make_ai",
  dedup: "llmlog.source_dedup",
  anpr_tuning: "llmlog.source_anpr_tuning",
  smart_search: "llmlog.source_smart_search",
};
function sourceLabel(source, t) {
  if (SOURCE_LABELS[source]) return t(SOURCE_LABELS[source]);
  if (source?.startsWith("anomaly_ai:")) return `${t("llmlog.source_anomalies")} (${source.split(":")[1]})`;
  return source || "—";
}

function LogRow({ log }) {
  const { t } = useApp();
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="border-t border-border/40 cursor-pointer hover:bg-secondary/30" onClick={() => setOpen((v) => !v)}
          data-testid="llm-log-row">
        <td className="py-2 pr-2">{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</td>
        <td className="py-2 pr-4 font-mono text-xs whitespace-nowrap">{fmtDateTime(log.ts)}</td>
        <td className="py-2 pr-4">{sourceLabel(log.source, t)}</td>
        <td className="py-2 pr-4 font-mono text-xs">{log.model || "—"}</td>
        <td className="py-2 pr-4">
          {log.ok ? (
            <span className="flex items-center gap-1 text-[11px] text-emerald-500"><CheckCircle2 size={12} /> {log.status_code ?? "OK"}</span>
          ) : (
            <span className="flex items-center gap-1 text-[11px] text-[#FF3333]"><XCircle size={12} /> {log.status_code ?? t("llmlog.error_word")}</span>
          )}
        </td>
        <td className="py-2 font-mono text-xs text-muted-foreground">{log.latency_ms != null ? `${log.latency_ms} ms` : "—"}</td>
      </tr>
      {open && (
        <tr className="border-t border-border/20 bg-secondary/10" data-testid="llm-log-detail">
          <td colSpan={6} className="py-3 px-4 space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">URL</div>
            <div className="font-mono text-xs break-all">{log.url}</div>
            {log.error && (
              <>
                <div className="text-[10px] uppercase tracking-wider text-[#FF3333] mt-2">{t("llmlog.error_word")}</div>
                <pre className="text-xs font-mono bg-black/30 p-2 rounded overflow-x-auto whitespace-pre-wrap">{log.error}</pre>
              </>
            )}
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mt-2">{t("llmlog.request_label")}</div>
            <pre className="text-xs font-mono bg-black/30 p-2 rounded overflow-x-auto whitespace-pre-wrap max-h-64">
              {typeof log.request === "string" ? log.request : JSON.stringify(log.request, null, 2)}
            </pre>
            {log.response && (
              <>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mt-2">{t("llmlog.response_label")}</div>
                <pre className="text-xs font-mono bg-black/30 p-2 rounded overflow-x-auto whitespace-pre-wrap max-h-64">
                  {typeof log.response === "string" ? log.response : JSON.stringify(log.response, null, 2)}
                </pre>
              </>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export default function LlmLogs() {
  const { t } = useApp();
  const [items, setItems] = useState([]);
  const [sources, setSources] = useState([]);
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 200 };
      if (source) params.source = source;
      if (status) params.status = status;
      const r = await api.get("/llm-logs", { params }).catch(() => ({ data: { items: [] } }));
      setItems(r.data?.items || []);
    } finally {
      setLoading(false);
    }
  }, [source, status]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.get("/llm-logs/sources").then((r) => setSources(r.data?.sources || [])).catch(() => {});
  }, []);

  return (
    <div className="p-4 max-w-5xl" data-testid="llm-logs-page">
      <div className="mb-5">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Brain size={22} /> {t("nav.llm_logs")}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {t("llmlog.subtitle")}
        </p>
      </div>

      <Card className="p-4 space-y-3">
        <div className="flex flex-wrap justify-between items-center gap-2">
          <div className="flex flex-wrap gap-2">
            <select value={source} onChange={(e) => setSource(e.target.value)}
                    className="px-2 py-1.5 bg-card border border-input outline-none text-xs" data-testid="llm-log-source-filter">
              <option value="">{t("llmlog.filter_all_sources")}</option>
              {sources.map((s) => <option key={s} value={s}>{sourceLabel(s, t)}</option>)}
            </select>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
                    className="px-2 py-1.5 bg-card border border-input outline-none text-xs" data-testid="llm-log-status-filter">
              <option value="">{t("llmlog.filter_all_statuses")}</option>
              <option value="ok">{t("llmlog.status_success")}</option>
              <option value="error">{t("llmlog.status_errors")}</option>
            </select>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-sm text-muted-foreground">{items.length} {t("llmlog.calls_suffix")}</div>
            <Button size="sm" variant="ghost" onClick={load} disabled={loading}>
              <RefreshCw className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`} />{t("llmlog.refresh_btn")}
            </Button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="llm-logs-table">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="pb-2 pr-2 w-4"></th>
                <th className="pb-2 pr-4">{t("llmlog.th_timestamp")}</th>
                <th className="pb-2 pr-4">{t("llmlog.th_source")}</th>
                <th className="pb-2 pr-4">{t("llmlog.th_model")}</th>
                <th className="pb-2 pr-4">{t("llmlog.th_status")}</th>
                <th className="pb-2">{t("llmlog.th_latency")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((log, i) => <LogRow key={i} log={log} />)}
              {items.length === 0 && !loading && (
                <tr><td colSpan={6} className="py-6 text-center text-muted-foreground" data-testid="llm-logs-empty">
                  {t("llmlog.empty_state")}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
