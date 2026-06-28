import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import { formatApiErrorDetail } from "@/lib/api";
import { ShieldCheck, Loader2, Moon, Sun, Languages } from "lucide-react";
import { toast } from "sonner";

export default function Login() {
  const { login, t, theme, toggleTheme, lang, toggleLang, user } = useApp();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@mg-vms.com");
  const [password, setPassword] = useState("Admin@2026");
  const [totp, setTotp] = useState("");
  const [need2fa, setNeed2fa] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { if (user) navigate("/"); }, [user, navigate]);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const res = await login(email, password, need2fa ? totp : undefined);
      if (res.requires_2fa) { setNeed2fa(true); toast.info("Code 2FA requis"); }
      else { toast.success("Connexion réussie"); navigate("/"); }
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen flex bg-background text-foreground">
      {/* Left brand panel */}
      <div className="hidden lg:flex w-1/2 relative overflow-hidden border-r border-border">
        <img src="https://images.unsplash.com/photo-1693541684739-e714db2637e2?w=1200&q=80" alt="" className="absolute inset-0 w-full h-full object-cover opacity-30" />
        <div className="absolute inset-0 bg-background/70" />
        <div className="relative z-10 flex flex-col justify-between p-12 w-full">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary flex items-center justify-center">
              <ShieldCheck className="text-primary-foreground" />
            </div>
            <div>
              <div className="font-head font-black text-xl tracking-tight">MG-VMS</div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">MG Informatique</div>
            </div>
          </div>
          <div>
            <h1 className="font-head font-black text-4xl xl:text-5xl tracking-tight leading-tight mb-4">
              Centre de<br />commandement<br /><span className="text-[#0044FF]">vidéosurveillance</span>
            </h1>
            <p className="text-muted-foreground text-sm max-w-md">{t("app.tagline")} — gérez des centaines de caméras, ANPR, alertes intelligentes et multi-sites depuis une plateforme unique.</p>
          </div>
          <div className="flex gap-6 text-xs text-muted-foreground mono">
            <span><span className="mg-online">●</span> 18 ONLINE</span>
            <span><span className="mg-warning">●</span> ANPR ACTIVE</span>
            <span><span className="mg-active">●</span> AI ENGINE</span>
          </div>
        </div>
      </div>

      {/* Form */}
      <div className="flex-1 flex flex-col">
        <div className="flex justify-end gap-2 p-4">
          <button onClick={toggleLang} className="px-2 py-2 hover:bg-secondary flex items-center gap-1 text-xs uppercase"><Languages size={16} /> {lang}</button>
          <button onClick={toggleTheme} className="p-2 hover:bg-secondary">{theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}</button>
        </div>
        <div className="flex-1 flex items-center justify-center px-6">
          <form onSubmit={submit} className="w-full max-w-sm fade-up" data-testid="login-form">
            <h2 className="font-head font-bold text-2xl tracking-tight mb-1">{t("login.title")}</h2>
            <p className="text-sm text-muted-foreground mb-8">{t("login.subtitle")}</p>

            {!need2fa ? (
              <>
                <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("common.email")}</label>
                <input data-testid="login-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
                  className="w-full mb-4 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm" />
                <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("common.password")}</label>
                <input data-testid="login-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                  className="w-full mb-2 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm" />
              </>
            ) : (
              <>
                <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("login.twofa")}</label>
                <input data-testid="login-totp" value={totp} onChange={(e) => setTotp(e.target.value)} placeholder={t("login.twofa_hint")} autoFocus
                  className="w-full mb-2 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm mono tracking-[0.4em] text-center" />
              </>
            )}

            {error && <div data-testid="login-error" className="text-xs text-[#FF3333] mb-3 py-2 px-3 border border-[#FF3333]/30 bg-[#FF3333]/10">{error}</div>}

            <button data-testid="login-submit" type="submit" disabled={loading}
              className="w-full mt-3 py-2.5 bg-[#0044FF] text-white font-medium text-sm hover:bg-[#0033cc] transition-colors flex items-center justify-center gap-2 disabled:opacity-60">
              {loading && <Loader2 size={16} className="animate-spin" />} {t("login.signin")}
            </button>

            <div className="mt-8 text-[11px] text-muted-foreground border-t border-border pt-4 mono leading-relaxed">
              admin@mg-vms.com / Admin@2026<br />
              tech@mg-vms.com / Tech@2026<br />
              viewer@mg-vms.com / Viewer@2026
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
