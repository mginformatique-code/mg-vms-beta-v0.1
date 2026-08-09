import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import api from "@/lib/api";
import {
  Zap, RefreshCw, Camera as CamIcon, Car, User, Truck, Bus as BusIcon,
  Bike, PawPrint, CreditCard, LayoutGrid, Sparkles, Loader2, X as XIcon,
} from "lucide-react";
import { toast } from "sonner";
import EventViewer from "@/components/EventViewer";
import { VehiclesSection, VehicleDrawer } from "@/pages/Vehicles";

const TYPE_COLORS = {
  "Personne": "#FF3333", "Voiture": "#0044FF", "Camion": "#0044FF", "Bus": "#0044FF",
  "Moto": "#0044FF", "Vélo": "#00E676", "Animal": "#FFB800", "Mouvement": "#FFB800",
};

// v1.0-rc4 · Fusion Événements/Véhicules : UNE seule vue avec chips de filtre.
// Le chip « Plaques » affiche l'intégralité de l'ancien module Véhicules
// (recherche IA, identités, anomalies, fiche complète). Zéro perte de feature.
const FILTERS = [
  { id: "tous",       label: "Tous",       icon: LayoutGrid, types: null },
  { id: "plaques",    label: "Plaques",    icon: CreditCard },
  { id: "vehicules",  label: "Véhicules",  icon: Car,        types: ["Voiture", "Camion", "Bus", "Moto"] },
  { id: "personnes",  label: "Personnes",  icon: User,       types: ["Personne"] },
  { id: "camions",    label: "Camions",    icon: Truck,      types: ["Camion"] },
  { id: "bus",        label: "Bus",        icon: BusIcon,    types: ["Bus"] },
  { id: "deux-roues", label: "Deux roues", icon: Bike,       types: ["Moto", "Vélo"] },
  { id: "animaux",    label: "Animaux",    icon: PawPrint,   types: ["Animal"] },
];

export default function Events() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filtre = searchParams.get("filtre") || "tous";
  const [events, setEvents] = useState([]);
  const [cams, setCams] = useState([]);
  const [cameraId, setCameraId] = useState("");
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [viewerIdx, setViewerIdx] = useState(null);
  const [historyPlate, setHistoryPlate] = useState(null); // fiche véhicule depuis le viewer
  // v1.0-rc4 · Recherche IA disponible sur TOUTE la vue Événements
  const [smart, setSmart] = useState("");
  const [smartLoading, setSmartLoading] = useState(false);
  const [smartResult, setSmartResult] = useState(null);

  const activeFilter = FILTERS.find((f) => f.id === filtre) || FILTERS[0];
  const isPlaques = filtre === "plaques";

  const runSmartSearch = useCallback(async () => {
    const q = smart.trim();
    if (!q) { setSmartResult(null); return; }
    setSmartLoading(true);
    try {
      const { data } = await api.post("/smart-search", { query: q });
      setSmartResult(data);
      toast.success(`${data.events_count || 0} événement(s) trouvé(s) pour « ${q} »`);
    } catch (e) {
      // v1.0-rc4 · Fallback : IA indisponible → revient au listing classique
      // sans casser la vue Events. Message explicite du backend (SMART_SEARCH_LLM_*).
      setSmartResult(null);
      const d = e.response?.data?.detail;
      toast.error(d?.message || d?.error || "Recherche IA indisponible — filtres classiques toujours actifs");
    } finally { setSmartLoading(false); }
  }, [smart]);

  const clearSmart = () => { setSmart(""); setSmartResult(null); };

  // Source affichée : résultats IA si une recherche est active, sinon flux normal
  const shown = smartResult ? (smartResult.events || []) : events;

  const setFiltre = (id) => {
    const next = new URLSearchParams(searchParams);
    if (id === "tous") next.delete("filtre"); else next.set("filtre", id);
    setSearchParams(next, { replace: true });
  };

  const load = useCallback(async () => {
    if (isPlaques) return;
    setLoading(true);
    try {
      const params = { limit: 60 };
      if (activeFilter.types) params.types = activeFilter.types.join(",");
      if (cameraId) params.camera_id = cameraId;
      const r = await api.get("/events", { params });
      setEvents(r.data);
      setTotal(parseInt(r.headers["x-total-count"] || r.data.length, 10));
    } catch (e) {} finally { setLoading(false); }
  }, [isPlaques, activeFilter, cameraId]);

  useEffect(() => { api.get("/cameras").then((r) => setCams(r.data)).catch(() => {}); }, []);
  useEffect(() => {
    if (isPlaques) return;
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [load, isPlaques]);

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="events-page">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Zap size={22} className="text-[#0044FF]" /> Événements
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {isPlaques
              ? "Historique par plaque — recherche IA, identités, fiches véhicule complètes."
              : <>Détections IA temps réel — <span className="mono">{total}</span> au total</>}
          </p>
        </div>
        {!isPlaques && (
          <div className="flex items-center gap-2 flex-wrap">
            <select data-testid="events-camera-filter" value={cameraId} onChange={(e) => setCameraId(e.target.value)} className="border border-border bg-card text-sm px-2 py-2 outline-none">
              <option value="">Toutes les caméras</option>
              {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button onClick={load} data-testid="events-refresh-btn" className="p-2 border border-border hover:bg-secondary"><RefreshCw size={15} className={loading ? "animate-spin" : ""} /></button>
          </div>
        )}
      </div>

      {/* v1.0-rc4 · Recherche IA — toutes recherches confondues (personnes,
          véhicules, caméra, horaire). Le chip Plaques a déjà sa recherche IA
          dédiée (groupée par plaque) dans sa section. */}
      {!isPlaques && (
        <div className="flex items-center gap-2 max-w-3xl" data-testid="events-smart-search">
          <div className="relative flex-1">
            <Sparkles size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#0044FF]" />
            <input
              value={smart}
              onChange={(e) => setSmart(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSmartSearch()}
              data-testid="events-smart-input"
              placeholder="Recherche IA : « personne à 12h au téléphone », « voiture devant la cam 12 à 12h », « camions ce matin »…"
              className="w-full pl-9 pr-8 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]"
            />
            {smart && (
              <button onClick={clearSmart} data-testid="events-smart-clear"
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                <XIcon size={13} />
              </button>
            )}
          </div>
          <button
            onClick={runSmartSearch}
            disabled={smartLoading || !smart.trim()}
            data-testid="events-smart-btn"
            className="flex items-center gap-1 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40"
          >
            {smartLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={13} />}
            Recherche IA
          </button>
        </div>
      )}

      {/* Filtres IA détectés + reset */}
      {!isPlaques && smartResult && (
        <div className="border border-[#0044FF]/40 bg-[#0044FF]/5 p-2 text-[11px] mono flex flex-wrap gap-2 items-center" data-testid="events-smart-filters">
          <span className="text-[#0044FF] font-medium">
            {(smartResult.events || []).length} événement(s) pour « {smartResult.query} »
          </span>
          {Object.entries(smartResult.filters || {})
            .filter(([_, v]) => v && (Array.isArray(v) ? v.length : true))
            .map(([k, v]) => (
              <span key={k} className="px-1.5 py-0.5 border border-[#0044FF]/40 text-[#0044FF]">
                {k}: {Array.isArray(v) ? v.join(",") : String(v)}
              </span>
            ))}
          <button onClick={clearSmart} data-testid="events-smart-reset"
                  className="ml-auto text-[10px] uppercase tracking-wider text-[#0044FF] hover:underline">
            Réinitialiser
          </button>
        </div>
      )}


      {/* Chips de filtre — vue unifiée */}
      <div className="flex items-center gap-1.5 flex-wrap" data-testid="events-filter-chips">
        {FILTERS.map((f) => {
          const F = f.icon;
          const active = filtre === f.id;
          return (
            <button
              key={f.id}
              onClick={() => setFiltre(f.id)}
              data-testid={`events-filter-${f.id}`}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs border transition-colors ${
                active
                  ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF] font-medium"
                  : "border-border hover:border-[#0044FF]/60 text-muted-foreground hover:text-foreground"
              }`}
            >
              <F size={13} /> {f.label}
            </button>
          );
        })}
      </div>

      {isPlaques ? (
        <VehiclesSection embedded />
      ) : shown.length === 0 ? (
        <div className="text-muted-foreground text-sm py-20 text-center" data-testid="events-empty">
          {smartResult ? "Aucun événement ne correspond à cette recherche IA." : "Aucun événement détecté pour ces filtres."}
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
          {shown.map((e, i) => (
            <button key={e.id} onClick={() => setViewerIdx(i)} className="border border-border bg-card overflow-hidden text-left hover:border-[#0044FF] transition-colors" data-testid="event-card">
              <div className="relative bg-black aspect-video cursor-zoom-in">
                {e.thumbnail ? (
                  <img src={e.thumbnail} alt={e.type} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center"><CamIcon size={20} className="text-white/30" /></div>
                )}
                <span className="absolute top-1.5 left-1.5 text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 text-white" style={{ backgroundColor: TYPE_COLORS[e.type] || "#0044FF" }}>{e.type}</span>
                {e.confidence != null && <span className="absolute top-1.5 right-1.5 text-[10px] mono px-1.5 py-0.5 bg-black/70 text-white">{Math.round(e.confidence * 100)}%</span>}
                {e.plate && (
                  <span className="absolute bottom-1.5 left-1.5 text-[10px] mono font-bold px-1.5 py-0.5 bg-white text-black border border-black/40" data-testid="event-plate-badge">{e.plate}</span>
                )}
              </div>
              <div className="px-2.5 py-2 space-y-0.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs truncate">{e.camera_name}</span>
                  {e.vehicle_color && <span className="text-[10px] px-1.5 border border-border text-muted-foreground shrink-0">{e.vehicle_color}</span>}
                  {e.motion_pct != null && <span className="text-[10px] mono text-muted-foreground shrink-0">{e.motion_pct}%</span>}
                </div>
                <div className="text-[10px] mono text-muted-foreground" data-testid="event-timestamp">{new Date(e.timestamp).toLocaleString("fr-FR")}</div>
              </div>
            </button>
          ))}
        </div>
      )}

      {viewerIdx !== null && (
        <EventViewer
          items={shown}
          index={viewerIdx}
          onIndex={setViewerIdx}
          onClose={() => setViewerIdx(null)}
          onOpenPlate={(p) => { setHistoryPlate(p); }}
          kind="event"
        />
      )}

      {/* Fiche véhicule complète ouverte depuis le viewer (historique plaque/véhicule) */}
      <VehicleDrawer plate={historyPlate} onClose={() => setHistoryPlate(null)} />
    </div>
  );
}
