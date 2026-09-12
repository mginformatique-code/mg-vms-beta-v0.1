import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import { Brain, Save, Loader2, CheckCircle2, RefreshCw, Eye, Car } from "lucide-react";
import { toast } from "sonner";

/**
 * LlmSettings — Configuration LLM (recherche IA avancée), menu admin.
 *
 * v3.19 · Remplace la clé cloud EMERGENT_LLM_KEY par une instance Qwen
 * auto-hébergée, exposée en WAN via un domaine dédié — pensé pour un
 * déploiement client simple : une URL, une clé API, un switch, pas
 * d'édition manuelle de fichier .env par site. Voir backend/routes/llm_settings.py.
 */
const empty = {
  enabled: false, base_url: "https://ia.mginformatique.com", model: "qwen2.5", api_key: "", has_api_key: false,
  dedup_enabled: false, anpr_tuning_enabled: false,
  dedup_auto_approve_enabled: false, dedup_auto_approve_interval_min: 60,
  anomaly_ai_enabled: false,
  vision_model: "qwen2.5vl:7b", color_ai_enabled: false, make_ai_enabled: false,
  color_ai_auto_sync_enabled: false, color_ai_auto_sync_time: "03:00",
  make_ai_auto_sync_enabled: false, make_ai_auto_sync_time: "03:30",
  identity_merge_ai_enabled: false,
  identity_merge_ai_auto_approve_enabled: false, identity_merge_ai_auto_approve_interval_min: 60,
};

const Inp = (p) => <input {...p} className="w-full px-3 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]" />;
const Sel = (p) => <select {...p} className="px-2 py-1.5 bg-card border border-input outline-none text-xs focus:border-[#0044FF]" />;
const Lbl = ({ children }) => <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{children}</label>;

const getAutoApproveIntervals = (t) => [
  { value: 30, label: t("llmset.interval_30min") },
  { value: 60, label: t("llmset.interval_1h") },
  { value: 120, label: t("llmset.interval_2h") },
  { value: 360, label: t("llmset.interval_6h") },
  { value: 1440, label: t("llmset.interval_24h") },
];

function fmtDateTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR"); } catch { return iso; }
}

export default function LlmSettings() {
  const { t } = useApp();
  const AUTO_APPROVE_INTERVALS = getAutoApproveIntervals(t);
  const [cfg, setCfg] = useState(empty);
  const [saving, setSaving] = useState(false);
  const [autoStatus, setAutoStatus] = useState(null);
  const [identityMergeAutoStatus, setIdentityMergeAutoStatus] = useState(null);
  const [colorStatus, setColorStatus] = useState(null);
  const [colorRunning, setColorRunning] = useState(false);
  const [makeStatus, setMakeStatus] = useState(null);
  const [makeRunning, setMakeRunning] = useState(false);

  const loadAutoStatus = () => {
    api.get("/vehicles/dedup/auto-approve/status").then((r) => setAutoStatus(r.data)).catch(() => {});
  };
  const loadIdentityMergeAutoStatus = () => {
    api.get("/vehicles/identities/merge-ai/auto-approve/status").then((r) => setIdentityMergeAutoStatus(r.data)).catch(() => {});
  };
  const loadColorStatus = () => {
    api.get("/vehicles/color-ai/status").then((r) => setColorStatus(r.data)).catch(() => {});
  };
  const loadMakeStatus = () => {
    api.get("/vehicles/make-ai/status").then((r) => setMakeStatus(r.data)).catch(() => {});
  };

  useEffect(() => {
    api.get("/settings/llm").then((r) => setCfg({ ...empty, ...r.data })).catch(() => {});
    loadAutoStatus();
    loadColorStatus();
    loadMakeStatus();
    loadIdentityMergeAutoStatus();
    const iv = setInterval(() => { loadAutoStatus(); loadColorStatus(); loadMakeStatus(); loadIdentityMergeAutoStatus(); }, 30000);
    return () => clearInterval(iv);
  }, []);

  const runColorNow = async () => {
    setColorRunning(true);
    try {
      await api.post("/vehicles/color-ai/run");
      toast.success(t("llmset.toast_color_launched"));
      setTimeout(loadColorStatus, 15000);
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || t("llmset.err_launch_failed"));
    } finally { setColorRunning(false); }
  };

  const runMakeNow = async () => {
    setMakeRunning(true);
    try {
      await api.post("/vehicles/make-ai/run");
      toast.success(t("llmset.toast_make_launched"));
      setTimeout(loadMakeStatus, 15000);
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || t("llmset.err_launch_failed"));
    } finally { setMakeRunning(false); }
  };

  const upd = (k, v) => setCfg((c) => ({ ...c, [k]: v }));

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/settings/llm", {
        enabled: cfg.enabled, base_url: cfg.base_url, model: cfg.model, api_key: cfg.api_key,
        dedup_enabled: cfg.dedup_enabled, anpr_tuning_enabled: cfg.anpr_tuning_enabled,
        dedup_auto_approve_enabled: cfg.dedup_auto_approve_enabled,
        dedup_auto_approve_interval_min: cfg.dedup_auto_approve_interval_min,
        anomaly_ai_enabled: cfg.anomaly_ai_enabled,
        vision_model: cfg.vision_model, color_ai_enabled: cfg.color_ai_enabled,
        make_ai_enabled: cfg.make_ai_enabled,
        color_ai_auto_sync_enabled: cfg.color_ai_auto_sync_enabled,
        color_ai_auto_sync_time: cfg.color_ai_auto_sync_time,
        make_ai_auto_sync_enabled: cfg.make_ai_auto_sync_enabled,
        make_ai_auto_sync_time: cfg.make_ai_auto_sync_time,
        identity_merge_ai_enabled: cfg.identity_merge_ai_enabled,
        identity_merge_ai_auto_approve_enabled: cfg.identity_merge_ai_auto_approve_enabled,
        identity_merge_ai_auto_approve_interval_min: cfg.identity_merge_ai_auto_approve_interval_min,
      });
      setCfg({ ...empty, ...data });
      toast.success(t("llmset.toast_saved"));
      loadAutoStatus();
      loadIdentityMergeAutoStatus();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  return (
    <div className="p-4 max-w-2xl">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-1 flex items-center gap-2">
        <Brain size={22} className="text-[#0044FF]" /> LLM (MG-IA)
      </h1>
      <p className="text-sm text-muted-foreground mb-4">
        {t("llmset.intro")}
      </p>

      <div className="bg-card border border-border p-5" data-testid="llm-settings-panel">
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Brain size={18} className="text-[#0044FF]" />
            <span className="font-head font-semibold">{t("llmset.search_ai_title")}</span>
            {cfg.enabled && (
              <span className="text-[9px] uppercase tracking-wider mg-online flex items-center gap-1">
                <CheckCircle2 size={12} /> {t("common.active")}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{cfg.enabled ? t("common.active") : t("llmset.disabled")}</span>
            <Switch checked={cfg.enabled} onCheckedChange={(v) => upd("enabled", v)} data-testid="llm-enabled-toggle" />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <Lbl>{t("llmset.lbl_base_url")}</Lbl>
            <Inp value={cfg.base_url} onChange={(e) => upd("base_url", e.target.value)}
                 placeholder="https://ia.mginformatique.com" data-testid="llm-base-url" />
          </div>
          <div>
            <Lbl>{t("llmset.lbl_model")}</Lbl>
            <Inp value={cfg.model} onChange={(e) => upd("model", e.target.value)}
                 placeholder="qwen2.5" data-testid="llm-model" />
          </div>
          <div>
            <Lbl>{t("llmset.lbl_api_key")}</Lbl>
            <Inp type="password" value={cfg.api_key} onChange={(e) => upd("api_key", e.target.value)}
                 placeholder={cfg.has_api_key ? t("llmset.ph_api_key_saved") : t("llmset.ph_api_key_hint")}
                 data-testid="llm-api-key" />
          </div>
          <div className="col-span-2">
            <Lbl>{t("llmset.lbl_vision_model")}</Lbl>
            <Inp value={cfg.vision_model} onChange={(e) => upd("vision_model", e.target.value)}
                 placeholder="qwen2.5vl:7b" data-testid="llm-vision-model" />
            <div className="text-[11px] text-muted-foreground mt-1">
              {t("llmset.vision_model_hint")}
            </div>
          </div>
        </div>

        <p className="text-[11px] text-muted-foreground mt-3">
          {t("llmset.api_key_howto")}
        </p>
      </div>

      <div className="bg-card border border-border p-5 mt-4" data-testid="llm-features-panel">
        <div className="font-head font-semibold mb-3">{t("llmset.features_title")}</div>

        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-sm">{t("llmset.dedup_title")}</div>
            <div className="text-[11px] text-muted-foreground">{t("llmset.dedup_desc")}</div>
          </div>
          <Switch checked={cfg.dedup_enabled} onCheckedChange={(v) => upd("dedup_enabled", v)} data-testid="llm-dedup-toggle" />
        </div>

        {cfg.dedup_enabled && (
          <div className="py-2.5 border-b border-border pl-3 border-l-2 border-l-[#0044FF]/30 space-y-2" data-testid="llm-dedup-auto-approve-block">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm">{t("llmset.dedup_auto_approve_title")}</div>
                <div className="text-[11px] text-muted-foreground">{t("llmset.dedup_auto_approve_desc")}</div>
              </div>
              <Switch checked={cfg.dedup_auto_approve_enabled} onCheckedChange={(v) => upd("dedup_auto_approve_enabled", v)} data-testid="llm-dedup-auto-approve-toggle" />
            </div>
            {cfg.dedup_auto_approve_enabled && (
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">{t("llmset.lbl_every")}</span>
                <Sel value={cfg.dedup_auto_approve_interval_min}
                     onChange={(e) => upd("dedup_auto_approve_interval_min", Number(e.target.value))}
                     data-testid="llm-dedup-auto-approve-interval">
                  {AUTO_APPROVE_INTERVALS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </Sel>
              </div>
            )}
            {autoStatus?.enabled && (
              <div className="text-[10px] text-muted-foreground mono" data-testid="llm-dedup-auto-approve-status">
                {autoStatus.pending_count} {t("llmset.lbl_pending")} · {t("llmset.lbl_last_pass")} {fmtDateTime(autoStatus.last_run_at)}
                {autoStatus.last_approved_count != null && ` (${autoStatus.last_approved_count} ${t(autoStatus.last_approved_count > 1 ? "llmset.lbl_approved_many" : "llmset.lbl_approved_one")})`}
                {autoStatus.next_run_at && ` · ${t("llmset.lbl_next")} ${fmtDateTime(autoStatus.next_run_at)}`}
              </div>
            )}
          </div>
        )}

        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-sm">{t("llmset.identity_merge_title")}</div>
            <div className="text-[11px] text-muted-foreground">{t("llmset.identity_merge_desc")}</div>
          </div>
          <Switch checked={cfg.identity_merge_ai_enabled} onCheckedChange={(v) => upd("identity_merge_ai_enabled", v)} data-testid="llm-identity-merge-ai-toggle" />
        </div>

        {cfg.identity_merge_ai_enabled && (
          <div className="py-2.5 border-b border-border pl-3 border-l-2 border-l-[#0044FF]/30 space-y-2" data-testid="llm-identity-merge-ai-auto-approve-block">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm">{t("llmset.identity_auto_approve_title")}</div>
                <div className="text-[11px] text-muted-foreground">{t("llmset.identity_auto_approve_desc")}</div>
              </div>
              <Switch checked={cfg.identity_merge_ai_auto_approve_enabled} onCheckedChange={(v) => upd("identity_merge_ai_auto_approve_enabled", v)} data-testid="llm-identity-merge-ai-auto-approve-toggle" />
            </div>
            {cfg.identity_merge_ai_auto_approve_enabled && (
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">{t("llmset.lbl_every")}</span>
                <Sel value={cfg.identity_merge_ai_auto_approve_interval_min}
                     onChange={(e) => upd("identity_merge_ai_auto_approve_interval_min", Number(e.target.value))}
                     data-testid="llm-identity-merge-ai-auto-approve-interval">
                  {AUTO_APPROVE_INTERVALS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </Sel>
              </div>
            )}
            {identityMergeAutoStatus?.enabled && (
              <div className="text-[10px] text-muted-foreground mono" data-testid="llm-identity-merge-ai-auto-approve-status">
                {identityMergeAutoStatus.pending_count} {t("llmset.lbl_pending")} · {t("llmset.lbl_last_pass")} {fmtDateTime(identityMergeAutoStatus.last_run_at)}
                {identityMergeAutoStatus.last_approved_count != null && ` (${identityMergeAutoStatus.last_approved_count} ${t(identityMergeAutoStatus.last_approved_count > 1 ? "llmset.lbl_merged_many" : "llmset.lbl_merged_one")})`}
                {identityMergeAutoStatus.next_run_at && ` · ${t("llmset.lbl_next")} ${fmtDateTime(identityMergeAutoStatus.next_run_at)}`}
              </div>
            )}
          </div>
        )}

        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-sm">{t("llmset.anpr_tuning_title")}</div>
            <div className="text-[11px] text-muted-foreground">{t("llmset.anpr_tuning_desc")}</div>
          </div>
          <Switch checked={cfg.anpr_tuning_enabled} onCheckedChange={(v) => upd("anpr_tuning_enabled", v)} data-testid="llm-anpr-tuning-toggle" />
        </div>

        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-sm">{t("llmset.anomaly_title")}</div>
            <div className="text-[11px] text-muted-foreground">{t("llmset.anomaly_desc")}</div>
          </div>
          <Switch checked={cfg.anomaly_ai_enabled} onCheckedChange={(v) => upd("anomaly_ai_enabled", v)} data-testid="llm-anomaly-ai-toggle" />
        </div>

        <div className="py-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Eye size={13} className="text-muted-foreground" />
              <div>
                <div className="text-sm">{t("llmset.color_title")}</div>
                <div className="text-[11px] text-muted-foreground">{t("llmset.color_desc")}</div>
              </div>
            </div>
            <Switch checked={cfg.color_ai_enabled} onCheckedChange={(v) => upd("color_ai_enabled", v)} data-testid="llm-color-ai-toggle" />
          </div>
          {cfg.color_ai_enabled && (
            <div className="mt-2 pl-5 space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-[11px] text-muted-foreground">{t("llmset.auto_sync_desc")}</div>
                <Switch checked={cfg.color_ai_auto_sync_enabled} onCheckedChange={(v) => upd("color_ai_auto_sync_enabled", v)} data-testid="llm-color-ai-auto-sync-toggle" />
              </div>
              {cfg.color_ai_auto_sync_enabled && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">{t("llmset.lbl_daily_at")}</span>
                  <input type="time" value={cfg.color_ai_auto_sync_time}
                         onChange={(e) => upd("color_ai_auto_sync_time", e.target.value)}
                         className="px-2 py-1 bg-card border border-input outline-none text-xs focus:border-[#0044FF]"
                         data-testid="llm-color-ai-auto-sync-time" />
                </div>
              )}
              <div className="flex items-center justify-between gap-2">
                {colorStatus ? (
                  <div className="text-[10px] text-muted-foreground mono" data-testid="llm-color-ai-status">
                    {colorStatus.checked} / {colorStatus.total_eligible} {t("llmset.lbl_readings_checked_30d")} · {colorStatus.corrected} {t(colorStatus.corrected > 1 ? "llmset.lbl_corrected_many" : "llmset.lbl_corrected_one")}
                  </div>
                ) : <span />}
                <button onClick={runColorNow} disabled={colorRunning}
                        className="shrink-0 flex items-center gap-1 px-2 py-1 border border-border text-[10px] uppercase tracking-wider hover:bg-secondary/60 disabled:opacity-40"
                        data-testid="llm-color-ai-run-btn">
                  {colorRunning ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} {t("llmset.btn_check_now")}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="py-2.5 border-t border-border">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Car size={13} className="text-muted-foreground" />
              <div>
                <div className="text-sm">{t("llmset.make_title")}</div>
                <div className="text-[11px] text-muted-foreground">{t("llmset.make_desc")}</div>
              </div>
            </div>
            <Switch checked={cfg.make_ai_enabled} onCheckedChange={(v) => upd("make_ai_enabled", v)} data-testid="llm-make-ai-toggle" />
          </div>
          {cfg.make_ai_enabled && (
            <div className="mt-2 pl-5 space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-[11px] text-muted-foreground">{t("llmset.auto_sync_desc")}</div>
                <Switch checked={cfg.make_ai_auto_sync_enabled} onCheckedChange={(v) => upd("make_ai_auto_sync_enabled", v)} data-testid="llm-make-ai-auto-sync-toggle" />
              </div>
              {cfg.make_ai_auto_sync_enabled && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">{t("llmset.lbl_daily_at")}</span>
                  <input type="time" value={cfg.make_ai_auto_sync_time}
                         onChange={(e) => upd("make_ai_auto_sync_time", e.target.value)}
                         className="px-2 py-1 bg-card border border-input outline-none text-xs focus:border-[#0044FF]"
                         data-testid="llm-make-ai-auto-sync-time" />
                </div>
              )}
              <div className="flex items-center justify-between gap-2">
                {makeStatus ? (
                  <div className="text-[10px] text-muted-foreground mono" data-testid="llm-make-ai-status">
                    {makeStatus.checked} / {makeStatus.total_eligible} {t("llmset.lbl_readings_checked_30d")} · {makeStatus.corrected} {t(makeStatus.corrected > 1 ? "llmset.lbl_corrected_many" : "llmset.lbl_corrected_one")}
                  </div>
                ) : <span />}
                <button onClick={runMakeNow} disabled={makeRunning}
                        className="shrink-0 flex items-center gap-1 px-2 py-1 border border-border text-[10px] uppercase tracking-wider hover:bg-secondary/60 disabled:opacity-40"
                        data-testid="llm-make-ai-run-btn">
                  {makeRunning ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} {t("llmset.btn_check_now")}
                </button>
              </div>
            </div>
          )}
        </div>

        {!cfg.enabled && (cfg.dedup_enabled || cfg.anpr_tuning_enabled || cfg.anomaly_ai_enabled || cfg.color_ai_enabled || cfg.make_ai_enabled || cfg.identity_merge_ai_enabled) && (
          <p className="text-[11px] text-[#FFB800] mt-3">{t("llmset.warn_connection_disabled")}</p>
        )}
      </div>

      <button onClick={save} disabled={saving} data-testid="llm-save-btn"
              className="mt-4 flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
        {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
        {t("common.save")}
      </button>
    </div>
  );
}
