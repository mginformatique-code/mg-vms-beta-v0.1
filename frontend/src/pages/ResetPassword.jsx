import React, { useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { ShieldCheck, Loader2 } from "lucide-react";
import { toast } from "sonner";

export default function ResetPassword() {
  const { t } = useApp();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") || "";
  const [pwd, setPwd] = useState("");
  const [pwd2, setPwd2] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (pwd.length < 8) return setError(t("auth.pwd_min"));
    if (pwd !== pwd2) return setError(t("auth.pwd_mismatch"));
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: pwd });
      toast.success(t("auth.reset_done"));
      navigate("/login");
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background text-foreground px-6">
      <form onSubmit={submit} className="w-full max-w-sm fade-up" data-testid="reset-form">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-9 h-9 bg-primary flex items-center justify-center"><ShieldCheck size={18} className="text-primary-foreground" /></div>
          <div className="font-head font-black text-lg">MG-VMS</div>
        </div>
        <h2 className="font-head font-bold text-2xl tracking-tight mb-1">{t("auth.reset_title")}</h2>
        <p className="text-sm text-muted-foreground mb-8">{t("auth.reset_sub")}</p>
        {!token && <div className="text-xs text-[#FF3333] mb-3 py-2 px-3 border border-[#FF3333]/30 bg-[#FF3333]/10">{t("auth.no_token")}</div>}
        <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("auth.new_password")}</label>
        <input data-testid="reset-pwd" type="password" value={pwd} onChange={(e) => setPwd(e.target.value)} required
          className="w-full mb-4 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm" />
        <label className="block text-xs uppercase tracking-wider text-muted-foreground mb-1">{t("auth.confirm_password")}</label>
        <input data-testid="reset-pwd2" type="password" value={pwd2} onChange={(e) => setPwd2(e.target.value)} required
          className="w-full mb-2 px-3 py-2.5 bg-card border border-input focus:border-[#0044FF] outline-none text-sm" />
        {error && <div data-testid="reset-error" className="text-xs text-[#FF3333] mb-3 py-2 px-3 border border-[#FF3333]/30 bg-[#FF3333]/10">{error}</div>}
        <button data-testid="reset-submit" type="submit" disabled={loading || !token}
          className="w-full mt-3 py-2.5 bg-[#0044FF] text-white font-medium text-sm hover:bg-[#0033cc] flex items-center justify-center gap-2 disabled:opacity-60">
          {loading && <Loader2 size={16} className="animate-spin" />} {t("auth.reset_btn")}
        </button>
        <button type="button" onClick={() => navigate("/login")} className="w-full mt-2 py-2 text-xs text-muted-foreground hover:text-foreground">{t("auth.back_login")}</button>
      </form>
    </div>
  );
}
