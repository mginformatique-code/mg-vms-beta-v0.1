/**
 * TlsSettings.jsx — v0.7.f · Wave G · Centre de sécurité → HTTPS / TLS
 *
 * Page complète pour :
 *   • Domaine local (LAN, intranet) + domaine externe (Internet)
 *   • Options : force HTTPS + HSTS + max-age
 *   • Liste des certificats stockés (statut, expiration, SAN, empreinte)
 *   • Import d'un certificat existant (PEM cert + clé)
 *   • Génération d'un certificat auto-signé (LAN)
 *   • Activation / suppression / export PEM (audité)
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  ShieldCheck, ShieldAlert, ArrowLeft, Globe, Lock, Zap, Upload, KeyRound,
  Sparkles, Trash2, Check, AlertTriangle, Copy, Download, Info, X, RefreshCw,
} from "lucide-react";

// ────────────────────────────────────────────────────────────────
// UI atoms
// ────────────────────────────────────────────────────────────────
const Field = ({ label, hint, children, testid }) => (
  <label className="block" data-testid={testid ? `${testid}-field` : undefined}>
    <span className="block text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1">{label}</span>
    {children}
    {hint && <span className="block text-[10px] text-muted-foreground/70 mt-1">{hint}</span>}
  </label>
);

const Input = React.forwardRef(function Input({ className = "", ...p }, ref) {
  return (
    <input ref={ref} className={`w-full bg-secondary/30 border border-border px-3 py-2 text-sm mono focus:outline-none focus:border-[#0044FF] transition ${className}`} {...p} />
  );
});

const Btn = ({ variant = "primary", children, disabled, className = "", ...p }) => {
  const base = "inline-flex items-center gap-2 px-3 py-2 text-xs font-medium tracking-wide border transition disabled:opacity-40 disabled:cursor-not-allowed";
  const styles = {
    primary: "bg-[#0044FF] hover:bg-[#0033CC] text-white border-[#0044FF]",
    ghost: "bg-transparent border-border hover:bg-secondary/50 text-foreground",
    danger: "bg-transparent border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10",
    ok: "bg-[#00E676]/10 border-[#00E676] text-[#00E676] hover:bg-[#00E676]/20",
  };
  return <button disabled={disabled} className={`${base} ${styles[variant] || styles.primary} ${className}`} {...p}>{children}</button>;
};

const Badge = ({ tone = "muted", children, ...p }) => {
  const toneMap = {
    ok: "text-[#00E676] border-[#00E676]/40 bg-[#00E676]/10",
    warn: "text-[#FFB800] border-[#FFB800]/40 bg-[#FFB800]/10",
    err: "text-[#FF3333] border-[#FF3333]/40 bg-[#FF3333]/10",
    muted: "text-muted-foreground border-border bg-secondary/40",
    info: "text-[#0044FF] border-[#0044FF]/40 bg-[#0044FF]/10",
  };
  return <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] mono uppercase tracking-wide border ${toneMap[tone] || toneMap.muted}`} {...p}>{children}</span>;
};

// ────────────────────────────────────────────────────────────────
// Sections
// ────────────────────────────────────────────────────────────────
function DomainsPanel({ config, onSave }) {
  const [d, setD] = useState(config.domains);
  useEffect(() => setD(config.domains), [config.domains]);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try { await onSave(d); toast.success("Domaines enregistrés"); }
    catch (e) { toast.error(e.response?.data?.detail?.error || "Erreur enregistrement"); }
    finally { setSaving(false); }
  };

  return (
    <div className="bg-card border border-border p-4 space-y-4" data-testid="tls-domains-panel">
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <Globe size={14} className="text-[#0044FF]" />
        <h2 className="font-head font-black text-sm tracking-tight">Domaines & routing</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label="Domaine local (LAN / intranet)" hint="Ex : mgvms.local · résolu par mDNS ou DNS interne" testid="tls-domain-internal">
          <Input value={d.internal} onChange={(e) => setD({ ...d, internal: e.target.value })}
                 placeholder="mgvms.local" data-testid="tls-domain-internal-input" />
        </Field>
        <Field label="Domaine externe (Internet public)" hint="Ex : vms.exemple.com · requis pour Let's Encrypt" testid="tls-domain-external">
          <Input value={d.external} onChange={(e) => setD({ ...d, external: e.target.value })}
                 placeholder="vms.exemple.com" data-testid="tls-domain-external-input" />
        </Field>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <label className="flex items-start gap-2 cursor-pointer border border-border p-2 hover:bg-secondary/40" data-testid="tls-toggle-force-https">
          <input type="checkbox" checked={d.force_https} onChange={(e) => setD({ ...d, force_https: e.target.checked })} className="mt-0.5" />
          <div>
            <div className="text-sm font-medium">Forcer HTTPS</div>
            <div className="text-[10px] text-muted-foreground">Redirige tout HTTP → HTTPS</div>
          </div>
        </label>
        <label className="flex items-start gap-2 cursor-pointer border border-border p-2 hover:bg-secondary/40" data-testid="tls-toggle-hsts">
          <input type="checkbox" checked={d.hsts_enabled} onChange={(e) => setD({ ...d, hsts_enabled: e.target.checked })} className="mt-0.5" />
          <div>
            <div className="text-sm font-medium">HSTS</div>
            <div className="text-[10px] text-muted-foreground">Strict-Transport-Security header</div>
          </div>
        </label>
        <Field label="HSTS max-age (secondes)" hint="180 j = 15552000 · max 2 ans" testid="tls-hsts-maxage">
          <Input type="number" min="0" max="63072000" value={d.hsts_max_age_seconds}
                 onChange={(e) => setD({ ...d, hsts_max_age_seconds: parseInt(e.target.value, 10) || 0 })}
                 disabled={!d.hsts_enabled} data-testid="tls-hsts-maxage-input" />
        </Field>
      </div>

      <div className="flex justify-end pt-2 border-t border-border">
        <Btn onClick={save} disabled={saving} data-testid="tls-domains-save">
          {saving ? "Enregistrement…" : (<><Check size={13} /> Enregistrer</>)}
        </Btn>
      </div>
    </div>
  );
}

function CertificateRow({ cert, onActivate, onDelete, onExport }) {
  const badge = cert.expired
    ? <Badge tone="err"><AlertTriangle size={10}/> Expiré</Badge>
    : cert.days_left < 30
      ? <Badge tone="warn"><AlertTriangle size={10}/> {cert.days_left} j restants</Badge>
      : <Badge tone="ok">{cert.days_left} j</Badge>;

  return (
    <div className={`border ${cert.active ? "border-[#00E676] bg-[#00E676]/5" : "border-border bg-card"} p-3`}
         data-testid={`tls-cert-row-${cert.id}`}>
      <div className="flex items-start gap-3">
        <div className="mt-1">
          {cert.active ? <ShieldCheck size={20} className="text-[#00E676]" /> : <Lock size={20} className="text-muted-foreground" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm truncate">{cert.name}</span>
            {cert.active && <Badge tone="ok"><Check size={10}/> Actif</Badge>}
            {cert.self_signed && <Badge tone="warn">Auto-signé</Badge>}
            {cert.source === "uploaded" && <Badge tone="info">Importé</Badge>}
            {cert.source === "self-signed" && <Badge tone="muted"><Sparkles size={10}/> Généré</Badge>}
            {badge}
          </div>
          <div className="text-xs text-muted-foreground mt-1 mono truncate" title={cert.common_name}>
            <span className="opacity-60">CN :</span> {cert.common_name || "—"}
          </div>
          {cert.sans?.length > 0 && (
            <div className="text-[10px] text-muted-foreground mt-0.5 mono truncate" title={cert.sans.join(", ")}>
              <span className="opacity-60">SAN :</span> {cert.sans.join(", ")}
            </div>
          )}
          <div className="text-[10px] text-muted-foreground mt-0.5 mono truncate" title={cert.fingerprint_sha256}>
            <span className="opacity-60">SHA-256 :</span> {cert.fingerprint_sha256?.slice(0, 24)}…{cert.fingerprint_sha256?.slice(-8)}
          </div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            <span className="opacity-60">Valide du</span> {new Date(cert.not_before).toLocaleDateString("fr-FR")}
            <span className="opacity-60"> au</span> {new Date(cert.not_after).toLocaleDateString("fr-FR")}
          </div>
        </div>
        <div className="flex flex-col gap-1 shrink-0">
          {!cert.active && (
            <Btn variant="ok" onClick={() => onActivate(cert)} data-testid={`tls-cert-activate-${cert.id}`}>
              <ShieldCheck size={12}/> Activer
            </Btn>
          )}
          <Btn variant="ghost" onClick={() => onExport(cert)} data-testid={`tls-cert-export-${cert.id}`}>
            <Download size={12}/> Exporter
          </Btn>
          {!cert.active && (
            <Btn variant="danger" onClick={() => onDelete(cert)} data-testid={`tls-cert-delete-${cert.id}`}>
              <Trash2 size={12}/> Supprimer
            </Btn>
          )}
        </div>
      </div>
    </div>
  );
}

function CertificatesPanel({ config, onReload }) {
  const onActivate = async (cert) => {
    try { await api.put(`/security/tls/certificates/${cert.id}/activate`); toast.success(`« ${cert.name} » activé`); onReload(); }
    catch (e) { toast.error(e.response?.data?.detail?.error || "Échec activation"); }
  };
  const onDelete = async (cert) => {
    if (!window.confirm(`Supprimer définitivement « ${cert.name} » ?`)) return;
    try { await api.delete(`/security/tls/certificates/${cert.id}`); toast.success("Supprimé"); onReload(); }
    catch (e) { toast.error(e.response?.data?.detail?.message || e.response?.data?.detail?.error || "Échec suppression"); }
  };
  const onExport = async (cert) => {
    const includeKey = window.confirm(`Exporter aussi la clé privée ?\n\nOK = cert + clé (audité, sensible)\nAnnuler = cert seul (public)`);
    try {
      const r = await api.get(`/security/tls/certificates/${cert.id}/pem`, { params: { include_key: includeKey } });
      const bundle = includeKey ? `${r.data.cert_pem}\n${r.data.key_pem}` : r.data.cert_pem;
      const blob = new Blob([bundle], { type: "application/x-pem-file" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${cert.name.replace(/\W+/g, "_")}${includeKey ? "_full" : "_cert"}.pem`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast.success("Téléchargement démarré");
    } catch (e) { toast.error("Échec export"); }
  };

  const certs = config.certificates || [];
  return (
    <div className="bg-card border border-border p-4 space-y-3" data-testid="tls-certificates-panel">
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <Lock size={14} className="text-[#0044FF]" />
        <h2 className="font-head font-black text-sm tracking-tight">Certificats stockés <span className="text-muted-foreground mono ml-1">({certs.length})</span></h2>
        <button onClick={onReload} className="ml-auto text-xs text-muted-foreground hover:text-foreground flex items-center gap-1" data-testid="tls-certs-refresh">
          <RefreshCw size={11} /> Recharger
        </button>
      </div>
      {certs.length === 0 ? (
        <div className="text-xs text-muted-foreground text-center py-8" data-testid="tls-certs-empty">
          Aucun certificat stocké. Importe un cert existant ou génère un auto-signé ci-dessous.
        </div>
      ) : (
        <div className="space-y-2">
          {certs.map((c) => (
            <CertificateRow key={c.id} cert={c} onActivate={onActivate} onDelete={onDelete} onExport={onExport} />
          ))}
        </div>
      )}
    </div>
  );
}

function UploadCertPanel({ onCreated }) {
  const [name, setName] = useState("");
  const [certPem, setCertPem] = useState("");
  const [keyPem, setKeyPem] = useState("");
  const [activate, setActivate] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name || !certPem || !keyPem) return toast.error("Nom + cert + clé requis");
    setBusy(true);
    try {
      await api.post("/security/tls/certificates/upload", {
        name, cert_pem: certPem, key_pem: keyPem, activate,
      });
      toast.success("Certificat importé");
      setName(""); setCertPem(""); setKeyPem(""); setActivate(false);
      onCreated();
    } catch (e) {
      toast.error(e.response?.data?.detail?.error || e.response?.data?.detail?.message || "Échec import");
    } finally { setBusy(false); }
  };

  const readFile = (setter) => (e) => {
    const f = e.target.files?.[0]; if (!f) return;
    const rd = new FileReader();
    rd.onload = () => setter(String(rd.result || ""));
    rd.readAsText(f);
  };

  return (
    <div className="bg-card border border-border p-4 space-y-3" data-testid="tls-upload-panel">
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <Upload size={14} className="text-[#0044FF]" />
        <h2 className="font-head font-black text-sm tracking-tight">Importer un certificat existant</h2>
      </div>
      <div className="text-xs text-muted-foreground flex items-start gap-1">
        <Info size={11} className="mt-0.5 shrink-0" />
        Colle le PEM du certificat public + celui de la clé privée. Ex : sortie <span className="mono">Let&apos;s Encrypt</span> (fichiers <span className="mono">fullchain.pem</span> + <span className="mono">privkey.pem</span>).
      </div>

      <Field label="Nom convivial" testid="tls-upload-name">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex : Let's Encrypt vms.exemple.com" data-testid="tls-upload-name-input" />
      </Field>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label="Certificat public (fullchain.pem)" testid="tls-upload-cert">
          <textarea value={certPem} onChange={(e) => setCertPem(e.target.value)}
                     rows={7} placeholder="-----BEGIN CERTIFICATE-----&#10;…&#10;-----END CERTIFICATE-----"
                     className="w-full bg-secondary/30 border border-border px-3 py-2 text-[11px] mono font-mono focus:outline-none focus:border-[#0044FF]" data-testid="tls-upload-cert-input" />
          <input type="file" accept=".pem,.crt,.cer" onChange={readFile(setCertPem)} className="text-[10px] mt-1" data-testid="tls-upload-cert-file" />
        </Field>
        <Field label="Clé privée (privkey.pem)" testid="tls-upload-key">
          <textarea value={keyPem} onChange={(e) => setKeyPem(e.target.value)}
                     rows={7} placeholder="-----BEGIN PRIVATE KEY-----&#10;…&#10;-----END PRIVATE KEY-----"
                     className="w-full bg-secondary/30 border border-border px-3 py-2 text-[11px] mono font-mono focus:outline-none focus:border-[#0044FF]" data-testid="tls-upload-key-input" />
          <input type="file" accept=".pem,.key" onChange={readFile(setKeyPem)} className="text-[10px] mt-1" data-testid="tls-upload-key-file" />
        </Field>
      </div>
      <div className="flex items-center justify-between pt-2 border-t border-border">
        <label className="flex items-center gap-2 text-xs cursor-pointer" data-testid="tls-upload-activate-toggle">
          <input type="checkbox" checked={activate} onChange={(e) => setActivate(e.target.checked)} /> Activer immédiatement
        </label>
        <Btn onClick={submit} disabled={busy} data-testid="tls-upload-submit">
          {busy ? "Import…" : (<><Upload size={12}/> Importer</>)}
        </Btn>
      </div>
    </div>
  );
}

function SelfSignedPanel({ onCreated, defaultDomain }) {
  const [name, setName] = useState("Auto-signé LAN");
  const [cn, setCn] = useState(defaultDomain || "mgvms.local");
  const [sansTxt, setSansTxt] = useState("*.mgvms.local");
  const [org, setOrg] = useState("MG-VMS");
  const [country, setCountry] = useState("FR");
  const [days, setDays] = useState(365);
  const [keyBits, setKeyBits] = useState(2048);
  const [activate, setActivate] = useState(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (defaultDomain) setCn(defaultDomain); }, [defaultDomain]);

  const submit = async () => {
    if (!name || !cn) return toast.error("Nom + Common Name requis");
    setBusy(true);
    const sans = sansTxt.split(/[\s,;\n]+/).map((s) => s.trim()).filter(Boolean);
    try {
      await api.post("/security/tls/certificates/self-signed", {
        name, common_name: cn, sans, organization: org,
        country: country.slice(0, 2).toUpperCase(),
        validity_days: days, key_bits: keyBits, activate,
      });
      toast.success("Certificat auto-signé généré");
      onCreated();
    } catch (e) {
      toast.error(e.response?.data?.detail?.error || "Échec génération");
    } finally { setBusy(false); }
  };

  return (
    <div className="bg-card border border-border p-4 space-y-3" data-testid="tls-selfsigned-panel">
      <div className="flex items-center gap-2 border-b border-border pb-2">
        <Sparkles size={14} className="text-[#FFB800]" />
        <h2 className="font-head font-black text-sm tracking-tight">Générer un certificat auto-signé</h2>
      </div>
      <div className="text-xs text-muted-foreground flex items-start gap-1">
        <AlertTriangle size={11} className="mt-0.5 shrink-0 text-[#FFB800]" />
        Recommandé pour <b className="text-foreground">LAN / intranet uniquement</b>. Les navigateurs afficheront un avertissement tant que le cert n&apos;est pas ajouté aux <span className="mono">trust stores</span> clients.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Field label="Nom convivial" testid="tls-ss-name">
          <Input value={name} onChange={(e) => setName(e.target.value)} data-testid="tls-ss-name-input" />
        </Field>
        <Field label="Common Name (CN)" hint="Le domaine principal — doit correspondre à l'hôte" testid="tls-ss-cn">
          <Input value={cn} onChange={(e) => setCn(e.target.value)} placeholder="mgvms.local" data-testid="tls-ss-cn-input" />
        </Field>
      </div>
      <Field label="Subject Alternative Names (SAN)" hint="Domaines & IPs supplémentaires — un par ligne ou séparés par virgules. Wildcard supporté (*.mgvms.local)" testid="tls-ss-sans">
        <textarea value={sansTxt} onChange={(e) => setSansTxt(e.target.value)} rows={3}
                   placeholder="*.mgvms.local, 192.168.1.10"
                   className="w-full bg-secondary/30 border border-border px-3 py-2 text-[12px] mono focus:outline-none focus:border-[#0044FF]" data-testid="tls-ss-sans-input" />
      </Field>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Field label="Organisation (O)" testid="tls-ss-org">
          <Input value={org} onChange={(e) => setOrg(e.target.value)} data-testid="tls-ss-org-input" />
        </Field>
        <Field label="Pays (2 lettres)" testid="tls-ss-country">
          <Input value={country} onChange={(e) => setCountry(e.target.value)} maxLength={2} data-testid="tls-ss-country-input" />
        </Field>
        <Field label="Validité (jours)" hint="1 - 3650" testid="tls-ss-days">
          <Input type="number" min="1" max="3650" value={days} onChange={(e) => setDays(parseInt(e.target.value, 10) || 365)} data-testid="tls-ss-days-input" />
        </Field>
        <Field label="Taille clé RSA (bits)" testid="tls-ss-keybits">
          <select value={keyBits} onChange={(e) => setKeyBits(parseInt(e.target.value, 10))}
                  className="w-full bg-secondary/30 border border-border px-3 py-2 text-sm focus:outline-none focus:border-[#0044FF]" data-testid="tls-ss-keybits-input">
            <option value={2048}>2048 (rapide, standard)</option>
            <option value={3072}>3072</option>
            <option value={4096}>4096 (sécurité max, plus lent)</option>
          </select>
        </Field>
      </div>
      <div className="flex items-center justify-between pt-2 border-t border-border">
        <label className="flex items-center gap-2 text-xs cursor-pointer" data-testid="tls-ss-activate-toggle">
          <input type="checkbox" checked={activate} onChange={(e) => setActivate(e.target.checked)} /> Activer immédiatement
        </label>
        <Btn variant="primary" onClick={submit} disabled={busy} data-testid="tls-ss-submit">
          {busy ? "Génération…" : (<><Sparkles size={12}/> Générer</>)}
        </Btn>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Page
// ────────────────────────────────────────────────────────────────
export default function TlsSettings() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try { const { data } = await api.get("/security/tls/config"); setConfig(data); }
    catch (e) { toast.error("Impossible de charger les paramètres TLS"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const saveDomains = async (d) => {
    await api.put("/security/tls/domains", d);
    await load();
  };

  if (loading || !config) {
    return <div className="p-8 text-muted-foreground" data-testid="tls-loading">Chargement…</div>;
  }

  const active = config.certificates.find((c) => c.active);
  const nearExpiryCount = config.certificates.filter((c) => c.days_left < 30 && !c.expired).length;
  const expiredCount = config.certificates.filter((c) => c.expired).length;

  return (
    <div className="p-4 space-y-4 max-w-6xl mx-auto" data-testid="tls-settings">
      {/* Header */}
      <div className="flex items-end justify-between border-b border-border pb-3">
        <div className="flex items-center gap-4">
          <Link to="/security-center" className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1" data-testid="tls-back">
            <ArrowLeft size={13}/> Centre de sécurité
          </Link>
          <div>
            <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-1">Sécurité · HTTPS / TLS</div>
            <h1 className="font-head font-black text-3xl tracking-tight">Paramètres HTTPS &amp; certificats</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {active
            ? <Badge tone="ok"><ShieldCheck size={11}/> {active.name}</Badge>
            : <Badge tone="warn"><ShieldAlert size={11}/> Aucun certificat actif</Badge>}
          {expiredCount > 0 && <Badge tone="err">{expiredCount} expiré{expiredCount>1?'s':''}</Badge>}
          {nearExpiryCount > 0 && <Badge tone="warn">{nearExpiryCount} expire bientôt</Badge>}
        </div>
      </div>

      {/* Résumé état actuel */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2" data-testid="tls-summary">
        <div className="bg-card border border-border p-3">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1 flex items-center gap-1"><Globe size={11}/> Domaine externe</div>
          <div className="font-mono text-sm truncate">{config.domains.external || <span className="text-muted-foreground italic">(non défini)</span>}</div>
        </div>
        <div className="bg-card border border-border p-3">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1 flex items-center gap-1"><Globe size={11}/> Domaine local</div>
          <div className="font-mono text-sm truncate">{config.domains.internal || <span className="text-muted-foreground italic">(non défini)</span>}</div>
        </div>
        <div className="bg-card border border-border p-3">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1 flex items-center gap-1"><Zap size={11}/> Force HTTPS</div>
          <div className="text-sm">{config.domains.force_https ? <Badge tone="ok">Activé</Badge> : <Badge tone="muted">Désactivé</Badge>}</div>
        </div>
        <div className="bg-card border border-border p-3">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1 flex items-center gap-1"><Lock size={11}/> Let&apos;s Encrypt</div>
          <div className="text-sm">{config.letsencrypt_enabled ? <Badge tone="ok">Détecté</Badge> : <Badge tone="muted">Non configuré</Badge>}</div>
        </div>
      </div>

      {/* Panneaux */}
      <DomainsPanel config={config} onSave={saveDomains} />
      <CertificatesPanel config={config} onReload={load} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <SelfSignedPanel onCreated={load} defaultDomain={config.domains.internal || "mgvms.local"} />
        <UploadCertPanel onCreated={load} />
      </div>

      {/* Guide de bas de page */}
      <div className="bg-secondary/30 border border-border p-4 text-xs text-muted-foreground" data-testid="tls-help">
        <div className="font-medium text-foreground mb-2 flex items-center gap-1"><Info size={12}/> Aide rapide</div>
        <ul className="space-y-1 list-disc list-inside">
          <li><b>LAN uniquement</b> : génère un cert auto-signé avec ton domaine <span className="mono">.local</span> comme CN + ton IP LAN en SAN. Importe-le sur les postes clients.</li>
          <li><b>Production Internet</b> : renseigne le domaine externe, laisse <span className="mono">certbot</span> obtenir un cert Let&apos;s Encrypt (compose <span className="mono">docker-compose.prod.yml</span>), puis importe <span className="mono">fullchain.pem</span> + <span className="mono">privkey.pem</span>.</li>
          <li><b>Force HTTPS + HSTS</b> : à activer <b>seulement</b> après avoir un cert public trusté — un HSTS activé sur cert auto-signé bloque l&apos;accès aux navigateurs.</li>
        </ul>
      </div>
    </div>
  );
}
