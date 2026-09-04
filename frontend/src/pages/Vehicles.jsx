import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import VirtualGrid from "@/components/VirtualGrid";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Search, Car, Camera as CameraIcon, Clock,
  Activity, BarChart3, Loader2, Info, ChevronRight,
  AlertTriangle, ShieldAlert, ShieldCheck, Shield, Bell, X as XIcon,
  CheckCircle2, GitMerge, Sparkles, Users, Plus, LayoutGrid, List,
} from "lucide-react";
import { toast } from "sonner";

/**
 * v1.0-rc2 · Fix miniatures Vehicles noires.
 * Les balises <img> HTML ne peuvent PAS envoyer le header Authorization Bearer,
 * elles s'appuient uniquement sur les cookies. Le backend `auth.get_current_user`
 * accepte un fallback `?token=` en query param (voir auth.py:255).
 * Ce helper injecte le token pour toutes les images de passage véhicule.
 */
function passageThumbUrl(passageId, kind = "vehicle") {
  if (!passageId) return null;
  const token = localStorage.getItem("mg_token") || "";
  const qs = token ? `&token=${encodeURIComponent(token)}` : "";
  return `${process.env.REACT_APP_BACKEND_URL}/api/vehicles/passage/${passageId}/thumb?kind=${kind}${qs}`;
}

/**
 * Vehicle History Center — v0.6 Smart ANPR History
 *
 * Regroupe automatiquement les lectures ANPR par plaque et présente une
 * fiche véhicule complète : galerie, timeline, heatmap, caméras visitées,
 * parcours, habitudes.
 */
export function VehiclesSection({ embedded = false, initialQuery = "" }) {
  const { t, user } = useApp();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [openPlate, setOpenPlate] = useState(null);
  const [anomalies, setAnomalies] = useState([]);
  const [dedupSuggestions, setDedupSuggestions] = useState([]);
  const [dedupRunning, setDedupRunning] = useState(false);
  const [dedupAvailable, setDedupAvailable] = useState(true); // v3.22 · évite de faire attendre pour rien si le switch LLM est off
  // v3.20 · Affichage tuiles (miniatures, plus lourd à charger) vs liste
  // compacte (façon ancien menu Plaques) — demandé pour alléger l'interface.
  // Préférence mémorisée par navigateur, pas envoyée au serveur.
  const [viewMode, setViewMode] = useState(() => localStorage.getItem("vehicles_view_mode") || "tiles");
  useEffect(() => { localStorage.setItem("vehicles_view_mode", viewMode); }, [viewMode]);

  // v3.18 · Fusion manuelle de fiches — sélection explicite par l'opérateur,
  // pas de calcul automatique (voir _merge_by_identity côté backend).
  const [mergeMode, setMergeMode] = useState(false);
  const [selectedPlates, setSelectedPlates] = useState(new Set());
  const [merging, setMerging] = useState(false);
  const togglePlateSelection = (plate) => {
    setSelectedPlates((prev) => {
      const next = new Set(prev);
      next.has(plate) ? next.delete(plate) : next.add(plate);
      return next;
    });
  };
  const cancelMerge = () => { setMergeMode(false); setSelectedPlates(new Set()); };

  // v3.20 · Suppression définitive d'une ou plusieurs fiches (lectures ANPR
  // + miniatures embarquées, voir bulk_delete_vehicles côté backend) — même
  // mécanisme de sélection que la fusion, mode mutuellement exclusif.
  const [deleteMode, setDeleteMode] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const cancelDelete = () => { setDeleteMode(false); setSelectedPlates(new Set()); };
  const confirmDelete = async () => {
    if (selectedPlates.size < 1) return;
    const plates = items.filter((it) => selectedPlates.has(it.plate));
    const totalReads = plates.reduce((sum, it) => sum + (it.passages_count || 0), 0);
    if (!window.confirm(
      `Supprimer définitivement ${plates.length} fiche${plates.length > 1 ? "s" : ""} `
      + `(${totalReads} lecture${totalReads > 1 ? "s" : ""} ANPR + miniatures) ? `
      + `Cette action est IRRÉVERSIBLE.`
    )) return;
    setDeleting(true);
    try {
      const allPlates = plates.flatMap((it) => [it.plate, ...(it.plate_variants || [])]);
      const { data } = await api.post("/vehicles/bulk-delete", { plates: allPlates, confirm: true });
      toast.success(`${data.reads_deleted} lecture(s) supprimée(s) définitivement`);
      cancelDelete();
      load(q);
      loadIdentities();
    } catch (e) { toast.error(e.response?.data?.detail?.message || "Échec de la suppression"); }
    finally { setDeleting(false); }
  };
  // v3.19 · Créer une fiche véhicule manuellement — ex. véhicule signalé
  // volé : on connaît la plaque avant toute lecture ANPR. Compose deux
  // endpoints déjà en place et testés (pas de nouveau code backend) :
  // POST /vehicles/identities (la fiche) puis, si liste noire cochée,
  // POST /watchlist (déclenche déjà alerte + notification à la prochaine
  // lecture de cette plaque, voir routers.py::maybe_blacklist_alert).
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({
    plate: "", name: "", vehicle_make: "", vehicle_color: "", vehicle_type: "",
    notes: "", blacklist: false, reason: "",
  });
  const resetCreateForm = () => setCreateForm({
    plate: "", name: "", vehicle_make: "", vehicle_color: "", vehicle_type: "",
    notes: "", blacklist: false, reason: "",
  });
  const submitCreate = async () => {
    const plate = createForm.plate.trim().toUpperCase().replace(/\s|-/g, "");
    if (!plate) { toast.error("La plaque est requise"); return; }
    setCreating(true);
    try {
      await api.post("/vehicles/identities", {
        plates: [plate],
        name: createForm.name.trim() || plate,
        vehicle_make: createForm.vehicle_make.trim() || null,
        vehicle_color: createForm.vehicle_color.trim() || null,
        vehicle_type: createForm.vehicle_type.trim() || null,
        notes: createForm.notes.trim(),
      });
      if (createForm.blacklist) {
        await api.post("/watchlist", { plate, list_type: "black", reason: createForm.reason.trim() });
      }
      toast.success(`Fiche créée pour ${plate}`);
      setCreateOpen(false);
      resetCreateForm();
      load(q);
      loadIdentities();
    } catch (e) {
      toast.error(e.response?.data?.detail?.message || "Création de la fiche impossible");
    } finally {
      setCreating(false);
    }
  };
  const confirmMerge = async () => {
    if (selectedPlates.size < 2) return;
    setMerging(true);
    try {
      // Envoie la plaque canonique ET ses variantes déjà fusionnées pour
      // chaque fiche sélectionnée — l'identité doit couvrir tout ce qui est
      // déjà regroupé, pas seulement la plaque affichée.
      const plates = items
        .filter((it) => selectedPlates.has(it.plate))
        .flatMap((it) => [it.plate, ...(it.plate_variants || [])]);
      await api.post("/vehicles/identities", { plates, name: plates[0] });
      toast.success(`${selectedPlates.size} fiches fusionnées`);
      cancelMerge();
      load(q);
    } catch (e) {
      toast.error("Fusion impossible");
    } finally {
      setMerging(false);
    }
  };
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

  const loadAnomalies = useCallback(async () => {
    try {
      const { data } = await api.get("/vehicles/anomalies/recent", { params: { since_hours: 48, limit: 8 } });
      setAnomalies(data.items || []);
    } catch { /* silent */ }
  }, []);

  // v3.20 · Suggestions de fusion (même véhicule lu différemment) —
  // générées en tâche de fond par Qwen, jamais fusionnées automatiquement.
  const loadDedup = useCallback(async () => {
    try {
      const { data } = await api.get("/vehicles/dedup/suggestions", { params: { status: "pending" } });
      setDedupSuggestions(data.items || []);
    } catch { /* silent */ }
  }, []);

  // v3.22 · Vérifie en amont si le dédoublonnage IA est réellement
  // utilisable (connexion LLM + switch dédié) — évite de faire cliquer
  // "Rechercher maintenant" puis attendre pour rien si c'est désactivé
  // dans Administration → LLM. Réservé admin (seul rôle voyant le bouton).
  const loadDedupAvailability = useCallback(async () => {
    if (user?.role !== "admin") return;
    try {
      const { data } = await api.get("/settings/llm");
      setDedupAvailable(!!data.enabled && !!data.dedup_enabled);
    } catch { setDedupAvailable(true); /* échec réseau : ne pas bloquer sur une supposition */ }
  }, [user?.role]);

  // v3.21 · La recherche complète (candidats + jusqu'à 25 appels Qwen
  // séquentiels) prend plusieurs minutes en réel — le backend la lance
  // maintenant en tâche de fond et répond immédiatement (voir
  // vehicle_dedup.py). On reflète ça ici : la requête elle-même est
  // rapide, puis on raffraîchit périodiquement la liste pendant quelques
  // minutes pour faire apparaître les suggestions au fil de l'eau, sans
  // que le bouton reste bloqué en "en cours" pendant tout ce temps.
  const runDedupNow = async () => {
    setDedupRunning(true);
    try {
      await api.post("/vehicles/dedup/run");
      toast.success("Recherche de doublons lancée en arrière-plan — les suggestions apparaîtront ici automatiquement (peut prendre plusieurs minutes)");
      let tries = 0;
      const poll = setInterval(() => {
        tries += 1;
        loadDedup();
        if (tries >= 18) clearInterval(poll); // ~3 min à 10s d'intervalle
      }, 10000);
    } catch (e) {
      // v3.22 · Le backend renvoie déjà un message précis (ex. DEDUP_DISABLED
      // si le switch dédoublonnage est désactivé dans Administration → LLM)
      // — on l'affiche tel quel au lieu d'un message générique qui laissait
      // l'utilisateur chercher pourquoi ça ne marche pas.
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Échec du lancement de la recherche de doublons");
    }
    finally { setDedupRunning(false); }
  };

  const decideDedup = async (id, accept) => {
    try {
      await api.post(`/vehicles/dedup/suggestions/${id}/${accept ? "accept" : "reject"}`);
      setDedupSuggestions((prev) => prev.filter((s) => s.id !== id));
      if (accept) { toast.success("Fiches fusionnées"); load(q); }
    } catch { toast.error("Échec"); }
  };

  // v3.41 · L'ancien détecteur heuristique de candidats (/vehicles/identities/detect
  // — marque/couleur/type + plaques proches, v0.7) est retiré : redondant
  // avec le dédoublonnage Qwen, bien plus abouti après les affinages du
  // jour (tri, tier distance-1, planification fiable). Ne reste que la
  // liste des identités déjà confirmées, affichée dans la fenêtre fusion.
  const loadIdentities = useCallback(async () => {
    try {
      const { data: list } = await api.get("/vehicles/identities");
      setIdentities(list.items || []);
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

  // v3.19 · 20 tuiles par page (demande explicite : les 20 dernières
  // plaques avec miniatures, puis "Charger plus" pour la suite — même
  // principe que le menu Événements). Le vrai gain de vitesse vient du
  // cache serveur ci-dessus (_list_cache) : avant, chaque page — y
  // compris "Charger plus" sur la même liste — repayait ~1s de
  // reclustering complet côté backend.
  const PAGE_SIZE = 20;
  const [loadingMore, setLoadingMore] = useState(false);
  const load = useCallback(async (search = "") => {
    setLoading(true);
    try {
      const { data } = await api.get("/vehicles", {
        params: { q: search, limit: PAGE_SIZE, offset: 0 },
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      toast.error("Impossible de charger les véhicules");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMore = useCallback(async () => {
    setLoadingMore(true);
    try {
      const { data } = await api.get("/vehicles", {
        params: { q, limit: PAGE_SIZE, offset: items.length },
      });
      setItems((prev) => [...prev, ...(data.items || [])]);
      setTotal(data.total || 0);
    } catch (e) {
      toast.error("Impossible de charger la suite");
    } finally {
      setLoadingMore(false);
    }
  }, [q, items.length]);

  // Chargement initial + refresh 30 s (pausé si le drawer est ouvert)
  useEffect(() => { load(""); loadAnomalies(); loadIdentities(); loadDedup(); loadDedupAvailability(); }, [load, loadAnomalies, loadIdentities, loadDedup, loadDedupAvailability]);
  // v3.19 · Relie la recherche IA générale (menu Événements → "Tous") à
  // celle-ci : "voiture"/"voiture rouge" y sont classés target:vehicles
  // avec de vrais résultats, mais la galerie Événements n'affiche que son
  // propre tableau "events" (jamais "vehicles") — rien ne s'affichait,
  // sans indication d'où chercher. Le bouton "Voir dans Plaques" bascule
  // ici et relance la MÊME requête pour éviter de la retaper.
  useEffect(() => {
    if (initialQuery) { setSmart(initialQuery); runSmartSearch(initialQuery); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);
  useEffect(() => {
    if (openPlate) return; // pause pendant l'ouverture du drawer
    const iv = setInterval(() => { load(q); loadAnomalies(); }, 30000);
    return () => clearInterval(iv);
  }, [openPlate, q, load, loadAnomalies]);

  return (
    <div className={embedded ? "" : "p-4"} data-testid="vehicles-page">
      <div className={`flex items-center ${embedded ? "justify-end" : "justify-between"} mb-4 flex-wrap gap-3`}>
        {!embedded && (
          <div>
            <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
              <Car size={26} /> Véhicules
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Historique par véhicule — cliquez sur une carte pour ouvrir la fiche complète.
            </p>
          </div>
        )}
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
              title={t("veh.adv_filters")}
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
        <div className="flex items-center gap-3">
          <div className="flex border border-border" data-testid="vehicles-view-toggle">
            <button onClick={() => setViewMode("tiles")} title="Affichage tuiles"
                    className={`p-1.5 ${viewMode === "tiles" ? "bg-[#0044FF] text-white" : "text-muted-foreground hover:text-foreground"}`}
                    data-testid="vehicles-view-tiles">
              <LayoutGrid size={13} />
            </button>
            <button onClick={() => setViewMode("list")} title="Affichage liste"
                    className={`p-1.5 border-l border-border ${viewMode === "list" ? "bg-[#0044FF] text-white" : "text-muted-foreground hover:text-foreground"}`}
                    data-testid="vehicles-view-list">
              <List size={13} />
            </button>
          </div>
          {smartResult && (
            <button onClick={clearSmart} data-testid="smart-clear-inline"
                    className="text-[10px] uppercase tracking-wider text-[#0044FF] hover:underline">
              Réinitialiser la recherche
            </button>
          )}
          {!smartResult && !mergeMode && !deleteMode && (
            <button onClick={() => setMergeMode(true)} data-testid="merge-mode-toggle"
                    className="text-[10px] uppercase tracking-wider text-muted-foreground hover:text-[#0044FF] flex items-center gap-1">
              <GitMerge size={12} /> Fusionner des fiches
            </button>
          )}
          {!smartResult && !mergeMode && !deleteMode && (
            <button onClick={() => setDeleteMode(true)} data-testid="delete-mode-toggle"
                    className="text-[10px] uppercase tracking-wider text-muted-foreground hover:text-[#FF3333] flex items-center gap-1">
              <XIcon size={12} /> Supprimer des fiches
            </button>
          )}
          {!smartResult && !mergeMode && !deleteMode && (
            <button onClick={() => setCreateOpen(true)} data-testid="create-fiche-btn"
                    className="text-[10px] uppercase tracking-wider text-muted-foreground hover:text-[#0044FF] flex items-center gap-1">
              <Plus size={12} /> Créer une fiche
            </button>
          )}
        </div>
      </div>

      {/* v3.18 · Fusion manuelle : plusieurs plaques lues différemment pour
          le même véhicule (fourgon garé mal lu à chaque scan, par ex.) sans
          rapport de texte assez proche pour la fusion automatique — un
          opérateur choisit ici explicitement quoi regrouper. */}
      {mergeMode && (
        <div className="border border-[#0044FF] bg-[#0044FF]/5 p-3 mb-3 flex items-center justify-between flex-wrap gap-2" data-testid="merge-toolbar">
          <span className="text-xs">
            Sélectionnez au moins 2 fiches représentant le même véhicule (ex. une voiture garée lue différemment à chaque scan), puis fusionnez.
            <span className="ml-2 font-medium">{selectedPlates.size} sélectionnée{selectedPlates.size > 1 ? "s" : ""}</span>
          </span>
          <div className="flex items-center gap-2">
            <button onClick={cancelMerge} className="px-3 py-1.5 text-xs border border-border hover:bg-secondary">
              Annuler
            </button>
            <button onClick={confirmMerge} disabled={selectedPlates.size < 2 || merging} data-testid="merge-confirm-btn"
                    className="px-3 py-1.5 text-xs bg-[#0044FF] text-white flex items-center gap-2 disabled:opacity-40">
              {merging ? <Loader2 size={13} className="animate-spin" /> : <GitMerge size={13} />}
              Fusionner ({selectedPlates.size})
            </button>
          </div>
        </div>
      )}

      {/* v3.20 · Suppression définitive — même mécanique de sélection que
          la fusion, pour nettoyer les faux positifs (objet fixe détecté à
          tort comme véhicule, plaque totalement hallucinée...) qu'aucune
          fusion automatique ne peut résoudre puisque ce n'est pas un
          doublon d'un vrai véhicule. */}
      {deleteMode && (
        <div className="border border-[#FF3333] bg-[#FF3333]/5 p-3 mb-3 flex items-center justify-between flex-wrap gap-2" data-testid="delete-toolbar">
          <span className="text-xs">
            Sélectionnez les fiches à supprimer définitivement (lectures ANPR + miniatures — irréversible).
            <span className="ml-2 font-medium">{selectedPlates.size} sélectionnée{selectedPlates.size > 1 ? "s" : ""}</span>
          </span>
          <div className="flex items-center gap-2">
            <button onClick={cancelDelete} className="px-3 py-1.5 text-xs border border-border hover:bg-secondary">
              Annuler
            </button>
            <button onClick={confirmDelete} disabled={selectedPlates.size < 1 || deleting} data-testid="delete-confirm-btn"
                    className="px-3 py-1.5 text-xs bg-[#FF3333] text-white flex items-center gap-2 disabled:opacity-40">
              {deleting ? <Loader2 size={13} className="animate-spin" /> : <XIcon size={13} />}
              Supprimer ({selectedPlates.size})
            </button>
          </div>
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={(o) => { setCreateOpen(o); if (!o) resetCreateForm(); }}>
        <DialogContent className="rounded-none border-border max-w-md" data-testid="create-fiche-dialog">
          <DialogHeader>
            <DialogTitle className="font-head flex items-center gap-2"><Plus size={18} /> Créer une fiche véhicule</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Plaque *</label>
              <input
                value={createForm.plate}
                onChange={(e) => setCreateForm({ ...createForm, plate: e.target.value })}
                data-testid="create-fiche-plate"
                placeholder="AB123CD"
                className="w-full px-2 py-1.5 bg-background border border-input outline-none mono uppercase"
              />
            </div>
            <div>
              <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Nom / repère (optionnel)</label>
              <input
                value={createForm.name}
                onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                placeholder="ex. Fourgon bleu Kangoo"
                className="w-full px-2 py-1.5 bg-background border border-input outline-none"
              />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Marque</label>
                <input value={createForm.vehicle_make} onChange={(e) => setCreateForm({ ...createForm, vehicle_make: e.target.value })}
                       className="w-full px-2 py-1.5 bg-background border border-input outline-none" />
              </div>
              <div>
                <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Couleur</label>
                <input value={createForm.vehicle_color} onChange={(e) => setCreateForm({ ...createForm, vehicle_color: e.target.value })}
                       className="w-full px-2 py-1.5 bg-background border border-input outline-none" />
              </div>
              <div>
                <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Type</label>
                <input value={createForm.vehicle_type} onChange={(e) => setCreateForm({ ...createForm, vehicle_type: e.target.value })}
                       className="w-full px-2 py-1.5 bg-background border border-input outline-none" />
              </div>
            </div>
            <div>
              <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Notes</label>
              <textarea
                value={createForm.notes}
                onChange={(e) => setCreateForm({ ...createForm, notes: e.target.value })}
                rows={2}
                className="w-full px-2 py-1.5 bg-background border border-input outline-none resize-none"
              />
            </div>
            <label className="flex items-center gap-2 text-sm border-t border-border pt-3 cursor-pointer">
              <input type="checkbox" checked={createForm.blacklist}
                     onChange={(e) => setCreateForm({ ...createForm, blacklist: e.target.checked })}
                     data-testid="create-fiche-blacklist" />
              <ShieldAlert size={14} className="text-red-500" />
              Mettre en liste noire (véhicule signalé volé) — alerte + notification à la prochaine lecture
            </label>
            {createForm.blacklist && (
              <div>
                <label className="block text-[9px] uppercase tracking-wider text-muted-foreground mb-1">Motif</label>
                <input value={createForm.reason} onChange={(e) => setCreateForm({ ...createForm, reason: e.target.value })}
                       placeholder="ex. Vol signalé le 28/08/2026"
                       className="w-full px-2 py-1.5 bg-background border border-input outline-none" />
              </div>
            )}
          </div>
          <DialogFooter>
            <button onClick={() => setCreateOpen(false)} className="px-3 py-1.5 text-xs border border-border hover:bg-secondary">
              Annuler
            </button>
            <button onClick={submitCreate} disabled={creating || !createForm.plate.trim()} data-testid="create-fiche-submit"
                    className="px-3 py-1.5 text-xs bg-[#0044FF] text-white flex items-center gap-2 disabled:opacity-40">
              {creating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Créer la fiche
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {history.length > 0 && !smartResult && (
        <div className="mb-3 flex items-center gap-2 flex-wrap text-[11px]" data-testid="search-history">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{t("veh.recent_searches")}</span>
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

      {anomalies.length > 0 && (
        <AnomaliesBanner items={anomalies} onOpen={(p) => setOpenPlate(p)} onDismiss={() => setAnomalies([])} />
      )}

      {(dedupSuggestions.length > 0 || identities.length > 0 || user?.role === "admin") && (
        <DedupButton
          items={dedupSuggestions}
          identities={identities}
          admin={user?.role === "admin"}
          running={dedupRunning}
          available={dedupAvailable}
          onRunNow={runDedupNow}
          onAccept={(id) => decideDedup(id, true)}
          onReject={(id) => decideDedup(id, false)}
          onOpenPlate={(p) => setOpenPlate(p)}
        />
      )}

      {items.length === 0 && !loading && (
        <div className="border border-border p-8 text-center text-muted-foreground">
          <Car size={48} className="mx-auto mb-2 opacity-30" />
          <div className="text-sm">{t("veh.none_yet")}</div>
        </div>
      )}

      <div data-testid="vehicles-grid-root">
        {viewMode === "tiles" ? (
          <VirtualGrid
            items={smartResult ? (smartResult.vehicles || []) : items}
            renderItem={(v) => (
              <VehicleCard
                v={v}
                onOpen={(mergeMode || deleteMode) ? () => togglePlateSelection(v.plate) : () => setOpenPlate(v.plate)}
                selectable={mergeMode || deleteMode}
                selected={selectedPlates.has(v.plate)}
              />
            )}
            itemKey={(v) => v.plate}
            rowHeight={340}
            minColumnWidth={220}
            maxColumns={6}
            threshold={200}
            fallbackClassName="grid gap-4 grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6"
            testid="vehicles-virtual-grid"
          />
        ) : (
          <VirtualGrid
            items={smartResult ? (smartResult.vehicles || []) : items}
            renderItem={(v) => (
              <VehicleListRow
                v={v}
                onOpen={(mergeMode || deleteMode) ? () => togglePlateSelection(v.plate) : () => setOpenPlate(v.plate)}
                selectable={mergeMode || deleteMode}
                selected={selectedPlates.has(v.plate)}
              />
            )}
            itemKey={(v) => v.plate}
            rowHeight={52}
            minColumnWidth={99999}
            maxColumns={1}
            threshold={200}
            testid="vehicles-virtual-list"
          />
        )}
      </div>

      {/* v3.17 · Même principe que le menu Événements : la page ne charge
          qu'un lot de PAGE_SIZE tuiles (limite la latence), avec un bouton
          pour remonter plus loin dans le temps au lieu de tout charger
          d'un coup. */}
      {!smartResult && items.length < total && items.length > 0 && (
        <div className="flex justify-center pt-2">
          <button onClick={loadMore} disabled={loadingMore} data-testid="vehicles-load-more"
                  className="flex items-center gap-2 px-4 py-2 border border-border text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground hover:border-[#0044FF]/60 disabled:opacity-50">
            {loadingMore ? <Loader2 size={13} className="animate-spin" /> : null}
            {loadingMore ? "Chargement…" : `Charger plus (${items.length} / ${total})`}
          </button>
        </div>
      )}

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
function VehicleCard({ v, onOpen, selectable = false, selected = false }) {
  const { t } = useApp();
  // v1.0-rc2 · Utilise le helper module `passageThumbUrl` qui appende ?token=
  // (les <img> HTML ne peuvent pas envoyer de Bearer header).
  const thumbUrl = (id, kind = "vehicle") => passageThumbUrl(id, kind);

  const previews = (v.preview_thumb_ids || []).slice(0, 3);
  const extra = Math.max(0, (v.passages_count || 0) - 1);

  return (
    <button
      onClick={onOpen}
      data-testid={`vehicle-card-${v.plate}`}
      className={`text-left bg-card border transition-all group p-3 flex flex-col gap-3 relative ${
        selectable
          ? selected ? "border-[#0044FF] ring-2 ring-[#0044FF]/40" : "border-border hover:border-[#0044FF]/50"
          : "border-border hover:border-[#0044FF]"
      }`}
    >
      {/* v3.18 · Mode fusion : case à cocher visuelle par-dessus la carte */}
      {selectable && (
        <div
          className={`absolute top-2 left-2 z-20 w-5 h-5 border-2 flex items-center justify-center ${
            selected ? "bg-[#0044FF] border-[#0044FF]" : "bg-black/40 border-white"
          }`}
          data-testid={`vehicle-select-${v.plate}`}
        >
          {selected && <CheckCircle2 size={14} className="text-white" />}
        </div>
      )}
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
// VehicleDrawer — panneau latéral avec 6 onglets (exporté pour la vue
// Événements fusionnée : historique plaque/véhicule depuis le viewer)
// ═══════════════════════════════════════════════════════════════════
export function VehicleDrawer({ plate, onClose, onWatchChanged }) {
  const { t } = useApp();
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
            {!detail && <span className="text-muted-foreground text-sm">{t("veh.loading")}</span>}
            {detail && (
              <span className="text-xs text-muted-foreground">
                {[detail.vehicle_make, detail.vehicle_model, detail.vehicle_color].filter(Boolean).join(" · ")}
              </span>
            )}
          </SheetTitle>
        </SheetHeader>

        {detail && (
          <Tabs defaultValue="overview" className="p-4">
            <TabsList className="grid grid-cols-5 rounded-none bg-secondary/40 border border-border h-auto p-0">
              <TabsTrigger value="overview"  className="rounded-none text-xs py-2" data-testid="tab-overview">Vue</TabsTrigger>
              <TabsTrigger value="gallery"   className="rounded-none text-xs py-2" data-testid="tab-gallery">Galerie</TabsTrigger>
              <TabsTrigger value="timeline"  className="rounded-none text-xs py-2" data-testid="tab-timeline">Timeline</TabsTrigger>
              <TabsTrigger value="heatmap"   className="rounded-none text-xs py-2" data-testid="tab-heatmap">Heatmap</TabsTrigger>
              <TabsTrigger value="cameras"   className="rounded-none text-xs py-2" data-testid="tab-cameras">{t("veh.cameras")}</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-4"><TabOverview d={detail} onWatchChanged={handleWatchChanged} onReload={reload} /></TabsContent>
            <TabsContent value="gallery"  className="mt-4"><TabGallery plate={plate} /></TabsContent>
            <TabsContent value="timeline" className="mt-4"><TabTimeline plate={plate} /></TabsContent>
            <TabsContent value="heatmap"  className="mt-4"><TabHeatmap plate={plate} /></TabsContent>
            <TabsContent value="cameras"  className="mt-4"><TabCameras plate={plate} /></TabsContent>
          </Tabs>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ─── Tabs contents ───────────────────────────────────────────────
function TabOverview({ d, onWatchChanged, onReload }) {
  const { t } = useApp();
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
          src={passageThumbUrl(d.best_thumb_id, "frame")}
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
      <PlateConsensusBlock plate={d.plate} onValidated={onReload} />

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
          {habits.typical_arrival && <div>{t("veh.usual_arrival")}<b className="mono">{habits.typical_arrival}</b></div>}
          {habits.typical_departure && <div>{t("veh.usual_departure")}<b className="mono">{habits.typical_departure}</b></div>}
          {habits.typical_days?.length > 0 && <div>{t("veh.main_days")}<b>{habits.typical_days.join(", ")}</b></div>}
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
  const { t } = useApp();
  return (
    <div className="mt-6" data-testid="persons-section">
      <div className="flex items-center gap-2 mb-3">
        <Users size={16} className="text-[#0044FF]" />
        <h2 className="font-head text-lg tracking-tight">{t("veh.people_detected")}<span className="mono text-sm text-muted-foreground">({persons.length})</span></h2>
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
// Consensus multi-plugins & Validation manuelle de la plaque (v0.7 preview)
// ═══════════════════════════════════════════════════════════════════
function PlateConsensusBlock({ plate, onValidated }) {
  const [data, setData] = useState(null);
  const [saving, setSaving] = useState(false);
  // v3.19 · Bypass manuel — quand aucune variante suggérée n'est la bonne
  // plaque (cas réel : 19 variantes OCR autour de « E2222x », aucune ne
  // correspondait au véhicule), l'opérateur doit pouvoir taper la plaque
  // directement plutôt que de choisir uniquement parmi les candidats.
  const [manualOpen, setManualOpen] = useState(false);
  const [manualPlate, setManualPlate] = useState("");

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
      onValidated && onValidated();  // v3.19 · rafraîchit le titre de la fiche (voir vehicle_detail)
    } catch { toast.error("Validation impossible"); }
    finally { setSaving(false); }
  };

  const validateManual = async () => {
    const p = manualPlate.trim().toUpperCase().replace(/\s|-/g, "");
    if (!p) return;
    await validate(p);
    setManualOpen(false);
    setManualPlate("");
  };

  const unvalidate = async () => {
    setSaving(true);
    try {
      await api.delete(`/vehicles/${encodeURIComponent(plate)}/validate`);
      toast.success("Validation retirée");
      load();
      onValidated && onValidated();
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
      ) : manualOpen ? (
        <div className="flex items-center gap-1.5 border-t border-border pt-2" data-testid="manual-plate-form">
          <input value={manualPlate} onChange={(e) => setManualPlate(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && validateManual()}
                 placeholder="Plaque correcte…" autoFocus data-testid="manual-plate-input"
                 className="flex-1 px-2 py-1 bg-background border border-input outline-none mono uppercase text-xs" />
          <button onClick={validateManual} disabled={saving || !manualPlate.trim()} data-testid="manual-plate-submit"
                  className="text-[9px] uppercase tracking-wider px-2 py-1 border border-[#00E676] text-[#00E676] hover:bg-[#00E676]/10 disabled:opacity-40">
            Valider
          </button>
          <button onClick={() => { setManualOpen(false); setManualPlate(""); }}
                  className="text-[9px] uppercase tracking-wider px-2 py-1 border border-border hover:bg-secondary/60">
            Annuler
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

          <button onClick={() => setManualOpen(true)} data-testid="manual-plate-open"
                  className="w-full text-[10px] uppercase tracking-wider text-muted-foreground hover:text-[#0044FF] pt-1">
            Aucune suggestion correcte ? Saisir la plaque manuellement
          </button>
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

// v3.20 · Suggestions de fusion générées par Qwen (tâche de fond,
// comparaison des attributs déjà extraits — pas de vision, le modèle
// configuré est texte seul). Jamais de fusion automatique : chaque
// suggestion attend une décision manuelle, même mécanisme de fusion que
// "Fusionner des fiches" (POST /vehicles/identities).
// v3.38 · Refonte demandée : un bouton unique (au lieu d'un bandeau
// toujours affiché) qui ouvre une fenêtre listant les suggestions, avec
// miniature réelle du véhicule par plaque (récupérée via le même
// endpoint/pattern que le reste de l'appli, passageThumbUrl — voir son
// commentaire plus haut) pour un vrai contrôle visuel avant fusion, et le
// détail des attributs au survol de chaque miniature.
// v3.41 · Fusionné avec l'ancien panneau "Identités véhicule" (v0.7) —
// même donnée sous-jacente (accepter une suggestion écrit dans la même
// collection vehicle_identities que ce panneau affichait), plus de raison
// d'avoir 2 menus séparés. Son propre détecteur de candidats heuristique
// est retiré (redondant avec le dédoublonnage Qwen ci-dessous, bien plus
// abouti). Renommé en conséquence : ce n'est plus seulement des
// suggestions, mais aussi les fusions déjà confirmées.
function DedupButton({ items, identities, admin, running, available, onRunNow, onAccept, onReject, onOpenPlate }) {
  const [open, setOpen] = useState(false);
  if (!admin && items.length === 0 && identities.length === 0) return null;
  return (
    <>
      <button onClick={() => setOpen(true)} data-testid="dedup-open-modal"
              className="flex items-center gap-1.5 border border-[#0044FF]/40 bg-[#0044FF]/5 text-[#0044FF] px-3 py-1.5 text-xs uppercase tracking-wider mb-4 hover:bg-[#0044FF]/10">
        <Sparkles size={14} /> Fusion & identités véhicule (IA) {items.length > 0 && `(${items.length})`}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="rounded-none border-border max-w-3xl max-h-[85vh] flex flex-col" data-testid="dedup-modal">
          <DialogHeader>
            <DialogTitle className="font-head flex items-center justify-between gap-4 pr-6">
              <span className="flex items-center gap-2"><Sparkles size={16} /> Fusion & identités véhicule (IA)</span>
              {admin && available && (
                <button onClick={onRunNow} disabled={running} data-testid="dedup-run-now"
                        className="text-[10px] uppercase tracking-wider text-[#0044FF] hover:underline disabled:opacity-50 flex items-center gap-1 font-normal normal-case">
                  {running && <Loader2 size={11} className="animate-spin" />}
                  {running ? "Recherche…" : "Rechercher maintenant"}
                </button>
              )}
            </DialogTitle>
          </DialogHeader>
          {admin && !available && (
            <p className="text-[11px] text-[#FF3333]" data-testid="dedup-unavailable">
              Connexion impossible — vérifiez la configuration dans Administration → LLM (MG-IA).
            </p>
          )}
          <div className="flex-1 overflow-y-auto space-y-4 -mx-1 px-1">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
                Suggestions en attente {items.length > 0 && `(${items.length})`}
              </div>
              {items.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  Aucune suggestion en attente — tâche automatique une fois par jour, ou lance-la manuellement.
                </p>
              ) : (
                <div className="space-y-2">
                  {items.map((s) => (
                    <DedupRow key={s.id} s={s} onAccept={onAccept} onReject={onReject} />
                  ))}
                </div>
              )}
            </div>
            {identities.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1.5">
                  <Users size={11} /> Identités confirmées ({identities.length})
                </div>
                <div className="flex flex-wrap gap-2">
                  {identities.map((id) => (
                    <div key={id.id} className="border border-[#0044FF]/40 bg-card px-2 py-1 text-[11px]" data-testid={`identity-${id.id}`}>
                      <div className="font-medium">{id.name}</div>
                      <div className="text-muted-foreground text-[10px]">
                        {id.plates.length} plaque{id.plates.length > 1 ? "s" : ""} · {id.vehicle_make || "—"} {id.vehicle_color || ""}
                      </div>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {id.plates.map((p) => (
                          <button key={p} onClick={() => { onOpenPlate(p); setOpen(false); }}
                                  className="mono text-[9px] px-1 py-0.5 border border-border hover:bg-secondary"
                                  data-testid={`identity-plate-${p}`}>
                            {p}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

// Une paire de vignettes cliquables au survol (attributs détaillés) +
// décision. Deux miniatures distinctes (une par plaque) : le point du
// tri manuel demandé — les attributs seuls ne montrent pas si c'est
// visuellement la même voiture.
function DedupRow({ s, onAccept, onReject }) {
  const [hover, setHover] = useState(null); // "a" | "b" | null
  const thumbA = passageThumbUrl(s.stats_a?.sample_plate_id, "vehicle");
  const thumbB = passageThumbUrl(s.stats_b?.sample_plate_id, "vehicle");
  const Thumb = ({ side, url, plate }) => {
    const st = side === "a" ? s.stats_a : s.stats_b;
    return (
      <div className="relative" onMouseEnter={() => setHover(side)} onMouseLeave={() => setHover((h) => (h === side ? null : h))}>
        {url ? (
          <img src={url} alt={plate} loading="lazy" data-testid={`dedup-thumb-${side}-${s.id}`}
               className="w-16 h-12 object-cover border border-border" />
        ) : (
          <div className="w-16 h-12 bg-secondary flex items-center justify-center text-[9px] text-muted-foreground border border-border">—</div>
        )}
        {hover === side && st && (
          <div className="absolute z-10 top-full left-0 mt-1 bg-black/90 border border-[#0044FF]/40 p-2 text-[10px] text-white w-48 space-y-0.5"
               data-testid={`dedup-hover-info-${side}-${s.id}`}>
            <div>Marque : {st.make || "—"}</div>
            <div>Modèle : {st.model || "—"}</div>
            <div>Couleur : {st.color || "—"}</div>
            <div>Type : {st.type || "—"}</div>
            <div>Lectures : {st.count ?? "—"}</div>
            <div>Dernière vue : {st.last_seen ? new Date(st.last_seen).toLocaleString("fr-FR") : "—"}</div>
          </div>
        )}
      </div>
    );
  };
  return (
    <div className="flex items-center gap-3 border border-border bg-card px-3 py-2 text-xs" data-testid={`dedup-item-${s.id}`}>
      <div className="flex items-center gap-1.5 shrink-0">
        <Thumb side="a" url={thumbA} plate={s.plate_a} />
        <span className="mono font-semibold">{s.plate_a}</span>
      </div>
      <span className="text-muted-foreground shrink-0">↔</span>
      <div className="flex items-center gap-1.5 shrink-0">
        <span className="mono font-semibold">{s.plate_b}</span>
        <Thumb side="b" url={thumbB} plate={s.plate_b} />
      </div>
      <div className="flex-1 min-w-0">
        <span className="text-muted-foreground text-[10px]">
          ({s.stats_a?.count} + {s.stats_b?.count} lectures)
        </span>
        {s.reason && <div className="text-[10px] text-muted-foreground mt-0.5 truncate">{s.reason}</div>}
      </div>
      {s.confidence != null && (
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground shrink-0">
          confiance {Math.round(s.confidence * 100)}%
        </span>
      )}
      <button onClick={() => onAccept(s.id)} data-testid={`dedup-accept-${s.id}`}
              className="px-2 py-1 border border-[#00E676] text-[#00E676] hover:bg-[#00E676]/10 shrink-0 uppercase tracking-wider text-[10px]">
        Fusionner
      </button>
      <button onClick={() => onReject(s.id)} data-testid={`dedup-reject-${s.id}`}
              className="px-2 py-1 border border-border text-muted-foreground hover:text-foreground shrink-0 uppercase tracking-wider text-[10px]">
        Ignorer
      </button>
    </div>
  );
}

function TabGallery({ plate }) {
  const { t } = useApp();
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
            <a href={passageThumbUrl(p.id, "frame")}
               target="_blank" rel="noreferrer"
               className="block relative"
               data-testid={`gallery-frame-link-${p.id}`}
               title={t("veh.view_full_photo")}>
              <img
                src={passageThumbUrl(p.id, "vehicle")}
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
            <a href={passageThumbUrl(p.id, "plate")}
               target="_blank" rel="noreferrer"
               className="block bg-black border-t border-border"
               data-testid={`gallery-plate-link-${p.id}`}
               title="Voir le crop plaque HD">
              <img
                src={passageThumbUrl(p.id, "plate")}
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

// v3.40 · Demande explicite : au survol de la miniature de passage, afficher
// la photo en grand (suit la souris, jamais coupée par le conteneur qui
// défile — position fixed) ; au clic, l'ouvrir plein écran.
function PassageThumb({ passageId, alt }) {
  const [hoverPos, setHoverPos] = useState(null);
  const [fullOpen, setFullOpen] = useState(false);
  const url = passageThumbUrl(passageId, "vehicle");
  if (!url) return <div className="w-10 h-10 bg-secondary border border-border shrink-0" />;
  return (
    <>
      <img src={url} alt={alt} loading="lazy"
           className="w-10 h-10 object-cover border border-border shrink-0 cursor-pointer"
           onError={(e) => { e.target.style.display = "none"; }}
           onMouseMove={(e) => setHoverPos({ x: e.clientX, y: e.clientY })}
           onMouseLeave={() => setHoverPos(null)}
           onClick={() => setFullOpen(true)}
           data-testid={`passage-thumb-${passageId}`} />
      {hoverPos && (
        <div className="fixed z-[60] pointer-events-none border-2 border-[#0044FF] bg-black shadow-xl"
             style={{
               left: Math.min(hoverPos.x + 16, window.innerWidth - 340),
               top: Math.min(hoverPos.y + 16, window.innerHeight - 260),
             }}>
          <img src={url} alt="" className="max-w-[320px] max-h-[240px] object-contain" />
        </div>
      )}
      {fullOpen && (
        <div className="fixed inset-0 z-[70] bg-black/90 flex items-center justify-center p-8"
             onClick={() => setFullOpen(false)} data-testid="passage-thumb-fullscreen">
          <img src={url} alt="" className="max-w-full max-h-full object-contain" />
        </div>
      )}
    </>
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
                <PassageThumb passageId={p.id} alt={p.camera_name} />
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
  const { t } = useApp();
  const [d, setD] = useState(null);
  useEffect(() => {
    api.get(`/vehicles/${encodeURIComponent(plate)}/heatmap`).then(({ data }) => setD(data));
  }, [plate]);
  if (!d) return <div className="text-xs text-muted-foreground">{t("veh.loading")}</div>;

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
  const { t } = useApp();
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
      {items.length === 0 && <div className="text-xs text-muted-foreground">{t("veh.no_camera")}</div>}
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

// v3.20 · Affichage liste — vue compacte façon ancien menu Plaques, en
// alternative aux tuiles avec miniatures (demandé : plus léger/rapide,
// pas de chargement d'image par ligne).
function VehicleListRow({ v, onOpen, selectable = false, selected = false }) {
  return (
    <button
      onClick={onOpen}
      data-testid={`vehicle-row-${v.plate}`}
      className={`w-full text-left bg-card border-b border-border hover:bg-secondary/40 transition-colors flex items-center gap-4 px-3 py-2 ${
        selectable && selected ? "bg-[#0044FF]/10" : ""
      }`}
    >
      {selectable && (
        <div
          className={`w-4 h-4 shrink-0 border-2 flex items-center justify-center ${
            selected ? "bg-[#0044FF] border-[#0044FF]" : "border-muted-foreground"
          }`}
          data-testid={`vehicle-row-select-${v.plate}`}
        >
          {selected && <CheckCircle2 size={11} className="text-white" />}
        </div>
      )}
      <div className="shrink-0 w-28">
        <PlateBadge value={v.plate} status={v.list_status} />
      </div>
      <div className="w-20 text-[11px] uppercase tracking-wider text-muted-foreground shrink-0">{v.vehicle_color || "—"}</div>
      <div className="flex-1 text-sm truncate min-w-0">
        {[v.vehicle_make, v.vehicle_model].filter(Boolean).join(" ") || <span className="text-muted-foreground">—</span>}
      </div>
      <div className="w-24 text-[11px] text-muted-foreground shrink-0 flex items-center gap-1"><Activity size={11} /> {v.passages_count}</div>
      <div className="w-24 text-[11px] text-muted-foreground shrink-0 flex items-center gap-1"><CameraIcon size={11} /> {v.cameras_count}</div>
      <div className="w-36 text-[11px] text-muted-foreground shrink-0 flex items-center gap-1"><Clock size={11} /> {fmtRelative(v.last_seen)}</div>
    </button>
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

// Compat : route legacy /vehicles (redirigée vers /events?filtre=plaques)
export default function Vehicles() {
  return <VehiclesSection />;
}
