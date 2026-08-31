/**
 * CameraCenterDispatch — v3.19
 *
 * Route landing pour /camera-center (sans :cameraId dans l'URL).
 *
 * v1.0-rc4 : redirigeait sans rien afficher vers /cameras — "Centre
 * caméras" n'avait donc aucun affichage propre, c'était un lien mort.
 *
 * v3.19 : grille technique simple, volontairement réduite aux champs
 * qui n'existent NULLE PART ailleurs dans l'appli pour ne rien dupliquer —
 *   - IP / mode / résolution / codec / PTZ → déjà dans Appareils (table)
 *   - miniatures vidéo → déjà dans Live
 *   - MTBF / coupures / historique → déjà dans le tableau de bord santé
 *   - compteurs total/en ligne/hors ligne → déjà sur le Dashboard
 * Reste : quels plugins IA tournent réellement sur chaque caméra (ANPR
 * actif ou non, nombre de plugins) — champ jamais affiché ailleurs sous
 * cette forme. Clic sur une carte → Appareils (édition/gestion complète).
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Wifi, WifiOff, ScanLine, Search } from "lucide-react";

export default function CameraCenterDispatch() {
  const navigate = useNavigate();
  const [cams, setCams] = useState(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.get("/cameras").then((r) => setCams(r.data || [])).catch(() => setCams([]));
  }, []);

  if (cams === null) return null;

  const filtered = q
    ? cams.filter((c) => (c.name || "").toLowerCase().includes(q.toLowerCase()) || (c.site_name || "").toLowerCase().includes(q.toLowerCase()))
    : cams;

  return (
    <div className="p-6" data-testid="camera-center-overview">
      <div className="flex items-center justify-between gap-4 mb-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Centre caméras</h1>
          <p className="text-sm text-muted-foreground mt-1">Vue technique rapide — cliquez une caméra pour l'ouvrir dans Appareils.</p>
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filtrer…" data-testid="camera-center-filter"
                 className="pl-8 pr-3 py-1.5 bg-background border border-input outline-none text-sm w-48 focus:border-[#0044FF]" />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {filtered.map((c) => {
          const pluginCount = (c.enabled_plugins || []).length;
          const anprActive = (c.enabled_plugins || []).includes("fast-alpr");
          return (
            <button key={c.id} onClick={() => navigate("/cameras")} data-testid="camera-center-card"
                    className="text-left bg-card border border-border p-3 hover:border-[#0044FF] transition-colors">
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <span className="font-medium text-sm truncate">{c.name}</span>
                <span className={`flex items-center gap-1 text-[10px] uppercase tracking-wider shrink-0 ${c.status === "online" ? "text-[#00E676]" : "text-[#FF3333]"}`}>
                  {c.status === "online" ? <Wifi size={12} /> : <WifiOff size={12} />}
                  {c.status === "online" ? "En ligne" : "Hors ligne"}
                </span>
              </div>
              <div className="text-xs text-muted-foreground mb-2 truncate">{c.site_name || "—"}</div>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[10px] px-1.5 py-0.5 border border-border text-muted-foreground">{pluginCount} plugin{pluginCount > 1 ? "s" : ""} IA</span>
                {anprActive && (
                  <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 border border-[#0044FF]/40 text-[#0044FF]">
                    <ScanLine size={10} /> ANPR
                  </span>
                )}
              </div>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div className="col-span-full text-center text-muted-foreground py-12 text-sm">Aucune caméra</div>
        )}
      </div>
    </div>
  );
}
