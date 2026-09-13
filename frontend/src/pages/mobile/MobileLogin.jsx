/**
 * MobileLogin — page de connexion dédiée mobile (v3.92).
 *
 * `Login.jsx` (desktop) place le logo UNIQUEMENT dans le panneau de marque
 * gauche (`hidden lg:flex`) — invisible en dessous de 1024px, donc sur
 * TOUT téléphone (bug réel confirmé par capture d'écran utilisateur : page
 * de connexion sans aucun logo). Plutôt que de retoucher la mise en page
 * desktop (risque de régression sur un flux d'authentification), page
 * dédiée : logo centré en tête, formulaire compact en dessous — même
 * logique de connexion/2FA/mot de passe oublié que `Login.jsx` (dupliquée
 * ici volontairement, code court, pour ne prendre aucun risque sur le flux
 * desktop déjà en production).
 */
import React, { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Loader2, Moon, Sun, Languages, Clock } from "lucide-react";
import { toast } from "sonner";
import Logo from "@/components/Logo";
import HoldToRevealInput from "@/components/ui/hold-to-reveal-input";

export default function MobileLogin() {
  const { login, t, theme, toggleTheme, lang, toggleLang, user } = useApp();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const inactivityLogout = searchParams.get("reason") === "inactivity";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [need2fa, setNeed2fa] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [forgotMode, setForgotMode] = useState(false);
  const [forgotEmail, setForgotEmail] = useState("");

  useEffect(() => { if (user) navigate("/"); }, [user, navigate]);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const res = await login(email, password, need2fa ? totp : undefined);
      if (res.requires_2fa) { setNeed2fa(true); toast.info(t("login.toast_2fa_required")); }
      else { toast.success(t("login.toast_success")); navigate("/"); }
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally { setLoading(false); }
  };

  const submitForgot = async (e) => {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      await api.post("/auth/forgot-password", { email: forgotEmail || email });
      toast.success(t("auth.forgot_sent"));
      setForgotMode(false);
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-[100dvh] flex flex-col bg-background text-foreground px-5" data-testid="mobile-login">
      <div className="flex justify-end gap-1 pt-3">
        <button onClick={toggleLang} className="px-2 py-2 text-muted-foreground flex items-center gap-1 text-xs uppercase"><Languages size={15} /> {lang}</button>
        <button onClick={toggleTheme} className="p-2 text-muted-foreground">{theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}</button>
      </div>

      <div className="flex flex-col items-center pt-6 pb-8">
        <Logo size={64} className="w-16 h-16" data-testid="mobile-login-logo" />
        <div className="font-head font-black text-lg tracking-tight mt-2">MG-VMS</div>
        <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">MG Informatique</div>
      </div>

      {forgotMode ? (
        <form onSubmit={submitForgot} className="w-full" data-testid="mobile-forgot-form">
          <h2 className="font-head font-bold text-xl tracking-tight mb-1">{t("auth.forgot_title")}</h2>
          <p className="text-sm text-muted-foreground mb-6">{t("auth.forgot_sub")}</p>
          <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("common.email")}</label>
          <input data-testid="mobile-forgot-email" type="email" value={forgotEmail} onChange={(e) => setForgotEmail(e.target.value)} required
            className="w-full mb-2 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm" />
          {error && <div className="text-xs text-[#FF3333] mb-3 py-2 px-3 border border-[#FF3333]/30 bg-[#FF3333]/10">{error}</div>}
          <button data-testid="mobile-forgot-submit" type="submit" disabled={loading}
            className="w-full mt-3 py-3 bg-[#0044FF] text-white font-medium text-sm flex items-center justify-center gap-2 disabled:opacity-60">
            {loading && <Loader2 size={16} className="animate-spin" />} {t("auth.forgot_btn")}
          </button>
          <button type="button" onClick={() => { setForgotMode(false); setError(""); }} data-testid="mobile-back-login"
            className="w-full mt-2 py-2 text-xs text-muted-foreground">{t("auth.back_login")}</button>
        </form>
      ) : (
        <form onSubmit={submit} className="w-full" data-testid="mobile-login-form">
          {inactivityLogout && (
            <div className="mb-4 p-3 border border-[#FFB800] bg-[#FFB800]/10 text-[#FFB800] text-xs flex items-start gap-2" data-testid="mobile-inactivity-banner">
              <Clock size={14} className="mt-0.5 shrink-0" />
              <div>
                <div className="font-semibold mb-0.5">{t("login.inactivity_title")}</div>
                {t("login.inactivity_message")}
              </div>
              <button type="button" onClick={() => setSearchParams({}, { replace: true })}
                      className="ml-auto text-[#FFB800]/70" aria-label={t("common.close")}>✕</button>
            </div>
          )}

          {!need2fa ? (
            <>
              <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("common.email")}</label>
              <input data-testid="mobile-login-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="off"
                className="w-full mb-4 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm" />
              <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("common.password")}</label>
              <HoldToRevealInput data-testid="mobile-login-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password"
                className="w-full mb-2 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm" />
              <button type="button" onClick={() => { setForgotMode(true); setForgotEmail(email); setError(""); }} data-testid="mobile-forgot-link"
                className="text-[11px] text-[#0044FF] mb-2">{t("auth.forgot_title")} ?</button>
            </>
          ) : (
            <>
              <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("login.twofa")}</label>
              <input data-testid="mobile-login-totp" value={totp} onChange={(e) => setTotp(e.target.value)} placeholder={t("login.twofa_hint")} autoFocus
                className="w-full mb-2 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm mono tracking-[0.4em] text-center" />
            </>
          )}

          {error && <div data-testid="mobile-login-error" className="text-xs text-[#FF3333] mb-3 py-2 px-3 border border-[#FF3333]/30 bg-[#FF3333]/10">{error}</div>}

          <button data-testid="mobile-login-submit" type="submit" disabled={loading}
            className="w-full mt-2 py-3 bg-[#0044FF] text-white font-medium text-sm flex items-center justify-center gap-2 disabled:opacity-60">
            {loading && <Loader2 size={16} className="animate-spin" />} {t("login.signin")}
          </button>
        </form>
      )}
    </div>
  );
}
