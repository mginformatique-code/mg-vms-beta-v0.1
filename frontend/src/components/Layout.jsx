import React, { useEffect, useState } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import Logo from "@/components/Logo";
import LicenseSection from "@/components/LicenseSection";
import CookieSection from "@/components/CookieSection";
import OpenSourceLicenses from "@/components/OpenSourceLicenses";
import WelcomePopup from "@/components/WelcomePopup";
import CookieConsentBanner from "@/components/CookieConsentBanner";
import {
  LayoutDashboard, Grid3x3, Cctv, Building2, ScanLine, Car, Bell, Map, Zap,
  ScrollText, Users, Settings, LogOut, Moon, Sun, Languages, Cpu, HardDrive, MemoryStick, BellRing, Puzzle, Film, Network, FileText, Server, Radio, Brain, Activity, ScanFace, Thermometer, Radar, Plane, DoorOpen, MapPin, Clock, Layers, ChevronDown, ChevronRight, LineChart, Sparkles, ShieldCheck, Lock, Info, LifeBuoy, ScrollText as LegalIcon, Terminal,
} from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const PLUGIN_ICON = {
  anpr: ScanLine, ai_detection: Brain, tracking: Activity, face_recognition: ScanFace,
  parking: Car, thermal: Thermometer, radar: Radar, drone: Plane, mqtt: Radio, access_control: DoorOpen,
};

const NAV = [
  { group: "nav.operations", items: [
    // Accueil avec vrai sous-menu (Welcome Center + Tableau de bord)
    { key: "nav.home", icon: LayoutDashboard, children: [
      { to: "/", key: "nav.welcome", icon: Sparkles, end: true },
      { to: "/dashboard", key: "nav.dashboard", icon: Grid3x3 },
    ]},
    // v1.0-rc4 · Regroupement Caméras : Appareils + Mur vidéo + Centre caméras
    { key: "nav.cameras", icon: Cctv, children: [
      { to: "/cameras", key: "nav.devices", icon: Cctv },
      { to: "/live", key: "nav.live", icon: Grid3x3, perm: "view_live" },
      { to: "/camera-center", key: "nav.camera_center", icon: Layers },
    ]},
    { to: "/recordings", icon: Film, key: "nav.recordings", perm: "view_recordings" },
    { to: "/sites", icon: Building2, key: "nav.sites" },
    { to: "/map", icon: Map, key: "nav.map" },
  ]},
  { group: "nav.events_group", items: [
    // Vrai sous-menu Événements
    // v1.0-rc4 · Fusion : la vue Véhicules vit dans Événements (chip « Plaques »)
    { key: "nav.events_root", icon: Zap, children: [
      { to: "/events", key: "nav.events_item", icon: Zap },
      { to: "/alerts", key: "nav.alerts", icon: Bell },
    ]},
  ]},
  { group: "nav.intelligence", items: [
    { to: "/smart-zones", icon: MapPin, key: "nav.smart_zones" },
    { to: "/workflows", icon: Zap, key: "nav.workflows" },
  ]},
  { group: "nav.admin", items: [
    { to: "/pipeline-center", icon: LineChart, key: "nav.pipeline_center", role: "technician" },
    // Centre de sécurité — sous-menu complet (Vue d'ensemble + Utilisateurs + MFA + Sessions + RBAC)
    { key: "nav.security_center", icon: ShieldCheck, role: "admin", children: [
      { to: "/security-center", key: "nav.security_score", icon: ShieldCheck, end: true },
      { to: "/users", key: "nav.users", icon: Users, role: "admin" },
      { to: "/security-center/mfa", key: "nav.mfa", icon: Lock },
      { to: "/security-center/sessions", key: "nav.sessions_active", icon: Clock },
      { to: "/security-center/rbac", key: "nav.rbac", icon: Layers, role: "admin" },
    ]},
    { to: "/network", icon: Network, key: "nav.network", role: "client" },
    { to: "/plugins", icon: Puzzle, key: "nav.plugins", role: "admin" },
    { to: "/llm-settings", icon: Brain, key: "nav.llm", role: "admin" },
  ]},
  { group: "nav.logs_reports", items: [
    { to: "/reports", icon: FileText, key: "nav.reports", role: "technician" },
    { to: "/audit", icon: ScrollText, key: "nav.audit", role: "technician" },
    { to: "/diagnostics", icon: Activity, key: "nav.diagnostics", role: "technician" },
    { to: "/logs-systeme", icon: Terminal, key: "nav.system_logs", role: "technician" },
  ]},
  { group: "nav.settings_group", items: [
    { to: "/storage", icon: HardDrive, key: "nav.storage" },
    { to: "/date-heure", icon: Clock, key: "nav.datetime" },
    { to: "/notifications", icon: BellRing, key: "nav.notifications", role: "technician" },
  ]},
];

function MiniBar({ label, value, icon: Icon }) {
  const color = value > 80 ? "#FF3333" : value > 65 ? "#FFB800" : "#00E676";
  return (
    <div className="flex items-center gap-2" data-testid={`metric-${label}`}>
      <Icon size={14} strokeWidth={1.5} className="text-muted-foreground" />
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground hidden xl:inline">{label}</span>
      <div className="w-14 h-1.5 bg-secondary overflow-hidden">
        <div style={{ width: `${value}%`, backgroundColor: color }} className="h-full transition-all" />
      </div>
      <span className="text-xs mono w-8">{value}%</span>
    </div>
  );
}

function GpuMiniBar({ gpu, onClick }) {
  // 3 états : (a) GPU actif → couleur selon util%, (b) GPU absent → gris "CPU"
  const isActive = !!(gpu?.available);
  const util = isActive ? (gpu.gpu_util_pct || 0) : 0;
  const color = !isActive ? "#666" : (util > 80 ? "#FF3333" : util > 65 ? "#FFB800" : "#00E676");
  const label = isActive ? "GPU" : "CPU";
  const title = isActive
    ? `${gpu.name || "GPU"} · VRAM ${gpu.vram_used_mb || 0}/${gpu.vram_total_mb || 0} MB · ${gpu.temperature_c || 0}°C`
    : `Aucun GPU NVIDIA détecté — pipeline IA sur CPU. ${gpu?.error || ""}`;
  return (
    <button onClick={onClick} data-testid="metric-GPU" title={title}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity">
      <Zap size={14} strokeWidth={1.5} style={{ color: isActive ? color : "#666" }} />
      <span className="text-[10px] uppercase tracking-wider hidden xl:inline"
            style={{ color: isActive ? "#00E676" : "#FF3333" }}>{label}</span>
      <div className="w-14 h-1.5 bg-secondary overflow-hidden">
        <div style={{ width: `${util}%`, backgroundColor: color }} className="h-full transition-all" />
      </div>
      <span className="text-xs mono w-8" style={{ color: isActive ? undefined : "#FF3333" }}>
        {isActive ? `${util}%` : "N/A"}
      </span>
    </button>
  );
}

function NavLeafItem({ item, t }) {
  const Ic = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      data-testid={`nav-${item.key.split(".")[1]}`}
      className={({ isActive }) =>
        `flex items-center gap-3 px-4 py-2 text-sm transition-colors border-l-2 ${
          isActive
            ? "border-l-[#0044FF] bg-secondary text-foreground font-medium"
            : "border-l-transparent text-muted-foreground hover:bg-secondary hover:text-foreground"
        }`
      }
    >
      <Ic size={17} strokeWidth={1.5} />
      {t(item.key)}
    </NavLink>
  );
}

function NavGroupItem({ item, t, can, hasPerm }) {
  const location = useLocation();
  const children = (item.children || []).filter(
    (c) => (!c.role || can(c.role)) && (!c.perm || hasPerm(c.perm))
  );
  const pathOf = (to) => (to || "").split("#")[0];
  const hashOf = (to) => { const i = (to || "").indexOf("#"); return i >= 0 ? (to || "").slice(i) : ""; };
  const activeChild = children.some((c) => location.pathname === pathOf(c.to));
  const [open, setOpen] = useState(activeChild);
  useEffect(() => {
    if (activeChild) setOpen(true);
  }, [activeChild]);
  const Ic = item.icon;
  const testId = `nav-${item.key.split(".")[1]}`;
  return (
    <div data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center gap-3 px-4 py-2 text-sm transition-colors border-l-2 ${
          activeChild
            ? "border-l-[#0044FF] text-foreground font-medium"
            : "border-l-transparent text-muted-foreground hover:bg-secondary hover:text-foreground"
        }`}
        aria-expanded={open}
      >
        <Ic size={17} strokeWidth={1.5} />
        <span className="flex-1 text-left">{t(item.key)}</span>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>
      {open && (
        <div className="pb-1">
          {children.map((c) => {
            const CIc = c.icon;
            // Détection d'active tenant compte du hash (`/settings#mfa`).
            const childPath = pathOf(c.to);
            const childHash = hashOf(c.to);
            const isActive = location.pathname === childPath
              && (childHash ? location.hash === childHash
                            : (!location.hash || c.end !== false));
            // Quand plusieurs enfants pointent vers le même pathname, on ne
            // veut pas que "général" (sans hash) reste actif si un hash est
            // présent dans l'URL.
            const sameGroup = children.some((cc) => cc !== c && pathOf(cc.to) === childPath);
            const finalActive = !sameGroup
              ? location.pathname === childPath
              : (location.pathname === childPath &&
                 (childHash ? location.hash === childHash : !location.hash));
            return (
              <NavLink
                key={c.to}
                to={c.to}
                end={c.end}
                data-testid={`nav-${c.key.split(".")[1]}`}
                className={`flex items-center gap-2 pl-11 pr-4 py-1.5 text-[13px] transition-colors border-l-2 ${
                  finalActive
                    ? "border-l-[#0044FF] bg-secondary text-foreground font-medium"
                    : "border-l-transparent text-muted-foreground/90 hover:bg-secondary hover:text-foreground"
                }`}
              >
                <CIc size={13} strokeWidth={1.5} />
                {t(c.key)}
              </NavLink>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AboutDialog({ open, onOpenChange, t, isAdmin, lang }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="about-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Logo size={22} className="w-5 h-5" /> {t("about.title")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4 text-sm">
          <div className="flex justify-center py-2">
            <Logo size={160} className="w-40 h-40" data-testid="about-logo-large" />
          </div>
          <div className="font-head font-bold text-base">{t("about.company")}</div>
          <div className="border border-border p-3">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-2">
              <LifeBuoy size={14} /> {t("about.support")}
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed mb-2">{t("about.support_desc")}</p>
            <a href="https://mg-vms.com/fr/contact" target="_blank" rel="noopener noreferrer"
               className="text-xs text-[#0044FF] hover:underline" data-testid="about-support-link">
              mg-vms.com/fr/contact
            </a>
          </div>
          <div className="border border-border p-3">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-2">
              <LegalIcon size={14} /> {t("about.legal")}
            </div>
            <a href="https://mginformatique.com" target="_blank" rel="noopener noreferrer"
               className="text-xs text-[#0044FF] hover:underline" data-testid="about-legal-link">
              mginformatique.com
            </a>
          </div>
          {/* Licence d'utilisation (EULA) — visible par TOUS les profils :
              c'est le cadre juridique d'usage du logiciel, pas un réglage
              d'administration. La clé de licence Gold ci-dessous, elle, reste
              réservée aux admins puisqu'eux seuls peuvent l'activer. */}
          <div className="border border-border p-3" data-testid="about-eula-section">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-2">
              <ScrollText size={14} /> {t("eula.title")}
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed mb-2">{t("eula.desc")}</p>
            <a href="https://mg-vms.com/fr/cgu" target="_blank" rel="noopener noreferrer"
               className="text-xs text-[#0044FF] hover:underline" data-testid="about-eula-link">
              {t("eula.link")}
            </a>
          </div>
          {isAdmin && <LicenseSection t={t} />}
          <OpenSourceLicenses t={t} lang={lang} />
          <CookieSection />
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function Layout({ children }) {
  const { t, user, logout, theme, toggleTheme, lang, toggleLang, can, hasPerm, liveMetrics, alertPing } = useApp();
  const navigate = useNavigate();
  const [sys, setSys] = useState({ cpu: 0, ram: 0, storage: 0, gpu: { available: false } });
  const [alertCount, setAlertCount] = useState(0);
  const [aboutOpen, setAboutOpen] = useState(false);

  const loadStats = () => {
    api.get("/dashboard/stats").then((r) => {
      setSys(r.data.system);
      setAlertCount(r.data.alerts_active);
    }).catch(() => {});
  };
  useEffect(() => {
    loadStats();
    const i = setInterval(loadStats, 30000);
    return () => { clearInterval(i); };
  }, []);

  // Mise à jour live via WebSocket
  useEffect(() => { if (liveMetrics) setSys(liveMetrics); }, [liveMetrics]);
  useEffect(() => { if (alertPing) setAlertCount((c) => c + 1); }, [alertPing]);

  return (
    <>
    <WelcomePopup />
    <CookieConsentBanner onOpenPreferences={() => setAboutOpen(true)} />
    <div className="h-screen flex overflow-hidden bg-background text-foreground">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-border bg-card flex flex-col" data-testid="sidebar">
        <a href="https://mg-vms.com" target="_blank" rel="noopener noreferrer"
           className="h-14 flex items-center gap-2.5 px-4 border-b border-border hover:bg-secondary/40 transition-colors"
           data-testid="sidebar-brand-link" title="mg-vms.com">
          <Logo size={36} className="w-9 h-9 shrink-0" data-testid="sidebar-logo" />
          <div className="leading-none">
            <div className="font-head font-black text-base tracking-tight">MG-VMS</div>
            <div className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground">MG Informatique</div>
          </div>
        </a>
        <nav className="flex-1 overflow-y-auto py-3">
          {NAV.map((g) => (
            <div key={g.group} className="mb-4">
              <div className="px-4 mb-1 text-[10px] uppercase tracking-[0.18em] text-muted-foreground font-medium">{t(g.group)}</div>
              {g.items
                .filter((it) => (!it.role || can(it.role)) && (!it.perm || hasPerm(it.perm)))
                .map((it) => it.children
                  ? <NavGroupItem key={it.key} item={it} t={t} can={can} hasPerm={hasPerm} />
                  : <NavLeafItem key={it.to} item={it} t={t} />)}
            </div>
          ))}
        </nav>
        <div className="border-t border-border p-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="w-full flex items-center gap-2 px-1 py-1 hover:bg-secondary transition-colors" data-testid="user-menu-trigger">
                <div className="w-8 h-8 bg-secondary flex items-center justify-center text-xs font-head font-bold shrink-0">
                  {(user?.name || "U").slice(0, 2).toUpperCase()}
                </div>
                <div className="leading-tight min-w-0 text-left">
                  <div className="text-xs font-medium truncate">{user?.name}</div>
                  <div className="text-[10px] uppercase tracking-wider text-[#0044FF]">{user?.role}</div>
                </div>
                <ChevronDown size={14} className="ml-auto text-muted-foreground shrink-0" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top" className="w-56" data-testid="user-menu-content">
              <DropdownMenuItem onSelect={(e) => { e.preventDefault(); setAboutOpen(true); }} data-testid="about-menu-item">
                <Info size={14} /> {t("nav.about")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => { logout(); navigate("/login"); }} data-testid="logout-btn">
                <LogOut size={14} /> {t("nav.logout")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} t={t} isAdmin={user?.role === "admin"} lang={lang} />
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 shrink-0 border-b border-border bg-card flex items-center justify-between px-4 gap-4">
          <div className="flex items-center gap-5">
            {liveMetrics && (
              <span data-testid="live-indicator" className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider mg-online">
                <span className="w-1.5 h-1.5 rounded-full bg-[#00E676] rec-dot" /> LIVE
              </span>
            )}
            <MiniBar label="CPU" value={sys.cpu} icon={Cpu} />
            <MiniBar label="RAM" value={sys.ram} icon={MemoryStick} />
            <MiniBar label="STO" value={sys.storage} icon={HardDrive} />
            <GpuMiniBar gpu={sys.gpu} onClick={() => navigate("/gpu")} />
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => navigate("/alerts")} data-testid="topbar-alerts" className="relative p-2 hover:bg-secondary transition-colors">
              <Bell size={18} strokeWidth={1.5} />
              {alertCount > 0 && (
                <span className="absolute top-0.5 right-0.5 min-w-4 h-4 px-1 bg-[#FF3333] text-white text-[9px] font-bold flex items-center justify-center rounded-full">{alertCount}</span>
              )}
            </button>
            <button onClick={toggleLang} data-testid="lang-toggle" className="px-2 py-2 hover:bg-secondary transition-colors flex items-center gap-1 text-xs font-medium uppercase">
              <Languages size={16} strokeWidth={1.5} /> {lang}
            </button>
            <button onClick={toggleTheme} data-testid="theme-toggle" className="p-2 hover:bg-secondary transition-colors">
              {theme === "dark" ? <Sun size={18} strokeWidth={1.5} /> : <Moon size={18} strokeWidth={1.5} />}
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
    </>
  );
}
