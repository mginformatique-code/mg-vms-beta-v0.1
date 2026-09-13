/**
 * MobileLayout — coquille de l'interface mobile dédiée (v3.91).
 *
 * PAS une sidebar réduite : un vrai pattern app mobile, barre de navigation
 * basse à 4 onglets + en-tête minimal (logo, cloche alertes, bascule vers
 * la vue complète). Consomme `useApp()` exactement comme `Layout.jsx`
 * (desktop) — même contexte auth/thème/langue/alertes, aucun état dupliqué.
 */
import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import useIsMobileViewport from "@/hooks/useIsMobileViewport";
import Logo from "@/components/Logo";
import { Video, Zap, Cctv, MoreHorizontal, Bell } from "lucide-react";

const TABS = [
  { to: "/m/live", key: "mobile.nav_live", icon: Video },
  { to: "/m/events", key: "mobile.nav_events", icon: Zap },
  { to: "/m/cameras", key: "mobile.nav_cameras", icon: Cctv },
  { to: "/m/more", key: "mobile.nav_more", icon: MoreHorizontal },
];

export default function MobileLayout({ children }) {
  const { t, alertPing } = useApp();
  const navigate = useNavigate();
  const { setMode } = useIsMobileViewport();
  const [alertCount, setAlertCount] = React.useState(0);
  React.useEffect(() => { if (alertPing) setAlertCount((c) => c + 1); }, [alertPing]);

  return (
    <div className="h-[100dvh] flex flex-col bg-background text-foreground overflow-hidden" data-testid="mobile-shell">
      <header className="h-12 shrink-0 border-b border-border bg-card flex items-center justify-between px-3">
        <div className="flex items-center gap-2">
          <Logo size={26} className="w-[26px] h-[26px]" />
          <span className="font-head font-black text-sm tracking-tight">MG-VMS</span>
        </div>
        <button onClick={() => navigate("/m/events")} data-testid="mobile-topbar-alerts"
                className="relative p-2 -mr-2 text-muted-foreground">
          <Bell size={19} strokeWidth={1.5} />
          {alertCount > 0 && (
            <span className="absolute top-0.5 right-0.5 min-w-4 h-4 px-1 bg-[#FF3333] text-white text-[9px] font-bold flex items-center justify-center rounded-full">
              {alertCount}
            </span>
          )}
        </button>
      </header>

      <main className="flex-1 overflow-y-auto overscroll-contain">{children}</main>

      <nav className="shrink-0 border-t border-border bg-card grid grid-cols-4" data-testid="mobile-tabbar"
           style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <NavLink key={tab.to} to={tab.to}
                     data-testid={`mobile-tab-${tab.key.split("_")[1]}`}
                     className={({ isActive }) =>
                       `flex flex-col items-center justify-center gap-0.5 py-2 text-[10px] uppercase tracking-wider ${
                         isActive ? "text-[#0044FF]" : "text-muted-foreground"
                       }`
                     }>
              <Icon size={20} strokeWidth={1.5} />
              {t(tab.key)}
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
}
