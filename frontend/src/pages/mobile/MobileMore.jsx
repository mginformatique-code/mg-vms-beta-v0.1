/**
 * MobileMore — compte, réglages rapides, bascule vers la vue complète, ET
 * (v3.92, demande explicite "ajouter tous les menus") l'intégralité des
 * menus desktop, réutilisés tels quels depuis `Layout.jsx` (export `NAV`)
 * — une seule source de vérité, mêmes permissions (`can`/`hasPerm`) que la
 * sidebar desktop. Un item qui pointe vers un écran non mobile-optimisé
 * (ex. RBAC, Pipeline Inspector) navigue simplement vers cette route, qui
 * s'affiche alors dans le shell desktop complet — un accès de secours
 * fonctionnel, pas une version mobile de ces pages (hors périmètre, voir
 * le plan).
 */
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import useIsMobileViewport from "@/hooks/useIsMobileViewport";
import { NAV } from "@/components/Layout";
import { LogOut, Moon, Sun, Languages, Monitor, ChevronDown, ChevronRight } from "lucide-react";

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

function MenuLeaf({ item, t, navigate }) {
  const Icon = item.icon;
  return (
    <button onClick={() => navigate(item.to)} data-testid={`mobile-more-nav-${item.key.split(".")[1]}`}
            className="w-full flex items-center gap-3 pl-9 pr-3 py-2.5 border-b border-border text-left">
      <Icon size={15} strokeWidth={1.5} className="text-muted-foreground shrink-0" />
      <span className="flex-1 text-[13px]">{t(item.key)}</span>
    </button>
  );
}

function MenuGroupItem({ item, t, can, hasPerm, navigate }) {
  const [open, setOpen] = useState(false);
  const children = (item.children || []).filter((c) => (!c.role || can(c.role)) && (!c.perm || hasPerm(c.perm)));
  if (children.length === 0) return null;
  const Icon = item.icon;
  return (
    <div data-testid={`mobile-more-navgroup-${item.key.split(".")[1]}`}>
      <button onClick={() => setOpen((v) => !v)}
              className="w-full flex items-center gap-3 px-3 py-3 border-b border-border text-left">
        <Icon size={18} strokeWidth={1.5} className="text-muted-foreground shrink-0" />
        <span className="flex-1 text-sm">{t(item.key)}</span>
        {open ? <ChevronDown size={15} className="text-muted-foreground" /> : <ChevronRight size={15} className="text-muted-foreground" />}
      </button>
      {open && children.map((c) => <MenuLeaf key={c.to} item={c} t={t} navigate={navigate} />)}
    </div>
  );
}

export default function MobileMore() {
  const { t, user, logout, theme, toggleTheme, lang, toggleLang, can, hasPerm } = useApp();
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

      <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
        {t("mobile.more_all_menus")}
      </div>
      {NAV.map((g) => {
        const items = g.items.filter((it) => (!it.role || can(it.role)) && (!it.perm || hasPerm(it.perm)));
        if (items.length === 0) return null;
        return (
          <div key={g.group}>
            <div className="px-3 pt-3 pb-1 text-[10px] uppercase tracking-[0.15em] text-muted-foreground">{t(g.group)}</div>
            {items.map((it) => it.children
              ? <MenuGroupItem key={it.key} item={it} t={t} can={can} hasPerm={hasPerm} navigate={navigate} />
              : <MenuLeaf key={it.to} item={it} t={t} navigate={navigate} />)}
          </div>
        );
      })}

      <div className="mt-2">
        <Row icon={LogOut} label={t("nav.logout")}
             onClick={() => { logout(); navigate("/login"); }} testId="mobile-more-logout" />
      </div>
    </div>
  );
}
