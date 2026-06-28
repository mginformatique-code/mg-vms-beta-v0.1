import React, { useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Moon, Sun, Languages, ShieldCheck, Monitor, Loader2 } from "lucide-react";
import { toast } from "sonner";

export default function SettingsPage() {
  const { t, theme, setTheme, lang, setLang, user, setUser } = useApp();
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);

  const start2fa = async () => {
    setLoading(true);
    try { const { data } = await api.post("/auth/2fa/setup"); setSetup(data); } catch (e) { toast.error("Erreur"); } finally { setLoading(false); }
  };
  const verify2fa = async () => {
    try { await api.post("/auth/2fa/verify", { code }); toast.success("2FA activée"); setUser({ ...user, twofa_enabled: true }); setSetup(null); setCode(""); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const disable2fa = async () => { await api.post("/auth/2fa/disable"); toast.success("2FA désactivée"); setUser({ ...user, twofa_enabled: false }); };

  const Card = ({ title, icon: Icon, children }) => (
    <div className="bg-card border border-border p-5 mb-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-4"><Icon size={15} /> {title}</div>
      {children}
    </div>
  );
  const Opt = ({ active, onClick, icon: Icon, label, tid }) => (
    <button onClick={onClick} data-testid={tid} className={`flex items-center gap-2 px-4 py-2.5 border text-sm transition-colors ${active ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF]" : "border-border hover:bg-secondary"}`}>
      <Icon size={16} /> {label}
    </button>
  );

  return (
    <div className="p-4 max-w-2xl">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-4">{t("settings.title")}</h1>

      <Card title={t("settings.appearance")} icon={Monitor}>
        <div className="text-xs text-muted-foreground mb-2">{t("settings.theme")}</div>
        <div className="flex gap-2 mb-5">
          <Opt active={theme === "dark"} onClick={() => setTheme("dark")} icon={Moon} label="Dark" tid="theme-dark" />
          <Opt active={theme === "light"} onClick={() => setTheme("light")} icon={Sun} label="Light" tid="theme-light" />
        </div>
        <div className="text-xs text-muted-foreground mb-2">{t("settings.language")}</div>
        <div className="flex gap-2">
          <Opt active={lang === "fr"} onClick={() => setLang("fr")} icon={Languages} label="Français" tid="lang-fr" />
          <Opt active={lang === "en"} onClick={() => setLang("en")} icon={Languages} label="English" tid="lang-en" />
        </div>
      </Card>

      <Card title={t("settings.security")} icon={ShieldCheck}>
        <div className="text-sm font-medium mb-1">{t("settings.twofa")}</div>
        <div className="text-xs text-muted-foreground mb-4">
          {user?.twofa_enabled ? <span className="mg-online">● Activée</span> : <span className="mg-offline">● Désactivée</span>}
        </div>
        {user?.twofa_enabled ? (
          <button onClick={disable2fa} data-testid="disable-2fa-btn" className="px-4 py-2 border border-[#FF3333] text-[#FF3333] text-sm hover:bg-[#FF3333]/10">{t("settings.twofa_disable")}</button>
        ) : setup ? (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{t("settings.scan")}</p>
            <img src={`https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(setup.otpauth_uri)}`} alt="QR" className="bg-white p-2" />
            <div className="text-[10px] mono text-muted-foreground break-all">SECRET: {setup.secret}</div>
            <div className="flex gap-2">
              <input value={code} onChange={(e) => setCode(e.target.value)} data-testid="2fa-code" placeholder="000000" className="px-3 py-2 bg-card border border-input outline-none mono tracking-[0.3em] text-center w-32" />
              <button onClick={verify2fa} data-testid="verify-2fa-btn" className="px-4 py-2 bg-[#0044FF] text-white text-sm">{t("common.confirm")}</button>
            </div>
          </div>
        ) : (
          <button onClick={start2fa} disabled={loading} data-testid="enable-2fa-btn" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{loading && <Loader2 size={15} className="animate-spin" />}{t("settings.twofa_enable")}</button>
        )}
      </Card>

      <Card title="Compte" icon={ShieldCheck}>
        <div className="grid grid-cols-2 gap-y-2 text-sm">
          <span className="text-muted-foreground">{t("common.name")}</span><span>{user?.name}</span>
          <span className="text-muted-foreground">{t("common.email")}</span><span className="mono">{user?.email}</span>
          <span className="text-muted-foreground">{t("common.role")}</span><span className="uppercase text-[#0044FF]">{user?.role}</span>
        </div>
      </Card>
    </div>
  );
}
