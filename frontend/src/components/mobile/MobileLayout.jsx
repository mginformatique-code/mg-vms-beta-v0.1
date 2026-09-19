/**
 * MobileLayout — coquille de l'interface mobile dédiée (v3.91).
 *
 * PAS une sidebar réduite : un vrai pattern app mobile, barre de navigation
 * basse à 4 onglets + en-tête minimal (logo, cloche alertes, bascule vers
 * la vue complète). Consomme `useApp()` exactement comme `Layout.jsx`
 * (desktop) — même contexte auth/thème/langue/alertes, aucun état dupliqué.
 */
import React from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import useIsMobileViewport from "@/hooks/useIsMobileViewport";
import Logo from "@/components/Logo";
import useMobileScrollRestore from "@/hooks/useMobileScrollRestore";
import { Home, Video, Zap, Cctv, MoreHorizontal, ChevronLeft } from "lucide-react";

// v3.93 · "Accueil" ajouté en 1ère position (référence app Reolink) — liste
// des sites, entrée naturelle pour un déploiement multi-site (MG-VMS n'a
// pas d'équivalent au "Home = mes appareils" de Reolink, qui est mono-site
// par construction).
const TABS = [
  { to: "/m/home", key: "mobile.nav_home", icon: Home },
  { to: "/m/live", key: "mobile.nav_live", icon: Video },
  { to: "/m/events", key: "mobile.nav_events", icon: Zap },
  // v3.97 · Pointe vers `/m/camera-center` (CameraCenterDispatch — tri,
  // filtre, plugins IA par caméra, déjà mobile-friendly) plutôt que la
  // simple liste de statut `/m/cameras` : signalé par l'utilisateur comme
  // la vraie page "Centre caméras" attendue, déjà présente dans l'app
  // (atteinte jusqu'ici seulement via le menu Plus). `/m/cameras` reste
  // utilisée pour le fil site->caméras depuis Accueil (MobileHome).
  { to: "/m/camera-center", key: "mobile.nav_cameras", icon: Cctv },
  { to: "/m/more", key: "mobile.nav_more", icon: MoreHorizontal },
];

export default function MobileLayout({ children }) {
  const { t, alertPing } = useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const { setMode } = useIsMobileViewport();
  const [alertCount, setAlertCount] = React.useState(0);
  React.useEffect(() => { if (alertPing) setAlertCount((c) => c + 1); }, [alertPing]);
  // v3.112 · "la cloche des notifs ne sert à rien, supprime-la, ajoute
  // plutôt le compteur sur Événements" — la cloche du header est retirée
  // (voir header ci-dessous) ; son compteur vit désormais directement sur
  // l'onglet Événements de la barre basse, remis à zéro dès qu'on y est.
  React.useEffect(() => { if (location.pathname === "/m/events") setAlertCount(0); }, [location.pathname]);
  const mainRef = React.useRef(null);
  useMobileScrollRestore(mainRef);

  // v3.115 · "tu penses pouvoir bloquer le mode zoom-dezoom ?" — verrouille
  // le pincement de zoom natif du navigateur, MOBILE UNIQUEMENT (restauré
  // à la valeur d'origine au démontage, donc jamais appliqué aux routes
  // desktop qui partagent le même index.html/meta viewport). Un pincement
  // accidentel sur l'app zoomait toute la page au lieu d'agir dans l'app.
  React.useEffect(() => {
    const meta = document.querySelector('meta[name="viewport"]');
    if (!meta) return;
    const original = meta.getAttribute("content");
    meta.setAttribute("content", "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no");
    return () => { meta.setAttribute("content", original); };
  }, []);

  // v3.104 · Bouton retour actif sur TOUTES les pages, y compris les 5
  // onglets racine (demande explicite : "que ce soit actif sur toutes les
  // pages" — la v3.103 le réservait aux pages non-racine). `navigate(-1)`
  // réutilise l'historique du navigateur, donc "Plus" retrouve sa position
  // de scroll (voir useMobileScrollRestore) même en repartant d'un onglet.

  return (
    <div className="h-[100dvh] flex flex-col bg-background text-foreground overflow-hidden" data-testid="mobile-shell">
      <header className="h-12 shrink-0 border-b border-border bg-card flex items-center justify-between px-3">
        <div className="flex items-center gap-2 min-w-0">
          <button onClick={() => navigate(-1)} data-testid="mobile-topbar-back"
                  className="p-1 -ml-1 text-foreground shrink-0">
            <ChevronLeft size={22} />
          </button>
          <Logo size={26} className="w-[26px] h-[26px] shrink-0" />
          <span className="font-head font-black text-sm tracking-tight truncate">MG-VMS</span>
        </div>
      </header>

      <main ref={mainRef} className="flex-1 overflow-y-auto overscroll-contain">{children}</main>

      <nav className="shrink-0 border-t border-border bg-card grid grid-cols-5" data-testid="mobile-tabbar"
           style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isEvents = tab.key === "mobile.nav_events";
          return (
            <NavLink key={tab.to} to={tab.to}
                     data-testid={`mobile-tab-${tab.key.split("_")[1]}`}
                     className={({ isActive }) =>
                       `flex flex-col items-center justify-center gap-0.5 py-2 px-0.5 text-[9px] uppercase ${
                         isActive ? "text-[#0044FF]" : "text-muted-foreground"
                       }`
                     }>
              <span className="relative">
                <Icon size={19} strokeWidth={1.5} />
                {isEvents && alertCount > 0 && (
                  <span className="absolute -top-1 -right-2 min-w-3.5 h-3.5 px-1 bg-[#FF3333] text-white text-[8px] font-bold flex items-center justify-center rounded-full"
                        data-testid="mobile-tab-events-badge">
                    {alertCount > 99 ? "99+" : alertCount}
                  </span>
                )}
              </span>
              <span className="truncate max-w-full">{t(tab.key)}</span>
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
}
