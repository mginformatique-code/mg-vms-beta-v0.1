import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { Building2, Loader2, ShieldCheck, Unplug, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";

/**
 * MgvmsCenterSettings — Réglages > MG-VMS Center (v3.49).
 *
 * MG-VMS Center est un service SÉPARÉ hébergé par MG Informatique qui
 * centralise l'état de tous les déploiements clients. La connexion se
 * fait ici en un assistant guidé (URL -> login -> MFA -> choix du
 * tenant) plutôt que par copier-coller manuel d'une clé API dans un
 * fichier .env. Le site ne se choisit jamais ici : ce MG-VMS gère déjà
 * ses propres sites en interne, ils apparaîtront automatiquement dans
 * MG-VMS Center au premier rapport envoyé.
 *
 * Restriction volontaire : le login+MFA exigés sont ceux de MG-VMS
 * Center lui-même, qui n'a de comptes que pour le personnel MG
 * Informatique — un client final ne peut donc jamais se connecter seul,
 * cet assistant nécessite la présence (sur place ou à distance) de
 * quelqu'un chez MG Informatique.
 */
const Inp = (p) => <input {...p} className="w-full px-3 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]" />;
const Sel = (p) => <select {...p} className="w-full px-3 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]" />;
const Lbl = ({ children }) => <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{children}</label>;

function fmtDateTime(unixOrIso) {
  if (!unixOrIso) return "—";
  try {
    const d = typeof unixOrIso === "number" ? new Date(unixOrIso * 1000) : new Date(unixOrIso);
    return d.toLocaleString("fr-FR");
  } catch { return "—"; }
}

export default function MgvmsCenterSettings() {
  const [status, setStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);

  // Assistant : idle | login | mfa | pairing
  const [step, setStep] = useState("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [url, setUrl] = useState("https://center.mginformatique.com");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState(null);
  const [code, setCode] = useState("");

  const [pairingToken, setPairingToken] = useState(null);
  const [tenants, setTenants] = useState([]);
  const [tenantChoice, setTenantChoice] = useState(""); // "" = nouveau
  const [newTenantName, setNewTenantName] = useState("");
  const [label, setLabel] = useState("");

  const loadStatus = () => {
    api.get("/mgvms-center/status").then((r) => setStatus(r.data)).catch(() => {}).finally(() => setLoadingStatus(false));
  };
  useEffect(() => { loadStatus(); }, []);

  const reset = () => {
    setStep("idle"); setError(null); setPassword(""); setCode("");
    setMfaToken(null); setPairingToken(null);
  };

  const submitLogin = async (e) => {
    e.preventDefault();
    setError(null); setBusy(true);
    try {
      const { data } = await api.post("/mgvms-center/connect/login", { url, email, password });
      setMfaToken(data.mfa_token);
      setStep("mfa");
    } catch (e) {
      setError(e.response?.data?.detail || "Échec de connexion");
    } finally { setBusy(false); }
  };

  const submitMfa = async (e) => {
    e.preventDefault();
    setError(null); setBusy(true);
    try {
      const { data } = await api.post("/mgvms-center/connect/mfa-verify", { url, mfa_token: mfaToken, code });
      setPairingToken(data.pairing_token);
      setTenants(data.tenants || []);
      setLabel(`${window.location.hostname} - MG-VMS`);
      setStep("pairing");
    } catch (e) {
      setError(e.response?.data?.detail || "Code invalide");
    } finally { setBusy(false); }
  };

  const submitPairing = async (e) => {
    e.preventDefault();
    setError(null); setBusy(true);
    try {
      await api.post("/mgvms-center/connect/finish", {
        url, pairing_token: pairingToken,
        tenant_id: tenantChoice || null, new_tenant_name: tenantChoice ? null : newTenantName,
        label,
      });
      toast.success("Connecté à MG-VMS Center");
      reset();
      loadStatus();
    } catch (e) {
      setError(e.response?.data?.detail || "Échec de la connexion");
    } finally { setBusy(false); }
  };

  const disconnect = async () => {
    if (!window.confirm("Déconnecter ce MG-VMS de MG-VMS Center ?")) return;
    try {
      await api.post("/mgvms-center/disconnect");
      toast.success("Déconnecté");
      loadStatus();
    } catch { toast.error("Échec de la déconnexion"); }
  };

  return (
    <div className="p-4 max-w-2xl" data-testid="mgvms-center-page">
      <div className="mb-5">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Building2 size={22} className="text-[#0044FF]" /> MG-VMS Center
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Connecte ce déploiement au tableau de bord central MG Informatique — suivi de version, alerte de mise à jour.
        </p>
      </div>

      {loadingStatus ? (
        <Loader2 size={16} className="animate-spin text-muted-foreground" />
      ) : status?.connected ? (
        <div className="bg-card border border-border p-5" data-testid="mgvms-center-connected">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 size={16} className="text-[#00E676]" />
            <span className="font-medium">Connecté à MG-VMS Center</span>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm mb-4">
            <div><div className="text-[10px] uppercase text-muted-foreground">URL</div>{status.url}</div>
            <div><div className="text-[10px] uppercase text-muted-foreground">Nom du déploiement</div>{status.label}</div>
            <div><div className="text-[10px] uppercase text-muted-foreground">Dernier rapport envoyé</div>{fmtDateTime(status.last_report_at)}</div>
            <div>
              <div className="text-[10px] uppercase text-muted-foreground">État du dernier envoi</div>
              {status.last_report_ok === false
                ? <span className="text-[#FF3333] flex items-center gap-1"><XCircle size={13} /> Échec</span>
                : <span className="text-[#00E676] flex items-center gap-1"><CheckCircle2 size={13} /> OK</span>}
            </div>
          </div>
          {status.update_available && (
            <div className="border border-[#FFB800]/50 bg-[#FFB800]/10 p-3 text-sm mb-4">
              Mise à jour disponible : <span className="mono">{status.latest_version}</span>
            </div>
          )}
          <button onClick={disconnect}
                  className="flex items-center gap-2 px-3 py-2 border border-border text-sm hover:bg-secondary text-[#FF3333]">
            <Unplug size={14} /> Déconnecter
          </button>
        </div>
      ) : (
        <div className="bg-card border border-border p-5">
          {step === "idle" && (
            <div>
              <div className="mb-3">
                <Lbl>URL de MG-VMS Center</Lbl>
                <Inp value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://center.mginformatique.com" />
              </div>
              <div className="text-xs text-muted-foreground mb-3 flex items-start gap-2 border border-border p-2.5">
                <ShieldCheck size={14} className="text-muted-foreground shrink-0 mt-0.5" />
                La connexion nécessite un compte MG-VMS Center (personnel MG Informatique uniquement, protégé par mot de passe + MFA).
              </div>
              <button onClick={() => setStep("login")} className="px-4 py-2 bg-[#0044FF] text-white text-sm">
                Se connecter
              </button>
            </div>
          )}

          {step === "login" && (
            <form onSubmit={submitLogin}>
              <div className="mb-3"><Lbl>E-mail (MG-VMS Center)</Lbl><Inp type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus /></div>
              <div className="mb-3"><Lbl>Mot de passe</Lbl><Inp type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
              {error && <div className="text-xs text-[#FF3333] mb-3">{error}</div>}
              <div className="flex gap-2">
                <button type="button" onClick={reset} className="px-3 py-2 border border-border text-sm hover:bg-secondary">Annuler</button>
                <button type="submit" disabled={busy} className="px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
                  {busy ? <Loader2 size={14} className="animate-spin" /> : "Continuer"}
                </button>
              </div>
            </form>
          )}

          {step === "mfa" && (
            <form onSubmit={submitMfa}>
              <div className="mb-3">
                <Lbl>Code MFA à 6 chiffres</Lbl>
                <Inp value={code} inputMode="numeric" maxLength={6}
                     onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required autoFocus />
              </div>
              {error && <div className="text-xs text-[#FF3333] mb-3">{error}</div>}
              <div className="flex gap-2">
                <button type="button" onClick={reset} className="px-3 py-2 border border-border text-sm hover:bg-secondary">Annuler</button>
                <button type="submit" disabled={busy || code.length !== 6} className="px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
                  {busy ? <Loader2 size={14} className="animate-spin" /> : "Valider"}
                </button>
              </div>
            </form>
          )}

          {step === "pairing" && (
            <form onSubmit={submitPairing}>
              <div className="mb-3">
                <Lbl>Tenant (client)</Lbl>
                <Sel value={tenantChoice} onChange={(e) => { setTenantChoice(e.target.value); setSiteChoice(""); }}>
                  <option value="">— créer un nouveau tenant —</option>
                  {tenants.map((tn) => <option key={tn.id} value={tn.id}>{tn.name}</option>)}
                </Sel>
                {!tenantChoice && (
                  <div className="mt-2">
                    <Inp value={newTenantName} onChange={(e) => setNewTenantName(e.target.value)}
                         placeholder="Nom du nouveau tenant" required />
                  </div>
                )}
              </div>
              <div className="text-xs text-muted-foreground mb-3 flex items-start gap-2 border border-border p-2.5">
                <ShieldCheck size={14} className="text-muted-foreground shrink-0 mt-0.5" />
                Les sites de ce déploiement apparaîtront automatiquement dans MG-VMS Center dès le premier rapport — rien à choisir ici.
              </div>
              <div className="mb-3">
                <Lbl>Nom de ce déploiement</Lbl>
                <Inp value={label} onChange={(e) => setLabel(e.target.value)} required />
              </div>
              {error && <div className="text-xs text-[#FF3333] mb-3">{error}</div>}
              <div className="flex gap-2">
                <button type="button" onClick={reset} className="px-3 py-2 border border-border text-sm hover:bg-secondary">Annuler</button>
                <button type="submit" disabled={busy} className="px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
                  {busy ? <Loader2 size={14} className="animate-spin" /> : "Terminer la connexion"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
