import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { KeyRound, Ban, Loader2 } from "lucide-react";

export default function LicenseSection({ t }) {
  const [state, setState] = useState(null);
  const [key, setKey] = useState("");
  const [activating, setActivating] = useState(false);

  const load = async () => {
    try { const { data } = await api.get("/license/status"); setState(data); }
    catch (e) { /* ignore */ }
  };
  useEffect(() => { load(); }, []);

  const activate = async () => {
    if (!key.trim()) return toast.error("Clé de licence requise");
    setActivating(true);
    try {
      await api.post("/license/activate", { license_key: key.trim() });
      toast.success("Licence activée"); setKey(""); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Clé invalide"); }
    finally { setActivating(false); }
  };

  const deactivate = async () => {
    if (!window.confirm("Désactiver la licence actuelle ?")) return;
    try { await api.delete("/license/deactivate"); toast.success("Licence désactivée"); load(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec"); }
  };

  const lic = state?.license;

  return (
    <div className="border border-border p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground">
          <KeyRound size={14} /> {t("license.title")}
        </div>
        {state && (
          <span
            className={`inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 border ${
              state.active ? "text-[#00E676] border-[#00E676]/60 bg-[#00E676]/10"
                : state.expired ? "text-[#FF3333] border-[#FF3333]/60 bg-[#FF3333]/10"
                : "text-muted-foreground border-border"
            }`}
            data-testid="license-badge"
          >
            {state.active ? t("license.status_active") : state.expired ? t("license.status_expired") : t("license.status_none")}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed mb-2">{t("license.desc")}</p>

      {lic && (
        <div className="border border-border p-2 mb-2 bg-background">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm mb-2">
            <div>
              <div className="text-[10px] text-muted-foreground">{t("license.client")}</div>
              <div className="text-xs" data-testid="license-client">{lic.client}</div>
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground">{t("license.type")}</div>
              <div className="text-xs uppercase" data-testid="license-type">{lic.type}</div>
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground">{t("license.expires")}</div>
              <div className="text-xs mono" data-testid="license-expires">
                {lic.expires_at ? new Date(lic.expires_at).toLocaleDateString("fr-FR") : "—"}
              </div>
            </div>
          </div>
          <button onClick={deactivate} data-testid="license-deactivate"
            className="flex items-center gap-1.5 px-3 py-1.5 border border-[#FF3333] text-[#FF3333] text-xs hover:bg-[#FF3333]/10">
            <Ban size={12} /> Désactiver
          </button>
        </div>
      )}

      <label className="text-xs text-muted-foreground block mb-1">{t("license.key_label")}</label>
      <div className="flex gap-2">
        <input type="text" placeholder={t("license.key_placeholder")} value={key}
               onChange={(e) => setKey(e.target.value)}
               data-testid="license-key-input"
               className="flex-1 px-3 py-2 bg-background border border-input outline-none mono text-xs focus:border-[#0044FF]" />
        <button onClick={activate} disabled={activating || !key.trim()} data-testid="license-activate-btn"
                className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
          {activating ? <Loader2 size={13} className="animate-spin" /> : <KeyRound size={13} />} {t("license.activate")}
        </button>
      </div>
    </div>
  );
}
