import React, { useEffect, useState } from "react";
import { NavLink, useNavigate, useLocation } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import Logo from "@/components/Logo";
import {
  LayoutDashboard, Grid3x3, Cctv, Building2, ScanLine, Car, Bell, Map, Zap,
  ScrollText, Users, Settings, LogOut, Moon, Sun, Languages, Cpu, HardDrive, MemoryStick, BellRing, Puzzle, Film, Network, FileText, Server, Radio, Brain, Activity, ScanFace, Thermometer, Radar, Plane, DoorOpen, MapPin, Clock, Layers, ChevronDown, ChevronRight, LineChart, Sparkles, ShieldCheck,
} from "lucide-react";

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
    { to: "/live", icon: Grid3x3, key: "nav.live", perm: "view_live" },
    { to: "/recordings", icon: Film, key: "nav.recordings", perm: "view_recordings" },
    { to: "/cameras", icon: Cctv, key: "nav.cameras" },
    { to: "/sites", icon: Building2, key: "nav.sites" },
    { to: "/map", icon: Map, key: "nav.map" },
  ]},
  { group: "nav.events_group", items: [
    // Vrai sous-menu Événements
    { key: "nav.events_root", icon: Zap, children: [
      { to: "/events", key: "nav.events_item", icon: Zap },
      { to: "/alerts", key: "nav.alerts", icon: Bell },
      { to: "/vehicles", key: "nav.vehicles", icon: Car, perm: "read_plates" },
    ]},
  ]},
  { group: "nav.intelligence", items: [
    { to: "/smart-zones", icon: MapPin, key: "nav.smart_zones" },
    { to: "/workflows", icon: Zap, key: "nav.workflows" },
  ]},
  { group: "nav.admin", items: [
    { to: "/pipeline-center", icon: LineChart, key: "nav.pipeline_center", role: "technician" },
    { to: "/security-center", icon: ShieldCheck, key: "nav.security_center", role: "admin" },
    { to: "/network", icon: Network, key: "nav.network", role: "client" },
    { to: "/plugins", icon: Puzzle, key: "nav.plugins", role: "admin" },
    { to: "/users", icon: Users, key: "nav.users", role: "admin" },
  ]},
  { group: "nav.logs_reports", items: [
    { to: "/reports", icon: FileText, key: "nav.reports", role: "technician" },
    { to: "/audit", icon: ScrollText, key: "nav.audit", role: "technician" },
    { to: "/diagnostics", icon: Activity, key: "nav.diagnostics", role: "technician" },
  ]},
  { group: "nav.settings_group", items: [
    { to: "/settings", icon: Settings, key: "nav.settings" },
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
  const activeChild = children.some((c) => location.pathname === c.to);
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
            return (
              <NavLink
                key={c.to}
                to={c.to}
                end={c.end}
                data-testid={`nav-${c.key.split(".")[1]}`}
                className={({ isActive }) =>
                  `flex items-center gap-2 pl-11 pr-4 py-1.5 text-[13px] transition-colors border-l-2 ${
                    isActive
                      ? "border-l-[#0044FF] bg-secondary text-foreground font-medium"
                      : "border-l-transparent text-muted-foreground/90 hover:bg-secondary hover:text-foreground"
                  }`
                }
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

export default function Layout({ children }) {
  const { t, user, logout, theme, toggleTheme, lang, toggleLang, can, hasPerm, liveMetrics, alertPing } = useApp();
  const navigate = useNavigate();
  const [sys, setSys] = useState({ cpu: 0, ram: 0, storage: 0, gpu: { available: false } });
  const [alertCount, setAlertCount] = useState(0);

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
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 bg-secondary flex items-center justify-center text-xs font-head font-bold">
              {(user?.name || "U").slice(0, 2).toUpperCase()}
            </div>
            <div className="leading-tight min-w-0">
              <div className="text-xs font-medium truncate">{user?.name}</div>
              <div className="text-[10px] uppercase tracking-wider text-[#0044FF]">{user?.role}</div>
            </div>
          </div>
          <button onClick={() => { logout(); navigate("/login"); }} data-testid="logout-btn"
            className="w-full flex items-center justify-center gap-2 px-3 py-1.5 text-xs border border-border hover:bg-secondary transition-colors">
            <LogOut size={14} /> {t("nav.logout")}
          </button>
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
  );
}
