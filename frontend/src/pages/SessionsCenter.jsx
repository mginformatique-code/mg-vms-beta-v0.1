/**
 * SessionsCenter.jsx — v0.5.5.b
 *
 * Page dédiée aux sessions actives. Auparavant intégrée en tant que
 * Card dans /settings, promue en page complète accessible depuis le
 * sous-menu « Centre de sécurité → Sessions actives ».
 *
 * Fonctionnalités :
 *  - KPIs : session courante, nb total, IP unique, timeout configuré
 *  - Timeout configurable (admin) parmi 7 valeurs préréglées
 *  - Liste détaillée : navigateur, IP, date connexion, dernière activité,
 *    expiration, badge « actuelle », bouton révoquer
 *  - Révocation individuelle + bouton « Déconnecter toutes les autres »
 */
import React, { useEffect, useMemo, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  LogOut, Clock, Wifi, Monitor, RefreshCw, Loader2, Users,
  AlertCircle, Shield, Info,
} from "lucide-react";

export default function SessionsCenter() {
  const { t, user } = useApp();
  const [data, setData] = useState({ items: [], current_jti: null });
  const [timeoutCfg, setTimeoutCfg] = useState({ session_hours: 8, options: [0.25, 0.5, 1, 4, 8, 12, 24] });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const isAdmin = user?.role === "admin";

  const load = async () => {
    try {
      const [r1, r2] = await Promise.all([
        api.get("/security/sessions"),
        api.get("/security/timeout"),
      ]);
      setData(r1.data);
      setTimeoutCfg(r2.data);
    } catch (e) { /* noop */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, []);

  const revoke = async (jti) => {
    if (!window.confirm(t("security.revoke_confirm") || "Déconnecter cette session ?")) return;
    setBusy(true);
    try {
      await api.delete(`/security/sessions/${jti}`);
      await load();
      toast.success(t("security.revoked") || "Session révoquée");
    } catch (e) { toast.error(t("security.revoke_failed") || "Échec"); }
    finally { setBusy(false); }
  };
  const revokeOthers = async () => {
    if (!window.confirm(t("security.revoke_others_confirm") || "Déconnecter toutes les autres sessions ?")) return;
    setBusy(true);
    try {
      const r = await api.post("/security/sessions/revoke-others");
      toast.success(`${r.data.revoked_count} session(s) révoquée(s)`);
      await load();
    } catch (e) { toast.error("Échec"); }
    finally { setBusy(false); }
  };
  const setHours = async (h) => {
    try {
      await api.put("/security/timeout", { session_hours: Number(h) });
      await load();
      toast.success(t("security.timeout_saved") || "Timeout mis à jour");
    } catch (e) { toast.error("Échec"); }
  };

  const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
  const uaShort = (ua) => {
    if (!ua) return "Inconnu";
    if (ua.includes("Chrome")) return "Chrome";
    if (ua.includes("Firefox")) return "Firefox";
    if (ua.includes("Safari")) return "Safari";
    if (ua.includes("Edge")) return "Edge";
    return ua.slice(0, 30);
  };

  const uniqueIps = useMemo(() => new Set(data.items.map((s) => s.ip)).size, [data.items]);
  const currentSession = useMemo(() => data.items.find((s) => s.current), [data.items]);

  return (
    <div className="p-6 max-w-5xl mx-auto" data-testid="sessions-center-page">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <LogOut size={26} className="text-[#0044FF]" />
          <div>
            <h1 className="font-head font-bold text-2xl tracking-tight">Sessions actives</h1>
            <p className="text-xs text-muted-foreground">Suivi et révocation des connexions à votre compte</p>
          </div>
        </div>
        <button onClick={load} disabled={loading}
          className="px-3 py-2 border border-border text-sm flex items-center gap-2 hover:bg-secondary"
          data-testid="sessions-refresh-btn">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Actualiser
        </button>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <KpiTile icon={Users} label="Sessions actives" value={data.items.length} color="#0044FF" />
        <KpiTile icon={Wifi} label="IP uniques" value={uniqueIps} color="#00E676" />
        <KpiTile icon={Clock} label="Timeout actuel" value={timeoutCfg.session_hours < 1 ? `${timeoutCfg.session_hours * 60}min` : `${timeoutCfg.session_hours}h`} color="#FFB800" />
        <KpiTile icon={Monitor} label="Session courante" value={currentSession ? uaShort(currentSession.user_agent) : "—"} color="#FF7043" />
      </div>

      {/* Timeout admin */}
      {isAdmin && (
        <div className="border border-border bg-card p-5 mb-4" data-testid="sessions-timeout-panel">
          <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-3 flex items-center gap-2">
            <Clock size={14} /> Durée de session avant déconnexion automatique
          </div>
          <div className="flex flex-wrap gap-2">
            {timeoutCfg.options.map((h) => (
              <button key={h} onClick={() => setHours(h)}
                data-testid={`sessions-timeout-${h}`}
                className={`px-3 py-1.5 text-xs mono border transition-colors ${
                  timeoutCfg.session_hours === h
                    ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF]"
                    : "border-border hover:bg-secondary"
                }`}>
                {h < 1 ? `${h * 60}min` : `${h}h`}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground mt-2 flex items-center gap-1">
            <Info size={11} /> Prend effet à la prochaine connexion. Vaut pour tous les utilisateurs de l&apos;instance.
          </p>
        </div>
      )}

      {/* Actions bar */}
      <div className="flex items-center justify-between mb-2 px-1">
        <div className="text-xs text-muted-foreground">
          {data.items.length} session(s) trouvée(s)
        </div>
        {data.items.length > 1 && (
          <button onClick={revokeOthers} disabled={busy}
            className="text-xs text-[#FF3333] hover:underline flex items-center gap-1"
            data-testid="sessions-revoke-others">
            <LogOut size={12} /> Déconnecter toutes les autres
          </button>
        )}
      </div>

      {/* Sessions table */}
      <div className="border border-border bg-card" data-testid="sessions-list">
        <div className="hidden md:grid grid-cols-[1.5fr_1fr_1.4fr_1.4fr_120px] gap-3 px-4 py-2 bg-muted text-[10px] uppercase tracking-widest text-muted-foreground border-b border-border">
          <div>Navigateur / Client</div><div>Adresse IP</div><div>Dernière activité</div><div>Expiration</div><div className="text-right">Action</div>
        </div>
        {loading && (
          <div className="p-6 text-center text-sm text-muted-foreground flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Chargement...
          </div>
        )}
        {!loading && data.items.length === 0 && (
          <div className="p-6 text-center text-sm text-muted-foreground">
            <AlertCircle size={20} className="mx-auto mb-2 opacity-60" />
            Aucune session active trouvée.
          </div>
        )}
        {data.items.map((s) => (
          <div key={s.jti}
               className={`grid grid-cols-1 md:grid-cols-[1.5fr_1fr_1.4fr_1.4fr_120px] gap-3 px-4 py-3 border-b border-border/60 last:border-b-0 items-center ${s.current ? "bg-[#00E676]/5" : ""}`}
               data-testid={`session-row-${s.jti}`}>
            <div className="text-sm flex items-center gap-2">
              <span className="font-medium">{uaShort(s.user_agent)}</span>
              {s.current && (
                <span className="text-[9px] mono uppercase tracking-wider px-1.5 py-0.5 bg-[#00E676]/20 text-[#00E676] border border-[#00E676]/50">
                  actuelle
                </span>
              )}
            </div>
            <div className="text-xs mono text-muted-foreground flex items-center gap-1">
              <Wifi size={11} /> {s.ip || "—"}
            </div>
            <div className="text-xs mono text-muted-foreground flex items-center gap-1">
              <Clock size={11} /> {fmt(s.last_seen_at)}
            </div>
            <div className="text-xs mono text-muted-foreground">
              Expire : {fmt(s.expires_at)}
            </div>
            <div className="text-right">
              {!s.current && (
                <button onClick={() => revoke(s.jti)} disabled={busy}
                  className="text-xs text-[#FF3333] hover:underline"
                  data-testid={`session-revoke-${s.jti}`}>
                  Déconnecter
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Hint */}
      <div className="mt-4 border border-border p-3 bg-card flex items-start gap-2">
        <Shield size={14} className="text-[#0044FF] mt-0.5" />
        <p className="text-xs text-muted-foreground leading-relaxed">
          Une session peut être révoquée à distance à tout moment. La révocation
          est immédiate : la prochaine requête effectuée par ce token sera
          rejetée avec un 401.
        </p>
      </div>
    </div>
  );
}

function KpiTile({ icon: Icon, label, value, color }) {
  return (
    <div className="border border-border bg-card p-3" data-testid={`sessions-kpi-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
        <Icon size={11} style={{ color }} /> {label}
      </div>
      <div className="text-xl mono font-black" style={{ color }}>{value}</div>
    </div>
  );
}
