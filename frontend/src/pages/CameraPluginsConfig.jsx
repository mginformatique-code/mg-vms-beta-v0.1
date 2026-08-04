/**
 * CameraPluginsConfig — Sélecteur modulaire des plugins IA activés par caméra.
 *
 * v0.3 · Remplace la case unique "Détection IA" par une liste complète des
 * 50 plugins installés, regroupés par catégorie et activables 1 à N par caméra.
 *
 * Backend :
 *   - GET /api/plugins/catalog → liste des plugins groupés
 *   - Le champ `enabled_plugins: string[]` de la caméra fait office de liste
 *     blanche pour dispatch_pipeline (vide = tous les plugins actifs — legacy)
 */
import React, { useEffect, useMemo, useState } from "react";
import { Search, CheckSquare, Square, ChevronDown, ChevronUp, Zap, X } from "lucide-react";
import api from "@/lib/api";

const CATEGORY_COLORS = {
  "ANPR / LPR": "#00E676",
  "Détection IA": "#00E5FF",
  "Tracking": "#B085FF",
  "Segmentation": "#FFB800",
  "Feu / Fumée": "#FF3333",
  "Sûreté active": "#FF3366",
  "EPI": "#00B0FF",
  "Comptage": "#FFA500",
  "Retail": "#EC4899",
  "Parking": "#94A3B8",
  "Agriculture": "#22C55E",
  "Notifications": "#F59E0B",
  "Événements": "#8B5CF6",
};

export default function CameraPluginsConfig({ value = [], onChange }) {
  const [catalog, setCatalog] = useState({ groups: [], total: 0, available: 0 });
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [openGroups, setOpenGroups] = useState({});
  const selected = new Set(value || []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const { data } = await api.get("/plugins/catalog");
        if (!cancelled) setCatalog(data);
      } catch (e) {
        // silent
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const filteredGroups = useMemo(() => {
    if (!query.trim()) return catalog.groups;
    const q = query.toLowerCase();
    return catalog.groups
      .map(g => ({ ...g, plugins: g.plugins.filter(p => (
        p.name.toLowerCase().includes(q) ||
        (p.display_name || "").toLowerCase().includes(q) ||
        (p.description || "").toLowerCase().includes(q)
      )) }))
      .filter(g => g.plugins.length > 0);
  }, [catalog.groups, query]);

  const toggle = (name) => {
    const next = new Set(selected);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    onChange(Array.from(next));
  };

  const toggleGroup = (group) => {
    const groupNames = group.plugins.filter(p => p.available).map(p => p.name);
    const allIn = groupNames.every(n => selected.has(n));
    const next = new Set(selected);
    if (allIn) groupNames.forEach(n => next.delete(n));
    else groupNames.forEach(n => next.add(n));
    onChange(Array.from(next));
  };

  const clearAll = () => onChange([]);
  const selectAll = () => {
    const all = catalog.groups.flatMap(g => g.plugins.filter(p => p.available).map(p => p.name));
    onChange(all);
  };

  const totalSel = selected.size;
  const totalAvail = catalog.available;

  return (
    <div className="border border-border p-3 bg-secondary/20 space-y-3" data-testid="camera-plugins-config">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <Zap size={14} className="text-[#00E676]" />
          <span className="text-xs font-medium">Config IA modulaire</span>
          <span className="text-[10px] mono text-muted-foreground">
            {totalSel} / {totalAvail} plugin{totalSel > 1 ? "s" : ""} actif{totalSel > 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" onClick={selectAll}
            className="text-[10px] px-2 py-1 border border-border hover:bg-secondary"
            data-testid="plugins-select-all">Tout activer</button>
          <button type="button" onClick={clearAll}
            className="text-[10px] px-2 py-1 border border-border hover:bg-secondary"
            data-testid="plugins-clear-all">
            <X size={10} className="inline mr-0.5" /> Tout retirer
          </button>
        </div>
      </div>

      {/* Hint */}
      {totalSel === 0 && (
        <div className="text-[10px] text-muted-foreground border-l-2 border-yellow-500/60 pl-2">
          Aucun plugin sélectionné → détection IA <b>désactivée</b> sur cette caméra.
          Cochez ≥ 1 plugin pour activer l&apos;analyse (ex. <code>yolo-detection</code> + <code>bytetrack</code> + <code>anpr-eps</code>).
        </div>
      )}

      {/* Search */}
      <div className="relative">
        <Search size={12} className="absolute left-2 top-2 text-muted-foreground" />
        <input
          type="text" placeholder="Rechercher un plugin…"
          value={query} onChange={(e) => setQuery(e.target.value)}
          className="w-full pl-7 pr-2 py-1.5 text-xs bg-card border border-input"
          data-testid="plugins-search"
        />
      </div>

      {/* Groups */}
      {loading ? (
        <div className="text-[11px] text-muted-foreground text-center py-4">Chargement du catalogue…</div>
      ) : (
        <div className="max-h-96 overflow-y-auto space-y-2" data-testid="plugins-groups">
          {filteredGroups.map((g) => {
            const color = CATEGORY_COLORS[g.category] || "#94A3B8";
            const groupSelected = g.plugins.filter(p => selected.has(p.name)).length;
            const groupTotal = g.plugins.filter(p => p.available).length;
            const isOpen = openGroups[g.category] !== false; // ouvert par défaut
            return (
              <div key={g.category} className="border border-border" data-testid={`plugins-group-${g.category}`}>
                <div className="flex items-center justify-between px-2 py-1.5 bg-secondary/30">
                  <button type="button" onClick={() => setOpenGroups({ ...openGroups, [g.category]: !isOpen })}
                    className="flex items-center gap-1.5 text-xs font-medium">
                    {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    <span className="w-1.5 h-1.5" style={{ backgroundColor: color }} />
                    {g.category}
                    <span className="text-[10px] mono text-muted-foreground">
                      {groupSelected}/{groupTotal}
                    </span>
                  </button>
                  <button type="button" onClick={() => toggleGroup(g)}
                    className="text-[10px] px-1.5 py-0.5 border border-border hover:bg-secondary">
                    {groupSelected === groupTotal ? "Décocher tout" : "Cocher tout"}
                  </button>
                </div>
                {isOpen && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-0.5 p-1.5">
                    {g.plugins.map((p) => {
                      const isSel = selected.has(p.name);
                      const disabled = !p.available;
                      return (
                        <label key={p.name}
                          className={`flex items-start gap-2 px-2 py-1.5 text-[11px] cursor-pointer border ${isSel ? "border-[#00E676]/50 bg-[#00E676]/5" : "border-transparent hover:bg-secondary/40"} ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
                          data-testid={`plugin-item-${p.name}`}>
                          <input type="checkbox" checked={isSel} disabled={disabled}
                            onChange={() => !disabled && toggle(p.name)}
                            className="mt-0.5" />
                          <div className="flex-1 min-w-0">
                            <div className="font-medium truncate">{p.display_name}</div>
                            {p.description && (
                              <div className="text-[10px] text-muted-foreground line-clamp-2">{p.description}</div>
                            )}
                            <div className="flex items-center gap-1.5 mt-0.5">
                              <span className="text-[9px] mono px-1 py-0.5 bg-secondary/50" style={{ color }}>{p.interface}</span>
                              {!p.available && <span className="text-[9px] text-red-400">indisponible</span>}
                            </div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
          {filteredGroups.length === 0 && (
            <div className="text-[11px] text-muted-foreground text-center py-4">Aucun plugin ne correspond à « {query} »</div>
          )}
        </div>
      )}
    </div>
  );
}
