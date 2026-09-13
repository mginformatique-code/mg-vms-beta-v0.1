/**
 * MobileMore — compte, réglages, ET (v3.92) l'intégralité des menus
 * desktop, réutilisés tels quels depuis `Layout.jsx` (export `NAV`) — une
 * seule source de vérité, mêmes permissions (`can`/`hasPerm`) que la
 * sidebar desktop. Un item qui pointe vers un écran non mobile-optimisé
 * (ex. RBAC, Pipeline Inspector) navigue simplement vers cette route, qui
 * s'affiche alors dans le shell desktop complet — un accès de secours
 * fonctionnel, pas une version mobile de ces pages (hors périmètre, voir
 * le plan).
 *
 * v3.93 · Reskin "cartes groupées" (référence app Reolink, capture d'écran
 * fournie par l'utilisateur : device card en tête, sections à en-tête
 * discret, lignes chevron `>` sans accordéon). Les sous-menus (children)
 * sont donc APLATIS ici — chaque enfant devient une ligne directe sous
 * l'en-tête de sa section, pas un groupe repliable comme sur desktop
 * (cohérent avec le "Paramètres" Reolink : jamais d'accordéon, uniquement
 * des lignes qui naviguent).
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import useIsMobileViewport from "@/hooks/useIsMobileViewport";
import { NAV } from "@/components/Layout";
import { LogOut, Moon, Sun, Languages, Monitor, ChevronRight } from "lucide-react";

function SectionLabel({ children }) {
  return <div className="px-4 pt-4 pb-1.5 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{children}</div>;
}

function Card({ children, testId }) {
  return (
    <div data-testid={testId} className="mx-3 rounded-xl bg-card border border-border overflow-hidden divide-y divide-border">
      {children}
    </div>
  );
}

function Row({ icon: Icon, label, onClick, testId, value, chevron = true }) {
  return (
    <button onClick={onClick} data-testid={testId}
            className="w-full flex items-center gap-3 px-3.5 py-3 text-left">
      {Icon && <Icon size={17} strokeWidth={1.5} className="text-muted-foreground shrink-0" />}
      <span className="flex-1 text-sm">{label}</span>
      {value && <span className="text-xs text-muted-foreground">{value}</span>}
      {chevron && <ChevronRight size={15} className="text-muted-foreground/60 shrink-0" />}
    </button>
  );
}

export default function MobileMore() {
  const { t, user, logout, theme, toggleTheme, lang, toggleLang, can, hasPerm } = useApp();
  const navigate = useNavigate();
  const { setMode } = useIsMobileViewport();

  // v3.93 · Aplatit chaque groupe NAV (children) en lignes directes,
  // exactement comme la liste "Paramètres" Reolink (screenshot de
  // référence) — jamais d'accordéon imbriqué.
  const flatten = (items) => items.flatMap((it) => {
    if (!it.children) return [it];
    return it.children.filter((c) => (!c.role || can(c.role)) && (!c.perm || hasPerm(c.perm)));
  });

  return (
    <div className="pb-4" data-testid="mobile-more">
      <Card testId="mobile-more-account">
        <div className="flex items-center gap-3 px-3.5 py-4">
          <div className="w-11 h-11 shrink-0 flex items-center justify-center bg-secondary rounded-full text-sm font-head font-bold">
            {(user?.name || "U").slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{user?.name}</div>
            <div className="text-[11px] uppercase tracking-wider text-[#0044FF]">{user?.role}</div>
          </div>
        </div>
      </Card>

      <SectionLabel>{t("mobile.more_quick_settings")}</SectionLabel>
      <Card testId="mobile-more-settings-card">
        <Row icon={theme === "dark" ? Sun : Moon} label={t("mobile.more_theme")}
             value={theme === "dark" ? t("mobile.more_theme_dark") : t("mobile.more_theme_light")}
             onClick={toggleTheme} testId="mobile-more-theme" chevron={false} />
        <Row icon={Languages} label={t("mobile.more_lang")} value={lang.toUpperCase()}
             onClick={toggleLang} testId="mobile-more-lang" chevron={false} />
        <Row icon={Monitor} label={t("mobile.more_switch_desktop")}
             onClick={() => { setMode("desktop"); navigate("/dashboard"); }}
             testId="mobile-more-desktop" />
      </Card>

      {NAV.map((g) => {
        const items = flatten(g.items.filter((it) => (!it.role || can(it.role)) && (!it.perm || hasPerm(it.perm))));
        if (items.length === 0) return null;
        return (
          <React.Fragment key={g.group}>
            <SectionLabel>{t(g.group)}</SectionLabel>
            <Card testId={`mobile-more-navgroup-${g.group.split(".")[1]}`}>
              {items.map((it) => (
                <Row key={it.to} icon={it.icon} label={t(it.key)}
                     onClick={() => navigate(it.to)}
                     testId={`mobile-more-nav-${it.key.split(".")[1]}`} />
              ))}
            </Card>
          </React.Fragment>
        );
      })}

      <SectionLabel>&nbsp;</SectionLabel>
      <Card testId="mobile-more-logout-card">
        <Row icon={LogOut} label={t("nav.logout")} chevron={false}
             onClick={() => { logout(); navigate("/login"); }} testId="mobile-more-logout" />
      </Card>
    </div>
  );
}
