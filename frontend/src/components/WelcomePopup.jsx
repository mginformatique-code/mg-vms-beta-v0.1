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
            <h2 className="font-head font-black text-2xl tracking-tight">{t("wpop.title")}</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              {t("wpop.subtitle")}{user?.name ? `, ${user.name}` : ""} — {t("wpop.subtitle_suffix")}
            </p>
          </div>
        </div>

        <div className="p-6 md:p-8 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Section icon={ListChecks} title={t("wpop.first_steps_title")} accent="#0044FF">
              <Step n={1}>{t("wpop.step1_pre")} <button onClick={() => go("/cameras")} className="text-[#0044FF] hover:underline">{t("wpop.step1_link")}</button>.</Step>
              <Step n={2}>{t("wpop.step2_pre")} <button onClick={() => go("/settings")} className="text-[#0044FF] hover:underline">{t("wpop.step2_link")}</button>.</Step>
              <Step n={3}>{t("wpop.step3")}</Step>
              <Step n={4}>{t("wpop.step4")}</Step>
            </Section>

            <Section icon={Lightbulb} title={t("wpop.best_practices_title")} accent="#FFB800">
              <p>{t("wpop.practice1_pre")} <b className="text-foreground">{t("wpop.practice1_bold")}</b> {t("wpop.practice1_post")}</p>
              <p>{t("wpop.practice2_pre")} <button onClick={() => go("/settings")} className="text-[#0044FF] hover:underline">{t("wpop.practice2_link")}</button> — {t("wpop.practice2_post")}</p>
              <p>{t("wpop.practice3")}</p>
            </Section>

            <Section icon={ShieldAlert} title={t("wpop.security_title")} accent="#FF3333">
              <p>{t("wpop.security1")}</p>
              <p>{t("wpop.security2_pre")} <button onClick={() => go("/security-center/mfa")} className="text-[#0044FF] hover:underline">{t("wpop.security2_link")}</button> {t("wpop.security2_post")}</p>
              <p>{t("wpop.security3_pre")} <button onClick={() => go("/network/tls")} className="text-[#0044FF] hover:underline">{t("wpop.security3_link1")}</button> {t("wpop.security3_mid")} <button onClick={() => go("/security-center/rbac")} className="text-[#0044FF] hover:underline">{t("wpop.security3_link2")}</button> {t("wpop.security3_post")}</p>
              <p>{t("wpop.security4_pre")} <button onClick={() => go("/audit")} className="text-[#0044FF] hover:underline">{t("wpop.security4_link")}</button> {t("wpop.security4_post")}</p>
            </Section>

            <Section icon={Youtube} title={t("wpop.tutorials_title")} accent="#8892a0">
              <p>{t("wpop.tutorials_body")}</p>
              <p className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider px-2 py-0.5 border border-border text-muted-foreground">{t("wpop.tutorials_soon")}</p>
              <p>{t("wpop.tutorials_meanwhile_pre")} <a href="https://docs.mg-vms.com" target="_blank" rel="noopener noreferrer" className="text-[#0044FF] hover:underline">{t("wpop.tutorials_doc_link")}</a> {t("wpop.tutorials_meanwhile_post")}</p>
            </Section>
          </div>

          {user?.role === "admin" && (
            <div>
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-2">
                <KeyRound size={14} /> {t("wpop.gold_support_title")}
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed mb-3">
                {t("wpop.gold_support_body")}
              </p>
              <LicenseSection t={t} />
            </div>
          )}

          <Section icon={LifeBuoy} title={t("wpop.help_title")} accent="#00E676">
            <p>
              <a href="https://mg-vms.com/fr/contact" target="_blank" rel="noopener noreferrer" className="text-[#0044FF] hover:underline">{t("wpop.help_support_link")}</a>
              {" · "}
              <a href="https://docs.mg-vms.com" target="_blank" rel="noopener noreferrer" className="text-[#0044FF] hover:underline">{t("wpop.help_doc_link")}</a>
              {" · "}
              <button onClick={() => go("/welcome")} className="text-[#0044FF] hover:underline">{t("wpop.help_changelog_link")}</button>
            </p>
          </Section>
        </div>

        <div className="p-4 border-t border-border flex items-center justify-between gap-4">
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" checked={dontShowAgain} onChange={(e) => setDontShowAgain(e.target.checked)} data-testid="welcome-popup-dismiss-checkbox" />
            {t("wpop.dont_show_again")}
          </label>
          <button onClick={close} className="px-5 py-2 bg-[#0044FF] text-white text-sm" data-testid="welcome-popup-close-btn">
            {t("wpop.lets_go")}
          </button>
        </div>
      </div>
    </div>
  );
}
