/**
 * MobileMore — compte, réglages, ET (v3.92) l'intégralité des menus
 * desktop, réutilisés tels quels depuis `Layout.jsx` (export `NAV`) — une
 * seule source de vérité, mêmes permissions (`can`/`hasPerm`) que la
 * sidebar desktop. v3.94 · Chaque item navigue vers son équivalent monté
 * sous `/m/...` (voir App.js) — la page desktop s'affiche TOUJOURS dans le
 * shell mobile (barre basse), jamais dans le shell desktop (demande
 * explicite : "on est bien sûr un frontend mobile only ?"). L'optimisation
 * visuelle fine de chaque page reste incrémentale, mais rien n'éjecte plus
 * du shell mobile.
 *
 * v3.93 · Reskin "cartes groupées" (référence app Reolink, capture d'écran
 * fournie par l'utilisateur : device card en tête, sections à en-tête
 * discret, lignes chevron `>` sans accordéon). Les sous-menus (children)
 * sont donc APLATIS ici — chaque enfant devient une ligne directe sous
 * l'en-tête de sa section, pas un groupe repliable comme sur desktop
 * (cohérent avec le "Paramètres" Reolink : jamais d'accordéon, uniquement
 * des lignes qui naviguent).
 */
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import useIsMobileViewport from "@/hooks/useIsMobileViewport";
import { NAV, AboutDialog } from "@/components/Layout";
import { LogOut, Moon, Sun, Languages, Monitor, ChevronRight, Info } from "lucide-react";

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

// v3.94 · "toutes les pages compatibles" — chaque route desktop est
// montée aussi sous `/m/...` (voir App.js), MÊME chemin par défaut. Une
// seule exception : `/cameras` (Appareils, CRUD/ajout de caméra côté
// desktop) collision avec `/m/cameras`, déjà pris par la liste de statut
// mobile dédiée (onglet Caméras) — redirigée vers un chemin distinct.
const MOBILE_PATH_OVERRIDES = { "/cameras": "/m/camera-devices" };
const mobilePathFor = (to) => MOBILE_PATH_OVERRIDES[to] || `/m${to}`;

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
  // v3.94 · Tap sur la carte compte → même menu que le clic sur
  // l'utilisateur côté sidebar desktop (À propos + Déconnexion), demande
  // explicite. `AboutDialog` réutilisé tel quel (licence/EULA/support/
  // statut MG-VMS Center), aucune réécriture.
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);

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
        <button onClick={() => setAccountMenuOpen(true)} data-testid="mobile-more-account-trigger"
                className="w-full flex items-center gap-3 px-3.5 py-4 text-left">
          <div className="w-11 h-11 shrink-0 flex items-center justify-center bg-secondary rounded-full text-sm font-head font-bold">
            {(user?.name || "U").slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium truncate">{user?.name}</div>
            <div className="text-[11px] uppercase tracking-wider text-[#0044FF]">{user?.role}</div>
          </div>
          <ChevronRight size={15} className="text-muted-foreground/60 shrink-0" />
        </button>
      </Card>

      {accountMenuOpen && (
        <>
          <div className="fixed inset-0 z-40 bg-black/40" onClick={() => setAccountMenuOpen(false)} />
          <div className="fixed inset-x-3 bottom-20 z-50 rounded-xl bg-card border border-border overflow-hidden divide-y divide-border"
               data-testid="mobile-more-account-menu">
            <Row icon={Info} label={t("nav.about")} chevron={false}
                 onClick={() => { setAccountMenuOpen(false); setAboutOpen(true); }} testId="mobile-more-about" />
            <Row icon={LogOut} label={t("nav.logout")} chevron={false}
                 onClick={() => { logout(); navigate("/login"); }} testId="mobile-more-logout" />
          </div>
        </>
      )}
      <AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} t={t} isAdmin={user?.role === "admin"} lang={lang} />

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
                     onClick={() => navigate(mobilePathFor(it.to))}
                     testId={`mobile-more-nav-${it.key.split(".")[1]}`} />
              ))}
            </Card>
          </React.Fragment>
        );
      })}
    </div>
  );
}
