/**
 * MobileMore — compte, réglages rapides, bascule vers la vue complète
 * (v3.91, interface mobile). PAS un menu de configuration : les réglages
 * avancés (utilisateurs, RBAC, réseau, IA...) restent desktop-only —
 * voir le plan. Seul un lien explicite permet de forcer le retour au
 * shell complet.
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import useIsMobileViewport from "@/hooks/useIsMobileViewport";
import { LogOut, Moon, Sun, Languages, Monitor } from "lucide-react";

function Row({ icon: Icon, label, onClick, testId, value }) {
  return (
    <button onClick={onClick} data-testid={testId}
            className="w-full flex items-center gap-3 px-3 py-3 border-b border-border text-left">
      <Icon size={18} strokeWidth={1.5} className="text-muted-foreground shrink-0" />
      <span className="flex-1 text-sm">{label}</span>
      {value && <span className="text-xs text-muted-foreground">{value}</span>}
    </button>
  );
}

export default function MobileMore() {
  const { t, user, logout, theme, toggleTheme, lang, toggleLang } = useApp();
  const navigate = useNavigate();
  const { setMode } = useIsMobileViewport();

  return (
    <div className="flex flex-col" data-testid="mobile-more">
      <div className="px-3 py-4 border-b border-border">
        <div className="text-sm font-medium">{user?.name}</div>
        <div className="text-[11px] uppercase tracking-wider text-[#0044FF]">{user?.role}</div>
      </div>

      <Row icon={theme === "dark" ? Sun : Moon} label={t("mobile.more_theme")}
           value={theme === "dark" ? t("mobile.more_theme_dark") : t("mobile.more_theme_light")}
           onClick={toggleTheme} testId="mobile-more-theme" />
      <Row icon={Languages} label={t("mobile.more_lang")} value={lang.toUpperCase()}
           onClick={toggleLang} testId="mobile-more-lang" />
      <Row icon={Monitor} label={t("mobile.more_switch_desktop")}
           onClick={() => { setMode("desktop"); navigate("/dashboard"); }}
           testId="mobile-more-desktop" />
      <Row icon={LogOut} label={t("nav.logout")}
           onClick={() => { logout(); navigate("/login"); }} testId="mobile-more-logout" />
    </div>
  );
}
