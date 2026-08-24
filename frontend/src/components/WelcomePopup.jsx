import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import Logo from "@/components/Logo";
import LicenseSection from "@/components/LicenseSection";
import {
  X, Lightbulb, Youtube, ListChecks, LifeBuoy, KeyRound, ShieldAlert,
} from "lucide-react";

const DISMISS_KEY = "mg_welcome_dismissed";

function Section({ icon: Icon, title, accent, children }) {
  return (
    <div className="border border-border p-4 bg-background">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] mb-3" style={{ color: accent || undefined }}>
        <Icon size={15} /> {title}
      </div>
      <div className="text-xs text-muted-foreground leading-relaxed space-y-2">{children}</div>
    </div>
  );
}

function Step({ n, children }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mono text-[10px] w-4 h-4 flex items-center justify-center border border-border shrink-0 mt-0.5">{n}</span>
      <span>{children}</span>
    </div>
  );
}

export default function WelcomePopup() {
  const { t, user } = useApp();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [dontShowAgain, setDontShowAgain] = useState(false);

  useEffect(() => {
    const justLoggedIn = sessionStorage.getItem("mg_just_logged_in");
    if (!justLoggedIn) return;
    sessionStorage.removeItem("mg_just_logged_in");
    if (localStorage.getItem(DISMISS_KEY) === "1") return;
    setOpen(true);
  }, []);

  if (!open) return null;

  const close = () => {
    if (dontShowAgain) localStorage.setItem(DISMISS_KEY, "1");
    setOpen(false);
  };

  const go = (path) => { close(); navigate(path); };

  return (
    <div className="fixed inset-0 z-[200] bg-black/70 backdrop-blur-md flex items-center justify-center p-4" data-testid="welcome-popup">
      <div className="bg-card border border-border w-full max-w-4xl max-h-[88vh] overflow-y-auto relative">
        <button onClick={close} className="absolute top-3 right-3 p-2 hover:bg-secondary transition-colors z-10" data-testid="welcome-popup-close">
          <X size={18} />
        </button>

        <div className="p-6 md:p-8 border-b border-border flex items-center gap-3">
          <Logo size={40} className="w-10 h-10 shrink-0" />
          <div>
            <h2 className="font-head font-black text-2xl tracking-tight">Bienvenue sur MG-VMS</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Merci d&apos;avoir installé MG-VMS{user?.name ? `, ${user.name}` : ""} — voici de quoi bien démarrer.
            </p>
          </div>
        </div>

        <div className="p-6 md:p-8 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Section icon={ListChecks} title="Premiers pas" accent="#0044FF">
              <Step n={1}>Ajoutez vos caméras dans <button onClick={() => go("/cameras")} className="text-[#0044FF] hover:underline">Caméras</button>.</Step>
              <Step n={2}>Choisissez vos disques (BDD sur NVMe/SSD, vidéo sur HDD) dans <button onClick={() => go("/settings")} className="text-[#0044FF] hover:underline">Stockage</button>.</Step>
              <Step n={3}>Configurez la rétention et les zones intelligentes selon vos besoins.</Step>
              <Step n={4}>Activez les alertes pour les événements qui comptent vraiment.</Step>
            </Section>

            <Section icon={Lightbulb} title="Bonnes pratiques" accent="#FFB800">
              <p>Un disque <b className="text-foreground">dédié par rôle</b> change tout : NVMe/SSD pour la base de données (écritures aléatoires), HDD pour la vidéo (gros volumes séquentiels, moins cher au Go).</p>
              <p>Vérifiez régulièrement <button onClick={() => go("/settings")} className="text-[#0044FF] hover:underline">l&apos;espace disque et la rétention</button> — un disque plein arrête les nouveaux enregistrements.</p>
              <p>Gardez le firmware de vos caméras à jour et testez vos flux RTSP après chaque changement réseau.</p>
            </Section>

            <Section icon={ShieldAlert} title="Sécurité" accent="#FF3333">
              <p>Changez le mot de passe admin par défaut si ce n&apos;est pas déjà fait.</p>
              <p>Activez la <button onClick={() => go("/security-center/mfa")} className="text-[#0044FF] hover:underline">double authentification (MFA)</button> sur les comptes admin.</p>
              <p>Vérifiez que votre <button onClick={() => go("/security-center/tls")} className="text-[#0044FF] hover:underline">certificat HTTPS</button> est valide et revoyez les <button onClick={() => go("/security-center/rbac")} className="text-[#0044FF] hover:underline">rôles utilisateurs</button> périodiquement.</p>
              <p>Le <button onClick={() => go("/audit")} className="text-[#0044FF] hover:underline">journal d&apos;audit</button> trace toute action sensible — utile en cas de doute.</p>
            </Section>

            <Section icon={Youtube} title="Tutoriels vidéo" accent="#8892a0">
              <p>Des tutoriels vidéo pas-à-pas (installation, caméras, IA, sécurité) sont en préparation.</p>
              <p className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider px-2 py-0.5 border border-border text-muted-foreground">Bientôt disponible</p>
              <p>En attendant, la <a href="https://docs.mg-vms.com" target="_blank" rel="noopener noreferrer" className="text-[#0044FF] hover:underline">documentation</a> couvre l&apos;essentiel.</p>
            </Section>
          </div>

          {user?.role === "admin" && (
            <div>
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-2">
                <KeyRound size={14} /> Support Gold
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed mb-3">
                Le support Gold débloque une assistance prioritaire et des fonctionnalités avancées. Activez une licence
                ci-dessous, ou retrouvez cette section à tout moment dans le menu utilisateur → À propos.
              </p>
              <LicenseSection t={t} />
            </div>
          )}

          <Section icon={LifeBuoy} title="Besoin d'aide ?" accent="#00E676">
            <p>
              <a href="https://mg-vms.com/fr/contact" target="_blank" rel="noopener noreferrer" className="text-[#0044FF] hover:underline">Support MG Informatique</a>
              {" · "}
              <a href="https://docs.mg-vms.com" target="_blank" rel="noopener noreferrer" className="text-[#0044FF] hover:underline">Documentation</a>
              {" · "}
              <button onClick={() => go("/welcome")} className="text-[#0044FF] hover:underline">Changelog des nouveautés</button>
            </p>
          </Section>
        </div>

        <div className="p-4 border-t border-border flex items-center justify-between gap-4">
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" checked={dontShowAgain} onChange={(e) => setDontShowAgain(e.target.checked)} data-testid="welcome-popup-dismiss-checkbox" />
            Ne plus afficher au démarrage
          </label>
          <button onClick={close} className="px-5 py-2 bg-[#0044FF] text-white text-sm" data-testid="welcome-popup-close-btn">
            C&apos;est parti
          </button>
        </div>
      </div>
    </div>
  );
}
