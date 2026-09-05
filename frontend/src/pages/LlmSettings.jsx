import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import { Brain, Save, Loader2, CheckCircle2, RefreshCw, Eye } from "lucide-react";
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
  vision_model: "qwen2.5vl:7b", color_ai_enabled: false,
};

const Inp = (p) => <input {...p} className="w-full px-3 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]" />;
const Sel = (p) => <select {...p} className="px-2 py-1.5 bg-card border border-input outline-none text-xs focus:border-[#0044FF]" />;
const Lbl = ({ children }) => <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{children}</label>;

const AUTO_APPROVE_INTERVALS = [
  { value: 30, label: "30 minutes" },
  { value: 60, label: "1 heure" },
  { value: 120, label: "2 heures" },
  { value: 360, label: "6 heures" },
  { value: 1440, label: "24 heures" },
];

function fmtDateTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR"); } catch { return iso; }
}

export default function LlmSettings() {
  const [cfg, setCfg] = useState(empty);
  const [saving, setSaving] = useState(false);
  const [autoStatus, setAutoStatus] = useState(null);
  const [colorStatus, setColorStatus] = useState(null);
  const [colorRunning, setColorRunning] = useState(false);

  const loadAutoStatus = () => {
    api.get("/vehicles/dedup/auto-approve/status").then((r) => setAutoStatus(r.data)).catch(() => {});
  };
  const loadColorStatus = () => {
    api.get("/vehicles/color-ai/status").then((r) => setColorStatus(r.data)).catch(() => {});
  };

  useEffect(() => {
    api.get("/settings/llm").then((r) => setCfg({ ...empty, ...r.data })).catch(() => {});
    loadAutoStatus();
    loadColorStatus();
    const iv = setInterval(() => { loadAutoStatus(); loadColorStatus(); }, 30000);
    return () => clearInterval(iv);
  }, []);

  const runColorNow = async () => {
    setColorRunning(true);
    try {
      await api.post("/vehicles/color-ai/run");
      toast.success("Vérification couleur lancée en arrière-plan — la progression se met à jour ci-dessous d'ici quelques minutes.");
      setTimeout(loadColorStatus, 15000);
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || "Échec du lancement");
    } finally { setColorRunning(false); }
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
      });
      setCfg({ ...empty, ...data });
      toast.success("Configuration LLM enregistrée");
      loadAutoStatus();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  return (
    <div className="p-4 max-w-2xl">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-1 flex items-center gap-2">
        <Brain size={22} className="text-[#0044FF]" /> LLM (MG-IA)
      </h1>
      <p className="text-sm text-muted-foreground mb-4">
        Connexion à un déploiement Qwen auto-hébergé, accessible en WAN — utilisée par plusieurs fonctionnalités : la recherche IA avancée, le dédoublonnage véhicule, le réglage automatique du seuil ANPR, les anomalies IA et la correction couleur véhicule (modèle vision dédié). Chacune a son propre interrupteur ci-dessous, en plus de la connexion.
      </p>

      <div className="bg-card border border-border p-5" data-testid="llm-settings-panel">
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Brain size={18} className="text-[#0044FF]" />
            <span className="font-head font-semibold">Recherche IA (Qwen)</span>
            {cfg.enabled && (
              <span className="text-[9px] uppercase tracking-wider mg-online flex items-center gap-1">
                <CheckCircle2 size={12} /> Actif
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{cfg.enabled ? "Actif" : "Désactivé"}</span>
            <Switch checked={cfg.enabled} onCheckedChange={(v) => upd("enabled", v)} data-testid="llm-enabled-toggle" />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <Lbl>URL du serveur (base URL)</Lbl>
            <Inp value={cfg.base_url} onChange={(e) => upd("base_url", e.target.value)}
                 placeholder="https://ia.mginformatique.com" data-testid="llm-base-url" />
          </div>
          <div>
            <Lbl>Modèle</Lbl>
            <Inp value={cfg.model} onChange={(e) => upd("model", e.target.value)}
                 placeholder="qwen2.5" data-testid="llm-model" />
          </div>
          <div>
            <Lbl>Clé API</Lbl>
            <Inp type="password" value={cfg.api_key} onChange={(e) => upd("api_key", e.target.value)}
                 placeholder={cfg.has_api_key ? "•••••••• (déjà enregistrée, laisser vide pour conserver)" : "Clé API du compte Open WebUI"}
                 data-testid="llm-api-key" />
          </div>
          <div className="col-span-2">
            <Lbl>Modèle vision (analyse d'image — couleur véhicule)</Lbl>
            <Inp value={cfg.vision_model} onChange={(e) => upd("vision_model", e.target.value)}
                 placeholder="qwen2.5vl:7b" data-testid="llm-vision-model" />
            <div className="text-[11px] text-muted-foreground mt-1">
              Distinct du modèle texte ci-dessus — aucun modèle texte ne peut voir une image. Même connexion (URL/clé), juste un nom de modèle différent, déployé séparément sur le serveur Ollama.
            </div>
          </div>
        </div>

        <p className="text-[11px] text-muted-foreground mt-3">
          La clé API se génère depuis le compte Open WebUI (ia.mginformatique.com) → Paramètres → Compte → Clés API.
        </p>
      </div>

      <div className="bg-card border border-border p-5 mt-4" data-testid="llm-features-panel">
        <div className="font-head font-semibold mb-3">Fonctionnalités utilisant cette connexion</div>

        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-sm">Dédoublonnage véhicule (Qwen)</div>
            <div className="text-[11px] text-muted-foreground">Suggère de fusionner des plaques probablement mal lues deux fois — tâche périodique + bouton manuel sur Plaques.</div>
          </div>
          <Switch checked={cfg.dedup_enabled} onCheckedChange={(v) => upd("dedup_enabled", v)} data-testid="llm-dedup-toggle" />
        </div>

        {cfg.dedup_enabled && (
          <div className="py-2.5 border-b border-border pl-3 border-l-2 border-l-[#0044FF]/30 space-y-2" data-testid="llm-dedup-auto-approve-block">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm">Auto-approbation des suggestions</div>
                <div className="text-[11px] text-muted-foreground">Approuve automatiquement TOUTES les suggestions en attente à l'intervalle choisi, sans validation manuelle — à utiliser avec prudence.</div>
              </div>
              <Switch checked={cfg.dedup_auto_approve_enabled} onCheckedChange={(v) => upd("dedup_auto_approve_enabled", v)} data-testid="llm-dedup-auto-approve-toggle" />
            </div>
            {cfg.dedup_auto_approve_enabled && (
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">Toutes les</span>
                <Sel value={cfg.dedup_auto_approve_interval_min}
                     onChange={(e) => upd("dedup_auto_approve_interval_min", Number(e.target.value))}
                     data-testid="llm-dedup-auto-approve-interval">
                  {AUTO_APPROVE_INTERVALS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </Sel>
              </div>
            )}
            {autoStatus?.enabled && (
              <div className="text-[10px] text-muted-foreground mono" data-testid="llm-dedup-auto-approve-status">
                {autoStatus.pending_count} en attente · dernier passage : {fmtDateTime(autoStatus.last_run_at)}
                {autoStatus.last_approved_count != null && ` (${autoStatus.last_approved_count} approuvée${autoStatus.last_approved_count > 1 ? "s" : ""})`}
                {autoStatus.next_run_at && ` · prochain : ${fmtDateTime(autoStatus.next_run_at)}`}
              </div>
            )}
          </div>
        )}

        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-sm">Réglage ANPR auto (Qwen)</div>
            <div className="text-[11px] text-muted-foreground">Ajuste le seuil de confiance ANPR par caméra selon la distribution des lectures — tâche hebdomadaire + bouton manuel sur Centre caméras.</div>
          </div>
          <Switch checked={cfg.anpr_tuning_enabled} onCheckedChange={(v) => upd("anpr_tuning_enabled", v)} data-testid="llm-anpr-tuning-toggle" />
        </div>

        <div className="flex items-center justify-between py-2.5 border-b border-border">
          <div>
            <div className="text-sm">Anomalies IA (Qwen)</div>
            <div className="text-[11px] text-muted-foreground">Explique en langage clair les écarts d'habitudes par véhicule, les convois répétés et les pics de trafic inhabituels — menu dédié "Anomalies IA", tâche périodique + bouton manuel.</div>
          </div>
          <Switch checked={cfg.anomaly_ai_enabled} onCheckedChange={(v) => upd("anomaly_ai_enabled", v)} data-testid="llm-anomaly-ai-toggle" />
        </div>

        <div className="py-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Eye size={13} className="text-muted-foreground" />
              <div>
                <div className="text-sm">Correction couleur véhicule (vision)</div>
                <div className="text-[11px] text-muted-foreground">Le classifieur couleur actuel a un biais mesuré (confond gris/argent et bleu). Le modèle vision revérifie les lectures récentes et corrige — tâche périodique + bouton manuel. Ignore automatiquement les images monochromes IR (nuit) — aucune couleur fiable à en tirer.</div>
              </div>
            </div>
            <Switch checked={cfg.color_ai_enabled} onCheckedChange={(v) => upd("color_ai_enabled", v)} data-testid="llm-color-ai-toggle" />
          </div>
          {cfg.color_ai_enabled && (
            <div className="mt-2 flex items-center justify-between gap-2 pl-5">
              {colorStatus ? (
                <div className="text-[10px] text-muted-foreground mono" data-testid="llm-color-ai-status">
                  {colorStatus.checked} / {colorStatus.total_eligible} lectures vérifiées (30j) · {colorStatus.corrected} corrigée{colorStatus.corrected > 1 ? "s" : ""}
                </div>
              ) : <span />}
              <button onClick={runColorNow} disabled={colorRunning}
                      className="shrink-0 flex items-center gap-1 px-2 py-1 border border-border text-[10px] uppercase tracking-wider hover:bg-secondary/60 disabled:opacity-40"
                      data-testid="llm-color-ai-run-btn">
                {colorRunning ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} Vérifier maintenant
              </button>
            </div>
          )}
        </div>

        {!cfg.enabled && (cfg.dedup_enabled || cfg.anpr_tuning_enabled || cfg.anomaly_ai_enabled || cfg.color_ai_enabled) && (
          <p className="text-[11px] text-[#FFB800] mt-3">La connexion ci-dessus est désactivée — ces fonctionnalités resteront inactives tant qu'elle ne l'est pas.</p>
        )}
      </div>

      <button onClick={save} disabled={saving} data-testid="llm-save-btn"
              className="mt-4 flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
        {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
        Enregistrer
      </button>
    </div>
  );
}
