/**
 * MobileHome — onglet "Accueil" (v3.93, demande explicite après référence
 * à l'app Reolink) : liste des SITES plutôt qu'une liste plate de caméras
 * — MG-VMS est multi-site par construction (contrairement à Reolink, qui
 * n'a pas cette notion), donc l'équivalent naturel du "Home = mes
 * appareils" de Reolink est ici "Home = mes sites", chacun regroupant ses
 * caméras. Tap sur un site → `MobileCameras` filtrée à ce site.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Building2, Loader2 } from "lucide-react";

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
      <div className="h-full flex items-center justify-center text-muted-foreground" data-testid="mobile-home-loading">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  if (sites.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground text-sm px-6 text-center" data-testid="mobile-home-empty">
        {t("mobile.home_no_sites")}
      </div>
    );
  }

  return (
    <div className="p-2 flex flex-col gap-1.5" data-testid="mobile-home-sites">
      {sites.map((site) => {
        const siteCams = cams.filter((c) => c.site_id === site.id);
        const online = siteCams.filter((c) => c.status === "online").length;
        return (
          <button key={site.id}
                  onClick={() => navigate("/m/cameras", { state: { siteId: site.id, siteName: site.name } })}
                  data-testid="mobile-home-site-row"
                  className="flex items-center gap-3 border border-border bg-card p-3 text-left">
            <div className="w-10 h-10 shrink-0 flex items-center justify-center bg-secondary">
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
  );
}
