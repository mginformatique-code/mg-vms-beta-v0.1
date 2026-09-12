import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { AlertTriangle, ShieldAlert, Wifi, Check, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import ContainerStatusPanel from "./ContainerStatusPanel";
import { useApp } from "@/context/AppContext";

/**
 * NetworkConfig.jsx — Réseau → Paramètres réseau (v3.51).
 *
 * IP / passerelle / DNS de la MACHINE (ou VM) qui héberge MG-VMS — pas une
 * option de l'application. Le conteneur backend n'a jamais d'accès réseau
 * à l'hôte : cette page dépose une DEMANDE (voir routes/system_admin.py),
 * appliquée côté hôte par network-watch.sh (timer systemd, voir
 * install.sh). Filet de sécurité intégré : toute nouvelle config doit être
 * confirmée depuis cette même page sous 90s, sinon la précédente est
 * restaurée automatiquement — une IP/passerelle fausse ne doit jamais
 * couper l'accès à la machine sans retour en arrière possible.
 */
const Field = ({ label, hint, children }) => (
  <label className="block">
    <span className="block text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1">{label}</span>
    {children}
    {hint && <span className="block text-[10px] text-muted-foreground/70 mt-1">{hint}</span>}
  </label>
);

export default function NetworkConfig() {
  const { t } = useApp();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [method, setMethod] = useState("auto");
  const [ip, setIp] = useState("");
  const [prefix, setPrefix] = useState(24);
  const [gateway, setGateway] = useState("");
  const [dns, setDns] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const load = async () => {
    try {
      const { data } = await api.get("/system/network");
      setStatus(data);
      if (data.available && data.current && !data.pending_confirm) {
        setMethod(data.current.method === "manual" ? "manual" : "auto");
        setIp(data.current.ip || "");
        setPrefix(data.current.prefix || 24);
        setGateway(data.current.gateway || "");
        setDns((data.current.dns || []).join(", "));
      }
    } catch { /* silencieux */ }
    finally { setLoading(false); }
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, status?.pending_confirm ? 3000 : 15000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!status?.pending_confirm]);

  const submit = async (e) => {
    e.preventDefault();
    if (!window.confirm(t("netcfg.confirm_apply"))) return;
    setSubmitting(true);
    try {
      const dnsList = dns.split(",").map((s) => s.trim()).filter(Boolean);
      await api.put("/system/network", { method, ip, prefix: Number(prefix), gateway, dns: dnsList });
      toast.success(t("netcfg.toast_sent"));
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSubmitting(false); }
  };

  const confirm = async () => {
    setConfirming(true);
    try {
      await api.post("/system/network/confirm");
      toast.success(t("netcfg.toast_confirmed"));
      load();
    } catch { toast.error(t("netcfg.toast_confirm_failed")); }
    finally { setConfirming(false); }
  };

  if (loading) return <div className="p-8 text-muted-foreground">{t("common.loading")}</div>;

  const pending = status?.pending_confirm;

  return (
    <div className="p-4 space-y-4 max-w-3xl mx-auto" data-testid="network-config-page">
      <div className="border-b border-border pb-3">
        <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-1">{t("netcfg.section_label")}</div>
        <h1 className="font-head font-black text-2xl tracking-tight">{t("netcfg.title")}</h1>
      </div>

      <div className="border border-[#FF3333]/50 bg-[#FF3333]/10 p-3 text-sm flex items-start gap-2">
        <ShieldAlert size={16} className="text-[#FF3333] shrink-0 mt-0.5" />
        <div>
          <span className="font-medium text-[#FF3333]">{t("netcfg.warning_label")} </span>
          {t("netcfg.warning_body_prefix")} <strong>{t("netcfg.warning_body_bold")}</strong> {t("netcfg.warning_body_suffix")}
        </div>
      </div>

      {!status?.available ? (
        <div className="border border-border bg-card p-4 text-sm text-muted-foreground flex items-start gap-2">
          <AlertTriangle size={16} className="shrink-0 mt-0.5" />
          <div>
            {status?.error || t("netcfg.unavailable")}
            <div className="text-xs mt-1">{t("netcfg.requires_host_timer")} <span className="mono">mgvms-network-watch</span> {t("netcfg.requires_host_timer_suffix")}</div>
          </div>
        </div>
      ) : (
        <>
          {pending && (
            <div className="border border-[#FFB800]/50 bg-[#FFB800]/10 p-3 text-sm flex items-center justify-between gap-3">
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} className="text-[#FFB800] shrink-0 mt-0.5" />
                <div>
                  <div className="font-medium text-[#FFB800]">{t("netcfg.pending_title")}</div>
                  <div className="text-muted-foreground">{t("netcfg.pending_body_prefix")} <span className="mono">{Math.max(0, pending.seconds_remaining)}s</span> {t("netcfg.pending_body_suffix")}</div>
                </div>
              </div>
              <button onClick={confirm} disabled={confirming}
                      className="flex items-center gap-2 px-4 py-2 bg-[#00E676] text-black text-sm font-medium shrink-0">
                {confirming ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} {t("common.confirm")}
              </button>
            </div>
          )}

          <div className="bg-card border border-border p-4">
            <div className="flex items-center gap-2 border-b border-border pb-2 mb-3">
              <Wifi size={14} className="text-[#0044FF]" />
              <h2 className="font-head font-black text-sm tracking-tight">{t("netcfg.current_state")}</h2>
              <button onClick={load} className="ml-auto p-1 hover:bg-secondary" title={t("netcfg.refresh")}><RefreshCw size={13} /></button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div><div className="text-[10px] uppercase text-muted-foreground">Interface</div><span className="mono">{status.current?.interface || "—"}</span></div>
              <div><div className="text-[10px] uppercase text-muted-foreground">{t("netcfg.method")}</div>{status.current?.method === "manual" ? t("netcfg.static") : "DHCP"}</div>
              <div><div className="text-[10px] uppercase text-muted-foreground">{t("net.ip")}</div><span className="mono">{status.current?.ip || "—"}/{status.current?.prefix ?? "—"}</span></div>
              <div><div className="text-[10px] uppercase text-muted-foreground">{t("netcfg.gateway")}</div><span className="mono">{status.current?.gateway || "—"}</span></div>
              <div className="col-span-2 md:col-span-4"><div className="text-[10px] uppercase text-muted-foreground">DNS</div><span className="mono">{(status.current?.dns || []).join(", ") || "—"}</span></div>
            </div>
          </div>

          {/* v3.54 · Bloc "État des conteneurs" déplacé ici depuis Suivi des
              performances → Debug (demande explicite) — vue seule (mêmes
              données que là-bas, pas de duplication de logique), plus à sa
              place à côté du reste de l'état réseau/machine. */}
          <ContainerStatusPanel />

          <form onSubmit={submit} className="bg-card border border-border p-4 space-y-3">
            <h2 className="font-head font-black text-sm tracking-tight border-b border-border pb-2 mb-1">{t("common.edit")}</h2>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex items-center gap-2 border border-border p-2.5 cursor-pointer">
                <input type="radio" checked={method === "auto"} onChange={() => setMethod("auto")} /> {t("netcfg.dhcp_auto")}
              </label>
              <label className="flex items-center gap-2 border border-border p-2.5 cursor-pointer">
                <input type="radio" checked={method === "manual"} onChange={() => setMethod("manual")} /> {t("netcfg.static")}
              </label>
            </div>
            {method === "manual" && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Field label={t("net.ip")}><input value={ip} onChange={(e) => setIp(e.target.value)} placeholder="192.168.1.50" className="inp mono text-xs" required /></Field>
                <Field label={t("netcfg.prefix_cidr")}><input type="number" min={1} max={32} value={prefix} onChange={(e) => setPrefix(e.target.value)} className="inp mono text-xs" required /></Field>
                <Field label={t("netcfg.gateway")}><input value={gateway} onChange={(e) => setGateway(e.target.value)} placeholder="192.168.1.1" className="inp mono text-xs" required /></Field>
                <Field label={t("netcfg.dns_field_label")}><input value={dns} onChange={(e) => setDns(e.target.value)} placeholder="1.1.1.1, 8.8.8.8" className="inp mono text-xs" /></Field>
              </div>
            )}
            <div className="flex justify-end pt-2 border-t border-border">
              <button type="submit" disabled={submitting || !!pending}
                      className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
                {submitting && <Loader2 size={14} className="animate-spin" />} {t("netcfg.apply_button")}
              </button>
            </div>
          </form>
        </>
      )}
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}
