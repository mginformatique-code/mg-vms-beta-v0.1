/**
 * MfaCenter.jsx — v0.5.5.b
 *
 * Page dédiée à la gestion MFA / 2FA. Auparavant intégrée en tant que
 * simple Card dans /settings, promue en page complète accessible depuis
 * le sous-menu « Centre de sécurité → MFA ».
 *
 * Fonctionnalités :
 *  - État actuel (activée / désactivée) + badge visuel
 *  - Assistant 3 étapes : Scanner QR code → Saisir le code → Confirmer
 *  - Affichage du secret TOTP en clair (pour saisie manuelle)
 *  - Désactivation avec confirmation
 *  - Explications pédagogiques (pourquoi activer, apps recommandées, etc.)
 */
import React, { useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import {
  ShieldCheck, ShieldOff, Smartphone, Copy, CheckCircle2, AlertTriangle,
  QrCode, Info, Lock, RefreshCw, Loader2,
} from "lucide-react";

export default function MfaCenter() {
  const { user, setUser } = useApp();
  const [setup, setSetup] = useState(null);   // {otpauth_uri, secret}
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/2fa/setup");
      setSetup(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally { setLoading(false); }
  };
  const verify = async () => {
    if (!code || code.length < 6) { toast.error("Entrez un code à 6 chiffres"); return; }
    setBusy(true);
    try {
      await api.post("/auth/2fa/verify", { code });
      toast.success("MFA activée avec succès");
      setUser({ ...user, twofa_enabled: true });
      setSetup(null); setCode("");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally { setBusy(false); }
  };
  const disable = async () => {
    if (!window.confirm("Désactiver la MFA ? La sécurité du compte sera réduite.")) return;
    setBusy(true);
    try {
      await api.post("/auth/2fa/disable");
      toast.success("MFA désactivée");
      setUser({ ...user, twofa_enabled: false });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally { setBusy(false); }
  };
  const copySecret = async () => {
    if (!setup?.secret) return;
    try {
      await navigator.clipboard.writeText(setup.secret);
      toast.success("Secret copié");
    } catch (_) { toast.error("Copie impossible"); }
  };

  const enabled = !!user?.twofa_enabled;

  return (
    <div className="p-6 max-w-4xl mx-auto" data-testid="mfa-center-page">
      {/* ─── Header ─── */}
      <div className="flex items-center gap-3 mb-6">
        <ShieldCheck size={26} className="text-[#0044FF]" />
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight">Authentification à deux facteurs</h1>
          <p className="text-xs text-muted-foreground">Renforcez la sécurité de votre compte avec un code TOTP</p>
        </div>
      </div>

      {/* ─── Status Card ─── */}
      <div className={`border p-5 mb-4 flex items-center gap-4 ${enabled ? "border-[#00E676]/40 bg-[#00E676]/5" : "border-[#FFB800]/40 bg-[#FFB800]/5"}`}
           data-testid="mfa-status-card">
        {enabled ? <ShieldCheck size={32} className="text-[#00E676]" /> : <ShieldOff size={32} className="text-[#FFB800]" />}
        <div className="flex-1">
          <div className="text-lg font-semibold">
            {enabled ? "MFA activée" : "MFA désactivée"}
          </div>
          <div className="text-xs text-muted-foreground">
            {enabled
              ? "Un code temporaire à 6 chiffres sera demandé à chaque connexion."
              : "Votre compte n'est protégé que par un mot de passe. L'activation de la MFA est fortement recommandée."}
          </div>
        </div>
        {enabled && (
          <button onClick={disable} disabled={busy}
            className="px-4 py-2 border border-[#FF3333] text-[#FF3333] text-sm hover:bg-[#FF3333]/10 flex items-center gap-2"
            data-testid="mfa-disable-btn">
            {busy && <Loader2 size={14} className="animate-spin" />}
            Désactiver la MFA
          </button>
        )}
      </div>

      {/* ─── Setup Flow ─── */}
      {!enabled && (
        <div className="border border-border p-5 mb-4 bg-card">
          <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-4 flex items-center gap-2">
            <QrCode size={14} /> Assistant d&apos;activation
          </div>

          {!setup ? (
            <div className="space-y-4">
              <StepRow n={1} title="Installez une app d'authentification">
                <div className="text-xs text-muted-foreground mb-1">
                  Applications recommandées :
                </div>
                <div className="flex flex-wrap gap-2 text-xs mono">
                  {["Google Authenticator", "Microsoft Authenticator", "Authy", "1Password", "Bitwarden"].map((a) => (
                    <span key={a} className="px-2 py-1 border border-border">{a}</span>
                  ))}
                </div>
              </StepRow>
              <StepRow n={2} title="Générez votre QR code sécurisé">
                <p className="text-xs text-muted-foreground">
                  Un secret unique lié à votre compte va être créé. Il ne quittera jamais ce serveur en clair.
                </p>
              </StepRow>
              <StepRow n={3} title="Validez avec un code TOTP">
                <p className="text-xs text-muted-foreground">
                  Votre app générera un code à 6 chiffres qui change toutes les 30 secondes.
                </p>
              </StepRow>
              <button onClick={start} disabled={loading}
                className="mt-2 px-5 py-2.5 bg-[#0044FF] text-white text-sm flex items-center gap-2 hover:bg-[#0033cc]"
                data-testid="mfa-start-btn">
                {loading && <Loader2 size={15} className="animate-spin" />}
                <ShieldCheck size={16} /> Démarrer l&apos;activation
              </button>
            </div>
          ) : (
            <div className="space-y-5" data-testid="mfa-setup-panel">
              <StepRow n={1} title="Scannez ce QR code avec votre app">
                <div className="flex items-start gap-5 mt-2">
                  <img src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(setup.otpauth_uri)}`}
                       alt="QR code MFA" className="bg-white p-2 border border-border" data-testid="mfa-qr-img" />
                  <div className="flex-1 space-y-2">
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Ou saisie manuelle du secret</div>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 px-2 py-1.5 bg-muted text-[11px] mono break-all border border-border" data-testid="mfa-secret-value">{setup.secret}</code>
                      <button onClick={copySecret} className="px-2 py-1.5 border border-border hover:bg-secondary" title="Copier">
                        <Copy size={14} />
                      </button>
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      Type: TOTP · Algo: SHA-1 · Chiffres: 6 · Période: 30s
                    </p>
                  </div>
                </div>
              </StepRow>

              <StepRow n={2} title="Entrez le code à 6 chiffres généré par l'app">
                <div className="flex items-center gap-2 mt-1">
                  <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                         data-testid="mfa-code-input" placeholder="000000" inputMode="numeric" autoFocus
                         className="px-4 py-2 bg-background border border-input outline-none mono tracking-[0.35em] text-center w-40 text-lg focus:border-[#0044FF]" />
                  <button onClick={verify} disabled={busy || code.length < 6}
                    className="px-5 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2 disabled:opacity-40"
                    data-testid="mfa-verify-btn">
                    {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                    Confirmer
                  </button>
                  <button onClick={() => { setSetup(null); setCode(""); }}
                    className="px-3 py-2 border border-border text-xs hover:bg-secondary">
                    Annuler
                  </button>
                </div>
              </StepRow>
            </div>
          )}
        </div>
      )}

      {/* ─── Info block ─── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <InfoBlock icon={Lock} title="Pourquoi activer ?">
          Un mot de passe volé ne suffit plus à accéder à votre compte : un
          second code temporaire, généré uniquement sur votre téléphone, est
          également requis.
        </InfoBlock>
        <InfoBlock icon={Smartphone} title="Perte du téléphone ?">
          Un administrateur peut désactiver la MFA depuis la gestion des
          utilisateurs après vérification d&apos;identité. Pensez à conserver le
          secret dans un gestionnaire de mots de passe.
        </InfoBlock>
        <InfoBlock icon={AlertTriangle} title="Bonnes pratiques">
          Utilisez une app open-source (Authy, Bitwarden). Ne partagez jamais
          le QR code ni le secret. Activez la MFA également pour vos comptes
          admin et OS.
        </InfoBlock>
      </div>
    </div>
  );
}

function StepRow({ n, title, children }) {
  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 shrink-0 rounded-full bg-[#0044FF] text-white text-xs font-bold flex items-center justify-center mono">
        {n}
      </div>
      <div className="flex-1">
        <div className="text-sm font-medium mb-1">{title}</div>
        {children}
      </div>
    </div>
  );
}

function InfoBlock({ icon: Icon, title, children }) {
  return (
    <div className="border border-border p-4 bg-card">
      <div className="flex items-center gap-2 text-xs uppercase tracking-widest text-muted-foreground mb-2">
        <Icon size={13} /> {title}
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">{children}</p>
    </div>
  );
}
