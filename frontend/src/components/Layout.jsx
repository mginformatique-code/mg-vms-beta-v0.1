import React, { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import {
  LayoutDashboard, Grid3x3, Cctv, Building2, ScanLine, Car, Bell, Map,
  ScrollText, Users, Settings, LogOut, Moon, Sun, Languages, ShieldCheck, Cpu, HardDrive, MemoryStick,
} from "lucide-react";

const NAV = [
  { group: "nav.operations", items: [
    { to: "/", icon: LayoutDashboard, key: "nav.dashboard", end: true },
    { to: "/live", icon: Grid3x3, key: "nav.live" },
    { to: "/cameras", icon: Cctv, key: "nav.cameras" },
    { to: "/sites", icon: Building2, key: "nav.sites" },
    { to: "/map", icon: Map, key: "nav.map" },
  ]},
  { group: "nav.intelligence", items: [
    { to: "/anpr", icon: ScanLine, key: "nav.anpr" },
    { to: "/vehicles", icon: Car, key: "nav.vehicles" },
    { to: "/alerts", icon: Bell, key: "nav.alerts" },
  ]},
  { group: "nav.admin", items: [
    { to: "/audit", icon: ScrollText, key: "nav.audit", role: "technician" },
    { to: "/users", icon: Users, key: "nav.users", role: "admin" },
    { to: "/settings", icon: Settings, key: "nav.settings" },
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

export default function Layout({ children }) {
  const { t, user, logout, theme, toggleTheme, lang, toggleLang, can } = useApp();
  const navigate = useNavigate();
  const [sys, setSys] = useState({ cpu: 0, ram: 0, storage: 0 });
  const [alertCount, setAlertCount] = useState(0);

  useEffect(() => {
    const load = () => {
      api.get("/dashboard/stats").then((r) => {
        setSys(r.data.system);
        setAlertCount(r.data.alerts_active);
      }).catch(() => {});
    };
    load();
    const i = setInterval(load, 15000);
    return () => clearInterval(i);
  }, []);

  return (
    <div className="h-screen flex overflow-hidden bg-background text-foreground">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-border bg-card flex flex-col" data-testid="sidebar">
        <div className="h-14 flex items-center gap-2 px-4 border-b border-border">
          <div className="w-8 h-8 bg-primary flex items-center justify-center">
            <ShieldCheck size={18} className="text-primary-foreground" strokeWidth={2} />
          </div>
          <div className="leading-none">
            <div className="font-head font-black text-base tracking-tight">MG-VMS</div>
            <div className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground">MG Informatique</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto py-3">
          {NAV.map((g) => (
            <div key={g.group} className="mb-4">
              <div className="px-4 mb-1 text-[10px] uppercase tracking-[0.18em] text-muted-foreground font-medium">{t(g.group)}</div>
              {g.items.filter((it) => !it.role || can(it.role)).map((it) => (
                <NavLink key={it.to} to={it.to} end={it.end}
                  data-testid={`nav-${it.key.split(".")[1]}`}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-4 py-2 text-sm transition-colors border-l-2 ${
                      isActive ? "border-l-[#0044FF] bg-secondary text-foreground font-medium"
                               : "border-l-transparent text-muted-foreground hover:bg-secondary hover:text-foreground"
                    }`}>
                  <it.icon size={17} strokeWidth={1.5} />
                  {t(it.key)}
                </NavLink>
              ))}
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
            <MiniBar label="CPU" value={sys.cpu} icon={Cpu} />
            <MiniBar label="RAM" value={sys.ram} icon={MemoryStick} />
            <MiniBar label="STO" value={sys.storage} icon={HardDrive} />
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
