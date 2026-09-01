import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import { Brain, Save, Loader2, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

/**
 * LlmSettings — Configuration LLM (recherche IA avancée), menu admin.
 *
 * v3.19 · Remplace la clé cloud EMERGENT_LLM_KEY par une instance Qwen
 * auto-hébergée, exposée en WAN via un domaine dédié — pensé pour un
 * déploiement client simple : une URL, une clé API, un switch, pas
 * d'édition manuelle de fichier .env par site. Voir backend/routes/llm_settings.py.
 */
const empty = { enabled: false, base_url: "https://ia.mginformatique.com", model: "qwen2.5", api_key: "", has_api_key: false, dedup_enabled: false, anpr_tuning_enabled: false };

const Inp = (p) => <input {...p} className="w-full px-3 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]" />;
const Lbl = ({ children }) => <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{children}</label>;

export default function LlmSettings() {
  const [cfg, setCfg] = useState(empty);
  const [saving, setSaving] = useState(false);

  useEffect(() => { api.get("/settings/llm").then((r) => setCfg({ ...empty, ...r.data })).catch(() => {}); }, []);

  const upd = (k, v) => setCfg((c) => ({ ...c, [k]: v }));

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/settings/llm", {
        enabled: cfg.enabled, base_url: cfg.base_url, model: cfg.model, api_key: cfg.api_key,
        dedup_enabled: cfg.dedup_enabled, anpr_tuning_enabled: cfg.anpr_tuning_enabled,
      });
      setCfg({ ...empty, ...data });
      toast.success("Configuration LLM enregistrée");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  return (
    <div className="p-4 max-w-2xl">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-1 flex items-center gap-2">
        <Brain size={22} className="text-[#0044FF]" /> LLM (MG-IA)
      </h1>
      <p className="text-sm text-muted-foreground mb-4">
        Connexion à un déploiement Qwen auto-hébergé, accessible en WAN — utilisée par 3 fonctionnalités : la recherche IA avancée, le dédoublonnage véhicule et le réglage automatique du seuil ANPR. Chacune des deux dernières a son propre interrupteur ci-dessous, en plus de la connexion.
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

        <div className="flex items-center justify-between py-2.5">
          <div>
            <div className="text-sm">Réglage ANPR auto (Qwen)</div>
            <div className="text-[11px] text-muted-foreground">Ajuste le seuil de confiance ANPR par caméra selon la distribution des lectures — tâche hebdomadaire + bouton manuel sur Centre caméras.</div>
          </div>
          <Switch checked={cfg.anpr_tuning_enabled} onCheckedChange={(v) => upd("anpr_tuning_enabled", v)} data-testid="llm-anpr-tuning-toggle" />
        </div>

        {!cfg.enabled && (cfg.dedup_enabled || cfg.anpr_tuning_enabled) && (
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
