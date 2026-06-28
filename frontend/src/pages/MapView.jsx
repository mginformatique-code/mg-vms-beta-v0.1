import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Building2, Cctv, MapPin, Wifi, WifiOff } from "lucide-react";

export default function MapView() {
  const { t } = useApp();
  const [sites, setSites] = useState([]);
  const [cams, setCams] = useState([]);
  const [active, setActive] = useState(null);

  useEffect(() => {
    api.get("/sites").then((r) => { setSites(r.data); if (r.data[0]) setActive(r.data[0]); });
    api.get("/cameras").then((r) => setCams(r.data));
  }, []);

  const center = active || { lat: 45.764, lng: 4.8357 };
  const d = 0.02;
  const bbox = `${center.lng - d},${center.lat - d},${center.lng + d},${center.lat + d}`;
  const mapUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${center.lat},${center.lng}`;
  const siteCams = cams.filter((c) => !active || c.site_id === active.id);

  return (
    <div className="p-4 h-full flex flex-col">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-4">{t("map.title")}</h1>
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-4 gap-2 min-h-0">
        <div className="lg:col-span-1 border border-border bg-card overflow-y-auto">
          {sites.map((s) => (
            <button key={s.id} onClick={() => setActive(s)} data-testid="map-site-item"
              className={`w-full text-left px-3 py-3 border-b border-border hover:bg-secondary transition-colors ${active?.id === s.id ? "bg-secondary border-l-2 border-l-[#0044FF]" : ""}`}>
              <div className="flex items-center gap-2"><Building2 size={15} className="text-[#0044FF]" /><span className="font-medium text-sm">{s.name}</span></div>
              <div className="text-[10px] text-muted-foreground flex items-center gap-1 mt-1 ml-6"><Cctv size={11} /> {s.camera_count} {t("sites.cameras")} · {s.type}</div>
            </button>
          ))}
        </div>
        <div className="lg:col-span-3 flex flex-col gap-2 min-h-0">
          <div className="flex-1 border border-border bg-card overflow-hidden min-h-[300px]">
            <iframe title="map" src={mapUrl} className="w-full h-full" style={{ border: 0, filter: "grayscale(0.2)" }} data-testid="osm-map" />
          </div>
          <div className="border border-border bg-card p-3 max-h-44 overflow-y-auto">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{active?.name} — {t("nav.cameras")}</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-1">
              {siteCams.map((c) => (
                <div key={c.id} className="flex items-center gap-2 px-2 py-1.5 border border-border text-xs">
                  {c.status === "online" ? <Wifi size={12} className="mg-online" /> : <WifiOff size={12} className="mg-offline" />}
                  <span className="truncate flex-1">{c.name}</span>
                  <MapPin size={11} className="text-muted-foreground" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
