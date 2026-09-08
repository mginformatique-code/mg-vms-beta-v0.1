import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { AlertTriangle, ShieldAlert, Wifi, Check, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import ContainerStatusPanel from "./ContainerStatusPanel";

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
    if (!window.confirm(
      "Ceci va modifier l'adresse IP réelle de la machine/VM qui héberge MG-VMS. " +
      "Si la nouvelle configuration est mauvaise, l'accès à cette machine peut être coupé " +
      "(restauration automatique de l'ancienne config dans 90s si non confirmée ici). Continuer ?"
    )) return;
    setSubmitting(true);
    try {
      const dnsList = dns.split(",").map((s) => s.trim()).filter(Boolean);
      await api.put("/system/network", { method, ip, prefix: Number(prefix), gateway, dns: dnsList });
      toast.success("Configuration envoyée — confirmez-la ci-dessous une fois appliquée.");
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSubmitting(false); }
  };

  const confirm = async () => {
    setConfirming(true);
    try {
      await api.post("/system/network/confirm");
      toast.success("Configuration confirmée.");
      load();
    } catch { toast.error("Échec de la confirmation"); }
    finally { setConfirming(false); }
  };

  if (loading) return <div className="p-8 text-muted-foreground">Chargement…</div>;

  const pending = status?.pending_confirm;

  return (
    <div className="p-4 space-y-4 max-w-3xl mx-auto" data-testid="network-config-page">
      <div className="border-b border-border pb-3">
        <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-1">Réseau · Machine</div>
        <h1 className="font-head font-black text-2xl tracking-tight">Paramètres réseau</h1>
      </div>

      <div className="border border-[#FF3333]/50 bg-[#FF3333]/10 p-3 text-sm flex items-start gap-2">
        <ShieldAlert size={16} className="text-[#FF3333] shrink-0 mt-0.5" />
        <div>
          <span className="font-medium text-[#FF3333]">Attention : </span>
          ceci modifie l'adresse IP réelle de la <strong>machine ou VM</strong> qui héberge MG-VMS —
          pas un simple réglage de l'application. Une mauvaise IP/passerelle peut couper l'accès distant
          à cette machine. La nouvelle configuration doit être confirmée ici sous 90s, sinon
          l'ancienne est restaurée automatiquement.
        </div>
      </div>

      {!status?.available ? (
        <div className="border border-border bg-card p-4 text-sm text-muted-foreground flex items-start gap-2">
          <AlertTriangle size={16} className="shrink-0 mt-0.5" />
          <div>
            {status?.error || "Indisponible."}
            <div className="text-xs mt-1">Nécessite le timer hôte <span className="mono">mgvms-network-watch</span> (NetworkManager/nmcli + jq) — voir install.sh.</div>
          </div>
        </div>
      ) : (
        <>
          {pending && (
            <div className="border border-[#FFB800]/50 bg-[#FFB800]/10 p-3 text-sm flex items-center justify-between gap-3">
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} className="text-[#FFB800] shrink-0 mt-0.5" />
                <div>
                  <div className="font-medium text-[#FFB800]">Configuration en attente de confirmation</div>
                  <div className="text-muted-foreground">Restauration automatique de l'ancienne config dans <span className="mono">{Math.max(0, pending.seconds_remaining)}s</span> si non confirmée.</div>
                </div>
              </div>
              <button onClick={confirm} disabled={confirming}
                      className="flex items-center gap-2 px-4 py-2 bg-[#00E676] text-black text-sm font-medium shrink-0">
                {confirming ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Confirmer
              </button>
            </div>
          )}

          <div className="bg-card border border-border p-4">
            <div className="flex items-center gap-2 border-b border-border pb-2 mb-3">
              <Wifi size={14} className="text-[#0044FF]" />
              <h2 className="font-head font-black text-sm tracking-tight">État actuel</h2>
              <button onClick={load} className="ml-auto p-1 hover:bg-secondary" title="Actualiser"><RefreshCw size={13} /></button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div><div className="text-[10px] uppercase text-muted-foreground">Interface</div><span className="mono">{status.current?.interface || "—"}</span></div>
              <div><div className="text-[10px] uppercase text-muted-foreground">Méthode</div>{status.current?.method === "manual" ? "Statique" : "DHCP"}</div>
              <div><div className="text-[10px] uppercase text-muted-foreground">Adresse IP</div><span className="mono">{status.current?.ip || "—"}/{status.current?.prefix ?? "—"}</span></div>
              <div><div className="text-[10px] uppercase text-muted-foreground">Passerelle</div><span className="mono">{status.current?.gateway || "—"}</span></div>
              <div className="col-span-2 md:col-span-4"><div className="text-[10px] uppercase text-muted-foreground">DNS</div><span className="mono">{(status.current?.dns || []).join(", ") || "—"}</span></div>
            </div>
          </div>

          {/* v3.54 · Bloc "État des conteneurs" déplacé ici depuis Suivi des
              performances → Debug (demande explicite) — vue seule (mêmes
              données que là-bas, pas de duplication de logique), plus à sa
              place à côté du reste de l'état réseau/machine. */}
          <ContainerStatusPanel />

          <form onSubmit={submit} className="bg-card border border-border p-4 space-y-3">
            <h2 className="font-head font-black text-sm tracking-tight border-b border-border pb-2 mb-1">Modifier</h2>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex items-center gap-2 border border-border p-2.5 cursor-pointer">
                <input type="radio" checked={method === "auto"} onChange={() => setMethod("auto")} /> DHCP (automatique)
              </label>
              <label className="flex items-center gap-2 border border-border p-2.5 cursor-pointer">
                <input type="radio" checked={method === "manual"} onChange={() => setMethod("manual")} /> Statique
              </label>
            </div>
            {method === "manual" && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Field label="Adresse IP"><input value={ip} onChange={(e) => setIp(e.target.value)} placeholder="192.168.1.50" className="inp mono text-xs" required /></Field>
                <Field label="Préfixe (CIDR)"><input type="number" min={1} max={32} value={prefix} onChange={(e) => setPrefix(e.target.value)} className="inp mono text-xs" required /></Field>
                <Field label="Passerelle"><input value={gateway} onChange={(e) => setGateway(e.target.value)} placeholder="192.168.1.1" className="inp mono text-xs" required /></Field>
                <Field label="DNS (max 4, séparés par virgule)"><input value={dns} onChange={(e) => setDns(e.target.value)} placeholder="1.1.1.1, 8.8.8.8" className="inp mono text-xs" /></Field>
              </div>
            )}
            <div className="flex justify-end pt-2 border-t border-border">
              <button type="submit" disabled={submitting || !!pending}
                      className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
                {submitting && <Loader2 size={14} className="animate-spin" />} Appliquer (confirmation requise sous 90s)
              </button>
            </div>
          </form>
        </>
      )}
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}
