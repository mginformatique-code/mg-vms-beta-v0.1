/**
 * MobileHome — onglet "Accueil" (v3.93, demande explicite après référence
 * à l'app Reolink) : liste des SITES plutôt qu'une liste plate de caméras
 * — MG-VMS est multi-site par construction (contrairement à Reolink, qui
 * n'a pas cette notion), donc l'équivalent naturel du "Home = mes
 * appareils" de Reolink est ici "Home = mes sites", chacun regroupant ses
 * caméras. Tap sur un site → `MobileCameras` filtrée à ce site.
 *
 * v3.98 · En-tête "bienvenue" ajouté (demande explicite) — mêmes sources
 * que `WelcomeCenter.jsx`/`Layout.jsx` desktop : `GET /welcome/summary`
 * pour le message d'accueil selon l'heure + la version installée (mêmes
 * clés i18n `welcome.greeting_*` déjà utilisées côté desktop, aucune
 * duplication de texte), `GET /dashboard/stats` pour CPU/RAM/GPU (même
 * endpoint que les mini-barres de la topbar desktop).
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Building2, Loader2, Cpu, MemoryStick, Zap } from "lucide-react";

function greetingKey() {
  const h = new Date().getHours();
  if (h < 6) return "welcome.greeting_night";
  if (h < 12) return "welcome.greeting_morning";
  if (h < 18) return "welcome.greeting_afternoon";
  return "welcome.greeting_evening";
}

function MiniStat({ icon: Icon, value, active = true }) {
  const color = !active ? "#666" : value > 80 ? "#FF3333" : value > 65 ? "#FFB800" : "#00E676";
  return (
    <div className="flex items-center gap-1.5">
      <Icon size={13} strokeWidth={1.5} className="text-muted-foreground" />
      <div className="w-10 h-1.5 bg-secondary rounded-full overflow-hidden">
        <div style={{ width: `${active ? value : 0}%`, backgroundColor: color }} className="h-full" />
      </div>
      <span className="text-[10px] mono w-8">{active ? `${value}%` : "N/A"}</span>
    </div>
  );
}

function WelcomeHeader() {
  const { t, user } = useApp();
  const [sys, setSys] = useState(null);
  const [version, setVersion] = useState(null);

  useEffect(() => {
    let alive = true;
    api.get("/dashboard/stats").then((r) => { if (alive) setSys(r.data.system); }).catch(() => {});
    api.get("/welcome/summary").then((r) => { if (alive) setVersion(r.data.version); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  return (
    <div className="p-3 border-b border-border bg-card" data-testid="mobile-home-welcome">
      <div className="text-base font-head font-bold tracking-tight">
        {t(greetingKey())}, {user?.name}
      </div>
      <div className="text-[11px] text-muted-foreground mb-2" data-testid="mobile-home-version">
        MG-VMS {version?.installed || "—"}
      </div>
      {sys && (
        <div className="flex items-center gap-4 flex-wrap">
          <MiniStat icon={Cpu} value={sys.cpu} />
          <MiniStat icon={MemoryStick} value={sys.ram} />
          <MiniStat icon={Zap} value={sys.gpu?.available ? sys.gpu.gpu_util_pct : 0} active={!!sys.gpu?.available} />
        </div>
      )}
    </div>
  );
}

export default function MobileHome() {
  const { t } = useApp();
  const navigate = useNavigate();
  const [sites, setSites] = useState(null);
  const [cams, setCams] = useState([]);

  useEffect(() => {
    let alive = true;
    const load = () => Promise.all([api.get("/sites"), api.get("/cameras")])
      .then(([sRes, cRes]) => { if (alive) { setSites(sRes.data || []); setCams(cRes.data || []); } })
      .catch(() => { if (alive) setSites([]); });
    load();
    const iv = setInterval(load, 20000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  if (sites === null) {
    return (
      <div className="h-full flex flex-col">
        <WelcomeHeader />
        <div className="flex-1 flex items-center justify-center text-muted-foreground" data-testid="mobile-home-loading">
          <Loader2 size={20} className="animate-spin" />
        </div>
      </div>
    );
  }

  if (sites.length === 0) {
    return (
      <div className="h-full flex flex-col">
        <WelcomeHeader />
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm px-6 text-center" data-testid="mobile-home-empty">
          {t("mobile.home_no_sites")}
        </div>
      </div>
    );
  }

  return (
    <div data-testid="mobile-home-sites">
      <WelcomeHeader />
      <div className="p-2 flex flex-col gap-1.5">
        {sites.map((site) => {
          const siteCams = cams.filter((c) => c.site_id === site.id);
          const online = siteCams.filter((c) => c.status === "online").length;
          return (
            <button key={site.id}
                    onClick={() => navigate("/m/cameras", { state: { siteId: site.id, siteName: site.name } })}
                    data-testid="mobile-home-site-row"
                    className="flex items-center gap-3 rounded-xl border border-border bg-card p-3 text-left">
              <div className="w-10 h-10 shrink-0 flex items-center justify-center bg-secondary rounded-lg">
                <Building2 size={18} className="text-muted-foreground" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{site.name}</div>
                <div className="text-[11px] text-muted-foreground">
                  {site.camera_count ?? siteCams.length} {t("mobile.cameras_suffix")}
                </div>
              </div>
              <div className="flex items-center gap-1.5 shrink-0 text-[11px] text-muted-foreground">
                <span className="w-1.5 h-1.5 rounded-full bg-[#00E676]" /> {online}
                <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground ml-1.5" /> {siteCams.length - online}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
