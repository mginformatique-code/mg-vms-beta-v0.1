import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import VirtualGrid from "@/components/VirtualGrid";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Search, Car, Camera as CameraIcon, Clock, Route as RouteIcon,
  Activity, BarChart3, Loader2, Info, ChevronDown, ChevronRight,
  AlertTriangle, ShieldAlert, ShieldCheck, Shield, Bell, X as XIcon,
  CheckCircle2, GitMerge, Sparkles, Users, Link2,
} from "lucide-react";
import { toast } from "sonner";

/**
 * Vehicle History Center — v0.6 Smart ANPR History
 *
 * Regroupe automatiquement les lectures ANPR par plaque et présente une
 * fiche véhicule complète : galerie, timeline, heatmap, caméras visitées,
 * parcours, habitudes.
 */
export default function Vehicles() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [openPlate, setOpenPlate] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  // Smart search
  const [smart, setSmart] = useState(""); // AI query
  const [smartLoading, setSmartLoading] = useState(false);
  const [smartResult, setSmartResult] = useState(null); // {filters, vehicles, persons}
  const [advOpen, setAdvOpen] = useState(false);
  const [adv, setAdv] = useState({ colors: "", makes: "", types: "", date_from: "", date_to: "" });
  const [history, setHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem("smart_search_history") || "[]"); }
    catch { return []; }
  });
  // Identities
  const [identities, setIdentities] = useState([]);
  const [identityCandidates, setIdentityCandidates] = useState([]);
  const [showCandidates, setShowCandidates] = useState(false);

  const loadAnomalies = useCallback(async () => {
    try {
      const { data } = await api.get("/vehicles/anomalies/recent", { params: { since_hours: 48, limit: 8 } });
      setAnomalies(data.items || []);
    } catch { /* silent */ }
  }, []);

  const loadIdentities = useCallback(async () => {
    try {
      const [{ data: list }, { data: cand }] = await Promise.all([
        api.get("/vehicles/identities"),
        api.get("/vehicles/identities/detect", { params: { min_plates: 2 } }),
      ]);
      setIdentities(list.items || []);
      setIdentityCandidates(cand.items || []);
    } catch { /* silent */ }
  }, []);

  const runSmartSearch = useCallback(async (queryOverride) => {
    const q = (typeof queryOverride === "string" ? queryOverride : smart).trim();
    if (!q) { setSmartResult(null); return; }
    if (typeof queryOverride === "string") setSmart(q);
    setSmartLoading(true);
    try {
      const { data } = await api.post("/smart-search", { query: q });
      setSmartResult(data);
      // Sauvegarde historique (5 dernières)
      try {
        const hist = JSON.parse(localStorage.getItem("smart_search_history") || "[]");
        const next = [{ query: q, at: Date.now(), vehicles: data.vehicles_count, persons: data.persons_count, target: data.target },
                       ...hist.filter((h) => h.query !== q)].slice(0, 5);
        localStorage.setItem("smart_search_history", JSON.stringify(next));
        setHistory(next);
      } catch { /* ignore */ }
      const total = (data.vehicles_count || 0) + (data.persons_count || 0);
      toast.success(`${total} résultat${total > 1 ? "s" : ""} trouvé${total > 1 ? "s" : ""}`);
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || "Recherche IA impossible");
    } finally { setSmartLoading(false); }
  }, [smart]);

  const clearSmart = () => { setSmart(""); setSmartResult(null); };

  const runAdvancedSearch = useCallback(async () => {
    // Applique les filtres avancés au load classique en construisant une query simple.
    const parts = [];
    if (adv.colors) parts.push(adv.colors);
    if (adv.makes) parts.push(adv.makes);
    if (adv.types) parts.push(adv.types);
    let query = parts.join(" ") || q;
    if (adv.date_from) query += ` du ${adv.date_from}`;
    if (adv.date_to) query += ` au ${adv.date_to}`;
    if (query.trim()) { setSmart(query); setTimeout(runSmartSearch, 50); }
  }, [adv, q, runSmartSearch]);

  const load = useCallback(async (search = "") => {
    setLoading(true);
    try {
      const { data } = await api.get("/vehicles", {
        params: { q: search, limit: 60, offset: 0 },
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      toast.error("Impossible de charger les véhicules");
    } finally {
      setLoading(false);
    }
  }, []);

  // Chargement initial + refresh 30 s (pausé si le drawer est ouvert)
  useEffect(() => { load(""); loadAnomalies(); loadIdentities(); }, [load, loadAnomalies, loadIdentities]);
  useEffect(() => {
    if (openPlate) return; // pause pendant l'ouverture du drawer
    const iv = setInterval(() => { load(q); loadAnomalies(); }, 30000);
    return () => clearInterval(iv);
  }, [openPlate, q, load, loadAnomalies]);

  return (
    <div className="p-4" data-testid="vehicles-page">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <Car size={26} /> Véhicules
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Historique par véhicule — cliquez sur une carte pour ouvrir la fiche complète.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-1 max-w-2xl">
          <div className="relative flex-1">
            <Sparkles size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#0044FF]" />
            <input
              value={smart}
              onChange={(e) => setSmart(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSmartSearch()}
              data-testid="smart-search-input"
              placeholder="Recherche IA : « voitures rouges hier », « plaque L3863 », « camions ce matin »…"
              className="w-full pl-9 pr-24 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]"
            />
            {smart && (
              <button onClick={clearSmart}
                      data-testid="smart-clear"
                      className="absolute right-14 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs">
                <XIcon size={13} />
              </button>
            )}
            <button
              onClick={() => setAdvOpen((o) => !o)}
              data-testid="adv-toggle"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground border border-border px-1.5 py-0.5"
              title="Filtres avancés"
            >
              Filtres
            </button>
          </div>
          <button
            onClick={runSmartSearch}
            disabled={smartLoading || !smart.trim()}
            data-testid="smart-search-btn"
            className="flex items-center gap-1 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40"
          >
            {smartLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={13} />}
            Recherche IA
          </button>
        </div>
      </div>

      {advOpen && (
        <div className="border border-border bg-card p-3 mb-3 grid grid-cols-2 md:grid-cols-5 gap-2 text-xs" data-testid="advanced-search">
          <div>
            <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Couleur</label>
            <input value={adv.colors} onChange={(e) => setAdv({ ...adv, colors: e.target.value })} placeholder="rouge, noir…" className="w-full px-2 py-1.5 bg-background border border-input outline-none" data-testid="adv-colors" />
          </div>
          <div>
            <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Marque</label>
            <input value={adv.makes} onChange={(e) => setAdv({ ...adv, makes: e.target.value })} placeholder="Toyota, Peugeot…" className="w-full px-2 py-1.5 bg-background border border-input outline-none" />
          </div>
          <div>
            <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Type</label>
            <input value={adv.types} onChange={(e) => setAdv({ ...adv, types: e.target.value })} placeholder="voiture, camion…" className="w-full px-2 py-1.5 bg-background border border-input outline-none" />
          </div>
          <div>
            <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Du</label>
            <input type="date" value={adv.date_from} onChange={(e) => setAdv({ ...adv, date_from: e.target.value })} className="w-full px-2 py-1.5 bg-background border border-input outline-none mono" />
          </div>
          <div>
            <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Au</label>
            <input type="date" value={adv.date_to} onChange={(e) => setAdv({ ...adv, date_to: e.target.value })} className="w-full px-2 py-1.5 bg-background border border-input outline-none mono" />
          </div>
          <div className="col-span-2 md:col-span-5 flex justify-end">
            <button onClick={runAdvancedSearch}
                    data-testid="adv-apply"
                    className="text-[10px] uppercase tracking-wider px-3 py-1.5 border border-[#0044FF] text-[#0044FF] hover:bg-[#0044FF]/10">
              Appliquer les filtres
            </button>
          </div>
        </div>
      )}

      <div className="text-xs text-muted-foreground mono mb-3 flex items-center justify-between" data-testid="vehicles-count">
        <span>
          {smartResult
            ? `${(smartResult.vehicles_count || 0)} véhicule(s) + ${(smartResult.persons_count || 0)} personne(s) pour « ${smartResult.query} »`
            : `${items.length} véhicule${items.length > 1 ? "s" : ""} affiché${items.length > 1 ? "s" : ""} sur ${total}`}
        </span>
        {smartResult && (
          <button onClick={clearSmart} data-testid="smart-clear-inline"
                  className="text-[10px] uppercase tracking-wider text-[#0044FF] hover:underline">
            Réinitialiser la recherche
          </button>
        )}
      </div>

      {history.length > 0 && !smartResult && (
        <div className="mb-3 flex items-center gap-2 flex-wrap text-[11px]" data-testid="search-history">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Recherches récentes :</span>
          {history.map((h, i) => (
            <button
              key={`${h.query}-${i}`}
              onClick={() => runSmartSearch(h.query)}
              data-testid={`history-${i}`}
              className="flex items-center gap-1 px-2 py-0.5 border border-border hover:border-[#0044FF] hover:text-[#0044FF] transition-colors"
              title={`${h.vehicles || 0} véhicules · ${h.persons || 0} personnes`}
            >
              <Sparkles size={10} className="text-[#0044FF]" />
              <span className="truncate max-w-[240px]">{h.query}</span>
            </button>
          ))}
          <button
            onClick={() => { localStorage.removeItem("smart_search_history"); setHistory([]); }}
            data-testid="history-clear"
            className="text-[9px] uppercase tracking-wider text-muted-foreground hover:text-foreground ml-auto"
          >
            Vider
          </button>
        </div>
      )}

      {smartResult?.filters && (
        <div className="border border-[#0044FF]/40 bg-[#0044FF]/5 p-2 mb-3 text-[11px] mono flex flex-wrap gap-2 items-center" data-testid="smart-filters">
          <span className="text-[#0044FF] font-medium">Filtres IA :</span>
          {Object.entries(smartResult.filters).filter(([_, v]) => v && (Array.isArray(v) ? v.length : true)).map(([k, v]) => (
            <span key={k} className="px-1.5 py-0.5 border border-[#0044FF]/40 text-[#0044FF]">
              {k}: {Array.isArray(v) ? v.join(",") : String(v)}
            </span>
          ))}
        </div>
      )}

      <IdentitiesPanel
        identities={identities}
        candidates={identityCandidates}
        show={showCandidates}
        onToggle={() => setShowCandidates((s) => !s)}
        onReload={loadIdentities}
        onOpenPlate={(p) => setOpenPlate(p)}
      />

      {anomalies.length > 0 && (
        <AnomaliesBanner items={anomalies} onOpen={(p) => setOpenPlate(p)} onDismiss={() => setAnomalies([])} />
      )}

      {items.length === 0 && !loading && (
        <div className="border border-border p-8 text-center text-muted-foreground">
          <Car size={48} className="mx-auto mb-2 opacity-30" />
          <div className="text-sm">Aucun véhicule détecté pour le moment.</div>
        </div>
      )}

      <div data-testid="vehicles-grid-root">
        <VirtualGrid
          items={smartResult ? (smartResult.vehicles || []) : items}
          renderItem={(v) => <VehicleCard v={v} onOpen={() => setOpenPlate(v.plate)} />}
          itemKey={(v) => v.plate}
          rowHeight={340}
          minColumnWidth={260}
          maxColumns={4}
          threshold={200}
          testid="vehicles-virtual-grid"
        />
      </div>

      {smartResult?.persons_count > 0 && (
        <PersonsSection persons={smartResult.persons || []} description={smartResult.filters?.object_description} />
      )}

      <VehicleDrawer
        plate={openPlate}
        onClose={() => setOpenPlate(null)}
        onWatchChanged={(plate, status) => {
          setItems((prev) => prev.map((it) => it.plate === plate ? { ...it, list_status: status } : it));
        }}
      />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// VehicleCard — effet cascade + badge +N
// ═══════════════════════════════════════════════════════════════════
function VehicleCard({ v, onOpen }) {
  const thumbUrl = (id, kind = "vehicle") =>
    id ? `${process.env.REACT_APP_BACKEND_URL}/api/vehicles/passage/${id}/thumb?kind=${kind}` : null;

  const previews = (v.preview_thumb_ids || []).slice(0, 3);
  const extra = Math.max(0, (v.passages_count || 0) - 1);

  return (
    <button
      onClick={onOpen}
      data-testid={`vehicle-card-${v.plate}`}
      className="text-left bg-card border border-border hover:border-[#0044FF] transition-all group p-3 flex flex-col gap-3"
    >
      {/* Effet cascade — 3 miniatures empilées */}
      <div className="relative h-40 mb-1">
        {previews.length === 0 && (
          <div className="w-full h-full bg-secondary/50 flex items-center justify-center text-muted-foreground text-xs">
            <Car size={40} className="opacity-30" />
          </div>
        )}
        {previews.map((id, idx) => {
          const isTop = idx === 0;
          // Empilement : cartes 2 & 3 décalées derrière, plus petites
          const style = {
            zIndex: previews.length - idx,
            transform: `translate(${idx * 8}px, ${idx * 6}px) scale(${1 - idx * 0.04})`,
            opacity: 1 - idx * 0.15,
          };
          return (
            <img
              key={id}
              src={thumbUrl(id, "vehicle")}
              alt={`Passage ${idx + 1}`}
              loading="lazy"
              className={`absolute inset-0 w-full h-full object-cover border border-border ${isTop ? "shadow-lg" : ""} transition-transform group-hover:scale-[1.02]`}
              style={style}
              onError={(e) => { e.target.style.display = "none"; }}
            />
          );
        })}
        {/* Badge +N */}
        {extra > 0 && (
          <span
            data-testid={`vehicle-badge-${v.plate}`}
            className="absolute top-1 left-1 z-20 text-[10px] font-bold px-2 py-0.5 bg-[#0044FF] text-white mono uppercase tracking-wider"
          >
            +{extra}
          </span>
        )}
      </div>

      {/* Plaque */}
      <div className="flex items-center gap-2">
        <PlateBadge value={v.plate} status={v.list_status} />
        {v.vehicle_color && (
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{v.vehicle_color}</span>
        )}
      </div>

      {/* Marque / modèle */}
      {(v.vehicle_make || v.vehicle_model) && (
        <div className="text-sm">{[v.vehicle_make, v.vehicle_model].filter(Boolean).join(" ")}</div>
      )}

      {/* Meta */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <div className="flex items-center gap-1"><Activity size={11} /> {v.passages_count} passages</div>
        <div className="flex items-center gap-1"><CameraIcon size={11} /> {v.cameras_count} caméra{v.cameras_count > 1 ? "s" : ""}</div>
        <div className="flex items-center gap-1 col-span-2"><Clock size={11} /> Dernier : {fmtRelative(v.last_seen)}</div>
      </div>
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════════
// VehicleDrawer — panneau latéral avec 6 onglets
// ═══════════════════════════════════════════════════════════════════
function VehicleDrawer({ plate, onClose, onWatchChanged }) {
  const open = !!plate;
  const [detail, setDetail] = useState(null);
  const reload = useCallback(() => {
    if (!plate) return;
    api.get(`/vehicles/${encodeURIComponent(plate)}`)
      .then(({ data }) => setDetail(data))
      .catch(() => toast.error("Impossible de charger la fiche véhicule"));
  }, [plate]);
  useEffect(() => {
    if (!plate) { setDetail(null); return; }
    reload();
  }, [plate, reload]);

  const handleWatchChanged = (newStatus) => {
    setDetail((d) => d ? { ...d, list_status: newStatus } : d);
    onWatchChanged && onWatchChanged(plate, newStatus);
  };

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="!w-full sm:!max-w-2xl overflow-y-auto p-0 bg-card" data-testid="vehicle-drawer">
        <SheetHeader className="border-b border-border p-4 sticky top-0 bg-card z-10">
          <SheetTitle className="font-head flex items-center gap-3">
            {detail && <PlateBadge value={detail.plate} status={detail.list_status} />}
            {!detail && <span className="text-muted-foreground text-sm">Chargement…</span>}
            {detail && (
              <span className="text-xs text-muted-foreground">
                {[detail.vehicle_make, detail.vehicle_model, detail.vehicle_color].filter(Boolean).join(" · ")}
              </span>
            )}
          </SheetTitle>
        </SheetHeader>

        {detail && (
          <Tabs defaultValue="overview" className="p-4">
            <TabsList className="grid grid-cols-6 rounded-none bg-secondary/40 border border-border h-auto p-0">
              <TabsTrigger value="overview"  className="rounded-none text-xs py-2" data-testid="tab-overview">Vue</TabsTrigger>
              <TabsTrigger value="gallery"   className="rounded-none text-xs py-2" data-testid="tab-gallery">Galerie</TabsTrigger>
              <TabsTrigger value="timeline"  className="rounded-none text-xs py-2" data-testid="tab-timeline">Timeline</TabsTrigger>
              <TabsTrigger value="heatmap"   className="rounded-none text-xs py-2" data-testid="tab-heatmap">Heatmap</TabsTrigger>
              <TabsTrigger value="cameras"   className="rounded-none text-xs py-2" data-testid="tab-cameras">Caméras</TabsTrigger>
              <TabsTrigger value="journey"   className="rounded-none text-xs py-2" data-testid="tab-journey">Parcours</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-4"><TabOverview d={detail} onWatchChanged={handleWatchChanged} /></TabsContent>
            <TabsContent value="gallery"  className="mt-4"><TabGallery plate={plate} /></TabsContent>
            <TabsContent value="timeline" className="mt-4"><TabTimeline plate={plate} /></TabsContent>
            <TabsContent value="heatmap"  className="mt-4"><TabHeatmap plate={plate} /></TabsContent>
            <TabsContent value="cameras"  className="mt-4"><TabCameras plate={plate} /></TabsContent>
            <TabsContent value="journey"  className="mt-4"><TabJourney plate={plate} /></TabsContent>
          </Tabs>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ─── Tabs contents ───────────────────────────────────────────────
function TabOverview({ d, onWatchChanged }) {
  const [habits, setHabits] = useState(null);
  const [anomaly, setAnomaly] = useState(null);
  const [wlSaving, setWlSaving] = useState(false);
  const [notifSending, setNotifSending] = useState(false);
  useEffect(() => {
    api.get(`/vehicles/${encodeURIComponent(d.plate)}/habits`).then(({ data }) => setHabits(data)).catch(() => {});
    api.get(`/vehicles/${encodeURIComponent(d.plate)}/anomaly`).then(({ data }) => setAnomaly(data)).catch(() => {});
  }, [d.plate]);

  const setWatch = async (listType) => {
    setWlSaving(true);
    try {
      // Retirer d'abord l'entrée existante pour cette plaque
      const { data: list } = await api.get("/watchlist");
      const existing = (list || []).find((w) => (w.plate || "").toUpperCase() === d.plate.toUpperCase());
      if (existing) {
        await api.delete(`/watchlist/${existing.id}`);
      }
      if (listType) {
        await api.post("/watchlist", { plate: d.plate, list_type: listType, reason: "" });
      }
      toast.success(listType ? `Plaque ajoutée à la liste ${listType === "black" ? "noire" : "blanche"}` : "Plaque retirée");
      onWatchChanged && onWatchChanged(listType || "none");
    } catch (e) {
      toast.error("Échec de la mise à jour de la liste");
    } finally { setWlSaving(false); }
  };

  const sendNotif = async () => {
    setNotifSending(true);
    try {
      const { data } = await api.post(`/vehicles/${encodeURIComponent(d.plate)}/notify-anomaly`);
      const channels = Object.entries(data.sent || {}).filter(([_, v]) => v === "sent").map(([k]) => k);
      if (channels.length) toast.success(`Notification envoyée sur : ${channels.join(", ")}`);
      else toast.info("Aucun canal de notification actif — configurez SMTP/Discord/Telegram dans les Notifications.");
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(detail?.message || "Notification impossible");
    } finally { setNotifSending(false); }
  };

  const current = d.list_status || "none";
  return (
    <div className="space-y-4" data-testid="drawer-overview">
      {d.best_thumb_id && (
        <img
          src={`${process.env.REACT_APP_BACKEND_URL}/api/vehicles/passage/${d.best_thumb_id}/thumb?kind=frame`}
          alt="Best thumbnail"
          className="w-full max-h-64 object-cover border border-border"
          onError={(e) => { e.target.style.display = "none"; }}
        />
      )}

      {/* Anomalie du dernier passage */}
      {anomaly && anomaly.severity !== "info" && anomaly.anomalies?.length > 0 && (
        <div
          className="border p-3 space-y-2 text-xs"
          style={{
            borderColor: anomaly.severity === "high" ? "#FF3333" : "#FFB800",
            background: anomaly.severity === "high" ? "rgba(255,51,51,0.06)" : "rgba(255,184,0,0.06)",
          }}
          data-testid="anomaly-block"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 font-medium" style={{ color: anomaly.severity === "high" ? "#FF3333" : "#FFB800" }}>
              <AlertTriangle size={13} /> Anomalie détectée
              <span className="text-[10px] uppercase tracking-wider mono ml-1">
                [{anomaly.severity}]
              </span>
            </div>
            <button
              onClick={sendNotif} disabled={notifSending}
              data-testid="notify-anomaly-btn"
              className="flex items-center gap-1 px-2 py-1 border text-[10px] uppercase tracking-wider hover:bg-secondary/60"
              style={{ borderColor: anomaly.severity === "high" ? "#FF3333" : "#FFB800" }}
            >
              {notifSending ? <Loader2 size={11} className="animate-spin" /> : <Bell size={11} />}
              Créer une alerte
            </button>
          </div>
          <div className="text-muted-foreground">{anomaly.message}</div>
          <div className="flex flex-wrap gap-1 pt-1">
            {anomaly.anomalies.map((a) => (
              <span key={a} className="text-[9px] mono uppercase px-1.5 py-0.5 border border-border">{a}</span>
            ))}
          </div>
        </div>
      )}

      {/* Consensus multi-plugins & validation manuelle */}
      <PlateConsensusBlock plate={d.plate} />

      {/* Actions Watchlist */}
      <div className="border border-border p-3 space-y-2" data-testid="watchlist-actions">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
          <Shield size={11} /> Watchlist
          <span className="ml-auto text-[10px] mono px-1.5 py-0.5"
                style={{
                  color: current === "black" ? "#FF3333" : current === "white" ? "#00E676" : "#888",
                  borderColor: current === "black" ? "#FF3333" : current === "white" ? "#00E676" : "#333",
                  border: "1px solid",
                }}>
            {current === "black" ? "LISTE NOIRE" : current === "white" ? "LISTE BLANCHE" : "AUCUNE"}
          </span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <button
            onClick={() => setWatch("black")}
            disabled={wlSaving || current === "black"}
            data-testid="watch-blacklist-btn"
            className={`flex items-center justify-center gap-1 px-2 py-2 border text-xs transition-colors ${current === "black" ? "border-[#FF3333] bg-[#FF3333]/10 text-[#FF3333]" : "border-border hover:border-[#FF3333] hover:text-[#FF3333]"}`}
          >
            <ShieldAlert size={12} /> Blacklist
          </button>
          <button
            onClick={() => setWatch("white")}
            disabled={wlSaving || current === "white"}
            data-testid="watch-whitelist-btn"
            className={`flex items-center justify-center gap-1 px-2 py-2 border text-xs transition-colors ${current === "white" ? "border-[#00E676] bg-[#00E676]/10 text-[#00E676]" : "border-border hover:border-[#00E676] hover:text-[#00E676]"}`}
          >
            <ShieldCheck size={12} /> Whitelist
          </button>
          <button
            onClick={() => setWatch(null)}
            disabled={wlSaving || current === "none"}
            data-testid="watch-remove-btn"
            className="flex items-center justify-center gap-1 px-2 py-2 border border-border text-xs hover:bg-secondary disabled:opacity-40"
          >
            {wlSaving ? <Loader2 size={11} className="animate-spin" /> : <XIcon size={12} />} Retirer
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <Stat label="Passages" value={d.passages_count} />
        <Stat label="Caméras" value={d.cameras_count} />
        <Stat label="Première apparition" value={fmtDateTime(d.first_seen)} />
        <Stat label="Dernier passage" value={fmtDateTime(d.last_seen)} />
        <Stat label="Confiance moyenne" value={d.avg_confidence != null ? `${(d.avg_confidence * 100).toFixed(0)}%` : "—"} />
        <Stat label="Durée moy. présence" value={d.avg_visit_duration_min != null ? `${d.avg_visit_duration_min} min` : "—"} />
        <Stat label="Marque" value={d.vehicle_make || "—"} />
        <Stat label="Modèle" value={d.vehicle_model || "—"} />
        <Stat label="Couleur" value={d.vehicle_color || "—"} />
        <Stat label="Type" value={d.vehicle_type || "—"} />
      </div>
      {habits && (habits.typical_arrival || habits.nocturnal_note || habits.typical_days?.length > 0) && (
        <div className="border border-border p-3 space-y-1.5 text-xs" data-testid="habits-block">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
            <Info size={11} /> Habitudes observées
          </div>
          {habits.typical_arrival && <div>Arrivée habituelle : <b className="mono">{habits.typical_arrival}</b></div>}
          {habits.typical_departure && <div>Départ habituel : <b className="mono">{habits.typical_departure}</b></div>}
          {habits.typical_days?.length > 0 && <div>Jours prédominants : <b>{habits.typical_days.join(", ")}</b></div>}
          {habits.nocturnal_note && (
            <div className="text-[#FFB800]">
              🌙 {habits.nocturnal_note} ({fmtDateTime(habits.nocturnal_first_seen)})
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Section Personnes (résultats smart-search cross-domain)
// ═══════════════════════════════════════════════════════════════════
function PersonsSection({ persons, description }) {
  return (
    <div className="mt-6" data-testid="persons-section">
      <div className="flex items-center gap-2 mb-3">
        <Users size={16} className="text-[#0044FF]" />
        <h2 className="font-head text-lg tracking-tight">Personnes détectées <span className="mono text-sm text-muted-foreground">({persons.length})</span></h2>
        {description && (
          <span className="text-xs text-muted-foreground italic">— « {description} » (tri visuel manuel)</span>
        )}
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-2">
        {persons.map((p) => (
          <a key={p.id}
             href={p.crop_thumbnail || "#"}
             target="_blank" rel="noreferrer"
             className="block bg-card border border-border hover:border-[#0044FF] transition-colors"
             data-testid={`person-${p.id}`}>
            {p.crop_thumbnail ? (
              <img src={p.crop_thumbnail} alt="" loading="lazy" className="w-full h-32 object-cover" />
            ) : (
              <div className="w-full h-32 bg-secondary/50 flex items-center justify-center">
                <Users size={20} className="opacity-40" />
              </div>
            )}
            <div className="p-1.5 text-[10px] mono">
              <div className="truncate">{p.type}</div>
              <div className="text-muted-foreground truncate">{p.camera_name}</div>
              <div className="flex items-center justify-between text-muted-foreground">
                <span>{fmtDateTime(p.timestamp)}</span>
                <span style={{ color: (p.confidence || 0) > 0.8 ? "#00E676" : "#FFB800" }}>
                  {((p.confidence || 0) * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Panneau Identités véhicule (cross-plate) · v0.7
// ═══════════════════════════════════════════════════════════════════
function IdentitiesPanel({ identities, candidates, show, onToggle, onReload, onOpenPlate }) {
  const [creating, setCreating] = useState(null); // signature en cours de création
  if (!identities.length && !candidates.length) return null;

  const promote = async (c) => {
    setCreating(c.signature);
    try {
      const name = [c.signature.make, c.signature.color, c.signature.type].filter(Boolean).join(" ").trim() || c.plates[0];
      await api.post("/vehicles/identities", {
        name, plates: c.plates,
        vehicle_make: c.signature.make,
        vehicle_color: c.signature.color,
        vehicle_type: c.signature.type,
        notes: "Créée depuis la détection auto",
      });
      toast.success(`Identité créée : ${name}`);
      onReload();
    } catch { toast.error("Création impossible"); }
    finally { setCreating(null); }
  };

  return (
    <div className="border border-border bg-secondary/30 p-3 mb-4" data-testid="identities-panel">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground">
          <Users size={13} className="text-[#0044FF]" />
          Identités véhicule
          <span className="mono">{identities.length}</span>
          {candidates.length > 0 && (
            <span className="text-[#FFB800] ml-2 flex items-center gap-1">
              <Link2 size={11} /> {candidates.length} candidat{candidates.length > 1 ? "s" : ""}
            </span>
          )}
        </div>
        {candidates.length > 0 && (
          <button onClick={onToggle}
                  data-testid="toggle-identity-candidates"
                  className="text-[10px] uppercase tracking-wider text-[#0044FF] hover:underline">
            {show ? "Masquer les candidats" : "Afficher les candidats"}
          </button>
        )}
      </div>

      {identities.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {identities.slice(0, 6).map((id) => (
            <div key={id.id} className="border border-[#0044FF]/40 bg-card px-2 py-1 text-[11px]" data-testid={`identity-${id.id}`}>
              <div className="font-medium">{id.name}</div>
              <div className="text-muted-foreground text-[10px]">
                {id.plates.length} plaque{id.plates.length > 1 ? "s" : ""} · {id.vehicle_make || "—"} {id.vehicle_color || ""}
              </div>
              <div className="flex flex-wrap gap-1 mt-1">
                {id.plates.slice(0, 4).map((p) => (
                  <button key={p} onClick={() => onOpenPlate(p)}
                          className="mono text-[9px] px-1 py-0.5 border border-border hover:bg-secondary"
                          data-testid={`identity-plate-${p}`}>
                    {p}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {show && candidates.length > 0 && (
        <div className="border-t border-border pt-2 space-y-1.5">
          {candidates.slice(0, 5).map((c, idx) => (
            <div key={idx} className="flex items-center gap-2 text-[11px]" data-testid={`identity-candidate-${idx}`}>
              <span className="text-muted-foreground w-40 truncate">
                {[c.signature.make, c.signature.color, c.signature.type].filter(Boolean).join(" · ")}
              </span>
              <span className="text-[10px] text-muted-foreground">{c.plates_count} plaques · {c.reads} lectures</span>
              <div className="flex flex-wrap gap-1 flex-1">
                {c.plates.slice(0, 6).map((p) => (
                  <span key={p} className="mono text-[9px] px-1 py-0.5 border border-border">{p}</span>
                ))}
              </div>
              <button onClick={() => promote(c)} disabled={creating === c.signature}
                      data-testid={`promote-identity-${idx}`}
                      className="text-[9px] uppercase tracking-wider px-2 py-1 border border-[#00E676] text-[#00E676] hover:bg-[#00E676]/10">
                {creating === c.signature ? <Loader2 size={10} className="animate-spin" /> : "Créer l'identité"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Consensus multi-plugins & Validation manuelle de la plaque (v0.7 preview)
// ═══════════════════════════════════════════════════════════════════
function PlateConsensusBlock({ plate }) {
  const [data, setData] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api.get(`/vehicles/${encodeURIComponent(plate)}/consensus`)
      .then(({ data }) => setData(data))
      .catch(() => setData(null));
  }, [plate]);
  useEffect(() => { load(); }, [load]);

  if (!data) return null;
  const val = data.validation;
  const isValidated = !!val;
  const canonical = isValidated ? val.canonical_plate : data.canonical_candidate;
  const candidates = data.candidates || [];
  const variants = data.variants_detected || [];
  const hasVariants = variants.length > 0;

  const validate = async (chosenCanonical) => {
    setSaving(true);
    try {
      const variantPlates = candidates
        .filter((c) => c.plate !== chosenCanonical)
        .map((c) => c.plate);
      await api.post(`/vehicles/${encodeURIComponent(plate)}/validate`, {
        canonical_plate: chosenCanonical,
        variants: variantPlates,
        reason: "Validation manuelle depuis le drawer véhicule",
      });
      toast.success(`Plaque « ${chosenCanonical} » validée · ${variantPlates.length} variante(s) liée(s)`);
      load();
    } catch { toast.error("Validation impossible"); }
    finally { setSaving(false); }
  };

  const unvalidate = async () => {
    setSaving(true);
    try {
      await api.delete(`/vehicles/${encodeURIComponent(plate)}/validate`);
      toast.success("Validation retirée");
      load();
    } catch { toast.error("Retrait impossible"); }
    finally { setSaving(false); }
  };

  return (
    <div className="border border-border p-3 space-y-2" data-testid="consensus-block">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
          <GitMerge size={11} /> Consensus multi-plugins
        </div>
        {isValidated && (
          <span className="text-[9px] mono uppercase px-1.5 py-0.5 border border-[#00E676] text-[#00E676] flex items-center gap-1">
            <CheckCircle2 size={10} /> Validée
          </span>
        )}
      </div>

      {isValidated ? (
        <div className="text-xs space-y-1">
          <div>Plaque canonique : <b className="mono">{canonical}</b></div>
          {val.variants?.length > 0 && (
            <div className="text-muted-foreground">
              Variantes liées : {val.variants.map((v) => <span key={v} className="mono mr-1">{v}</span>)}
            </div>
          )}
          <div className="text-[10px] text-muted-foreground">
            Par {val.validated_by} · {fmtDateTime(val.validated_at)}
          </div>
          <button onClick={unvalidate} disabled={saving}
                  data-testid="unvalidate-btn"
                  className="mt-1 text-[10px] uppercase tracking-wider px-2 py-1 border border-border hover:bg-secondary/60">
            {saving ? <Loader2 size={11} className="animate-spin" /> : "Retirer la validation"}
          </button>
        </div>
      ) : (
        <>
          <div className="text-xs space-y-1">
            <div>Suggestion : <b className="mono text-[#00E676]">{canonical}</b> (score {data.canonical_score})</div>
            {hasVariants && (
              <div className="text-muted-foreground text-[11px]">
                {variants.length} variante{variants.length > 1 ? "s" : ""} OCR détectée{variants.length > 1 ? "s" : ""} — probablement le même véhicule
              </div>
            )}
          </div>

          {candidates.length > 1 && (
            <div className="space-y-1 border-t border-border pt-2">
              {candidates.map((c) => (
                <div key={c.plate} className="flex items-center gap-2 text-[11px]" data-testid={`candidate-${c.plate}`}>
                  <span className="mono font-semibold w-16">{c.plate}</span>
                  <div className="flex-1 h-1 bg-secondary/60 relative">
                    <div className="h-full bg-[#0044FF]"
                         style={{ width: `${Math.min(100, (c.score / (candidates[0].score || 1)) * 100)}%` }} />
                  </div>
                  <span className="mono w-10 text-right">{c.score}</span>
                  <span className="mono text-muted-foreground w-14 text-right">
                    {c.reads} lect. · {c.engines.length} moteur{c.engines.length > 1 ? "s" : ""}
                  </span>
                  <button
                    onClick={() => validate(c.plate)}
                    disabled={saving}
                    data-testid={`validate-${c.plate}`}
                    className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border border-[#00E676] text-[#00E676] hover:bg-[#00E676]/10 disabled:opacity-40"
                  >
                    Valider
                  </button>
                </div>
              ))}
            </div>
          )}

          {candidates.length <= 1 && !hasVariants && (
            <button
              onClick={() => validate(canonical)}
              disabled={saving}
              data-testid="validate-single-btn"
              className="w-full flex items-center justify-center gap-1 px-2 py-2 border border-[#00E676] text-[#00E676] text-xs hover:bg-[#00E676]/10"
            >
              {saving ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={12} />}
              Valider cette plaque
            </button>
          )}
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Bandeau d'anomalies récentes (en tête de la grille)
// ═══════════════════════════════════════════════════════════════════
function AnomaliesBanner({ items, onOpen, onDismiss }) {
  return (
    <div className="border border-[#FFB800]/60 bg-[#FFB800]/5 p-3 mb-4" data-testid="anomalies-banner">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-[#FFB800] text-xs uppercase tracking-wider font-medium">
          <AlertTriangle size={14} /> Anomalies récentes ({items.length})
        </div>
        <button onClick={onDismiss}
                data-testid="anomalies-dismiss"
                className="text-[10px] text-muted-foreground hover:text-foreground uppercase tracking-wider">
          Masquer
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((a) => (
          <button
            key={a.plate}
            onClick={() => onOpen(a.plate)}
            data-testid={`anomaly-chip-${a.plate}`}
            className="flex items-center gap-2 border px-2 py-1 text-xs hover:bg-secondary/40 transition-colors"
            style={{ borderColor: a.severity === "high" ? "#FF3333" : "#FFB800",
                     color: a.severity === "high" ? "#FF3333" : "#FFB800" }}
          >
            <span className="mono font-semibold">{a.plate}</span>
            <span className="text-[10px] uppercase">{a.severity}</span>
            <span className="text-muted-foreground truncate max-w-[200px]">
              {a.anomalies.slice(0, 2).join(" · ")}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function TabGallery({ plate }) {
  const [items, setItems] = useState([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const loadMore = useCallback(async (o = 0, replace = false) => {
    setLoading(true);
    try {
      const { data } = await api.get(`/vehicles/${encodeURIComponent(plate)}/passages`, {
        params: { limit: 24, offset: o },
      });
      setTotal(data.total || 0);
      setItems((prev) => replace ? data.items : [...prev, ...data.items]);
      setOffset(o + (data.items?.length || 0));
    } finally { setLoading(false); }
  }, [plate]);
  useEffect(() => { loadMore(0, true); }, [loadMore]);

  return (
    <div className="space-y-3" data-testid="drawer-gallery">
      <div className="text-xs text-muted-foreground mono">{items.length} / {total} captures</div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {items.map((p) => (
          <div key={p.id}
               className="relative block bg-secondary/40 border border-border hover:border-[#0044FF] transition-colors"
               data-testid={`gallery-${p.id}`}>
            {/* v0.7.e · Wave E · 3 crops préservés : photo complète (lien),
                crop véhicule (miniature principale), crop plaque (bandeau bas). */}
            <a href={`${process.env.REACT_APP_BACKEND_URL}/api/vehicles/passage/${p.id}/thumb?kind=frame`}
               target="_blank" rel="noreferrer"
               className="block relative"
               data-testid={`gallery-frame-link-${p.id}`}
               title="Voir la photo complète">
              <img
                src={`${process.env.REACT_APP_BACKEND_URL}/api/vehicles/passage/${p.id}/thumb?kind=vehicle`}
                alt=""
                loading="lazy"
                className="w-full h-24 object-cover"
                data-testid={`gallery-vehicle-thumb-${p.id}`}
                onError={(e) => { e.target.style.display = "none"; }}
              />
              <span className="absolute top-1 right-1 px-1.5 py-0.5 text-[8px] mono uppercase tracking-wider bg-black/60 text-white border border-white/20">
                Full →
              </span>
            </a>
            {/* Bandeau crop plaque (petit ruban 100% × 20px) — le vrai crop
                de plaque optimisé par le gate qualité v0.7.e Wave C. */}
            <a href={`${process.env.REACT_APP_BACKEND_URL}/api/vehicles/passage/${p.id}/thumb?kind=plate`}
               target="_blank" rel="noreferrer"
               className="block bg-black border-t border-border"
               data-testid={`gallery-plate-link-${p.id}`}
               title="Voir le crop plaque HD">
              <img
                src={`${process.env.REACT_APP_BACKEND_URL}/api/vehicles/passage/${p.id}/thumb?kind=plate`}
                alt=""
                loading="lazy"
                className="w-full h-8 object-contain bg-black"
                data-testid={`gallery-plate-thumb-${p.id}`}
                onError={(e) => { e.target.style.display = "none"; }}
              />
            </a>
            <div className="p-1 text-[9px] mono text-muted-foreground">
              <div className="truncate">{fmtDateTime(p.timestamp)}</div>
              <div className="flex items-center justify-between">
                <span className="truncate">{p.camera_name}</span>
                <span style={{ color: p.confidence > 0.9 ? "#00E676" : "#FFB800" }}>{(p.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>
        ))}
      </div>
      {items.length < total && (
        <button
          onClick={() => loadMore(offset)}
          disabled={loading}
          className="w-full px-4 py-2 border border-border text-sm hover:bg-secondary flex items-center justify-center gap-2"
          data-testid="load-more-gallery"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : "Charger plus"}
        </button>
      )}
    </div>
  );
}

function TabTimeline({ plate }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.get(`/vehicles/${encodeURIComponent(plate)}/passages`, { params: { limit: 200 } })
       .then(({ data }) => setItems(data.items || []));
  }, [plate]);

  const groups = useMemo(() => {
    const out = new Map();
    for (const p of items) {
      const dt = new Date(p.timestamp);
      const key = dt.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
      if (!out.has(key)) out.set(key, []);
      out.get(key).push(p);
    }
    return Array.from(out.entries());
  }, [items]);

  return (
    <div className="space-y-4" data-testid="drawer-timeline">
      {groups.map(([day, rows]) => (
        <div key={day}>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2 sticky top-0 bg-card py-1">{day} · {rows.length} passage{rows.length > 1 ? "s" : ""}</div>
          <div className="border-l-2 border-[#0044FF]/40 pl-3 space-y-2">
            {rows.map((p) => (
              <div key={p.id} className="flex items-center gap-3 text-xs" data-testid={`timeline-item-${p.id}`}>
                <span className="mono text-[#0044FF] w-14">{new Date(p.timestamp).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</span>
                <img src={`${process.env.REACT_APP_BACKEND_URL}/api/vehicles/passage/${p.id}/thumb?kind=vehicle`} alt="" loading="lazy"
                     className="w-10 h-10 object-cover border border-border"
                     onError={(e) => { e.target.style.display = "none"; }} />
                <span className="text-muted-foreground truncate flex-1">{p.camera_name}</span>
                <span className="mono" style={{ color: p.confidence > 0.9 ? "#00E676" : "#FFB800" }}>{(p.confidence * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function TabHeatmap({ plate }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    api.get(`/vehicles/${encodeURIComponent(plate)}/heatmap`).then(({ data }) => setD(data));
  }, [plate]);
  if (!d) return <div className="text-xs text-muted-foreground">Chargement…</div>;

  const maxH = Math.max(1, ...d.by_hour);
  const maxD = Math.max(1, ...d.by_dow);

  return (
    <div className="space-y-5" data-testid="drawer-heatmap">
      <div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
          <BarChart3 size={11} /> Passages par heure
        </div>
        <div className="space-y-1 text-[10px] mono">
          {d.by_hour.map((count, h) => (
            <div key={h} className="flex items-center gap-2" data-testid={`heatmap-hour-${h}`}>
              <span className="w-6 text-muted-foreground">{String(h).padStart(2, "0")}</span>
              <div className="h-2.5 flex-1 bg-secondary/40 relative overflow-hidden">
                <div className="h-full bg-[#0044FF] transition-all" style={{ width: `${(count / maxH) * 100}%` }} />
              </div>
              <span className="w-8 text-right">{count}</span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
          <BarChart3 size={11} /> Passages par jour
        </div>
        <div className="space-y-1 text-[10px] mono">
          {d.by_dow.map((count, i) => (
            <div key={i} className="flex items-center gap-2" data-testid={`heatmap-dow-${i}`}>
              <span className="w-16 text-muted-foreground">{d.dow_labels[i]}</span>
              <div className="h-2.5 flex-1 bg-secondary/40 relative overflow-hidden">
                <div className="h-full bg-[#00E676] transition-all" style={{ width: `${(count / maxD) * 100}%` }} />
              </div>
              <span className="w-8 text-right">{count}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TabCameras({ plate }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.get(`/vehicles/${encodeURIComponent(plate)}/cameras`).then(({ data }) => setItems(data.items || []));
  }, [plate]);
  return (
    <div className="space-y-2" data-testid="drawer-cameras">
      {items.map((c) => (
        <div key={c.camera_id} className="border border-border p-3" data-testid={`cam-${c.camera_id}`}>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <CameraIcon size={14} className="text-[#0044FF]" />
              <span className="text-sm truncate">{c.camera_name || c.camera_id}</span>
            </div>
            <span className="mono text-xs px-2 py-0.5 bg-secondary/60">{c.count} passages</span>
          </div>
          <div className="text-[10px] text-muted-foreground mt-1 mono">
            Dernier : {fmtDateTime(c.last_seen)} · Premier : {fmtDateTime(c.first_seen)}
          </div>
        </div>
      ))}
      {items.length === 0 && <div className="text-xs text-muted-foreground">Aucune caméra concernée.</div>}
    </div>
  );
}

function TabJourney({ plate }) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    api.get(`/vehicles/${encodeURIComponent(plate)}/journey`).then(({ data }) => setItems(data.items || []));
  }, [plate]);
  const chrono = [...items].reverse(); // du + ancien au + récent
  return (
    <div className="space-y-2" data-testid="drawer-journey">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground flex items-center gap-1">
        <RouteIcon size={11} /> Ordre chronologique
      </div>
      {chrono.map((p, i) => (
        <div key={`${p.timestamp}-${i}`} className="flex items-center gap-3" data-testid={`journey-${i}`}>
          <div className="text-[11px] mono text-[#0044FF] w-24">
            {new Date(p.timestamp).toLocaleString("fr-FR", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}
          </div>
          <div className="flex-1 border border-border px-3 py-1.5 text-xs">
            {p.camera_name || p.camera_id}
            {p.direction && <span className="ml-2 text-muted-foreground">· {p.direction}</span>}
          </div>
          {i < chrono.length - 1 && <ChevronDown size={12} className="text-muted-foreground rotate-[-90deg] hidden" />}
        </div>
      ))}
      {chrono.length === 0 && <div className="text-xs text-muted-foreground">Aucun parcours à afficher.</div>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Petits helpers
// ═══════════════════════════════════════════════════════════════════
function Stat({ label, value }) {
  return (
    <div className="border border-border p-2">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mono mt-0.5">{value}</div>
    </div>
  );
}

function PlateBadge({ value, status }) {
  const c = status === "black" ? "#FF3333" : status === "white" ? "#00E676" : "#1a1a1a";
  return (
    <span className="inline-flex items-center mono font-semibold text-sm tracking-wider px-2 py-0.5 border-2 bg-white text-black" style={{ borderColor: c }} data-testid={`plate-${value}`}>
      <span className="text-[7px] bg-[#0044FF] text-white px-0.5 mr-1 leading-none py-1">F</span>{value}
    </span>
  );
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR"); }
  catch { return iso; }
}

function fmtRelative(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "il y a quelques secondes";
  if (diff < 3600) return `il y a ${Math.round(diff / 60)} min`;
  if (diff < 86400) return `il y a ${Math.round(diff / 3600)} h`;
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
