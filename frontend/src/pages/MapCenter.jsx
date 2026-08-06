/**
 * MapCenter.jsx — v0.5.2 (Phase 1)
 *
 * Site Manager / Map Center basé sur react-konva (canvas 2D performant).
 *
 * Hiérarchie : Client → Site → Bâtiment → Niveau → Plan → Caméras → Zones
 *
 * Phase 1 (livrée) :
 *   - Sélection Site + Bâtiment + Plan (arbre latéral gauche)
 *   - Upload plan (PNG/JPG/SVG) via FileReader → data URI
 *   - Canvas Konva avec image de fond + zoom molette + pan glisser-fond
 *   - Caméras positionnables (drag & drop) avec rotation via poignée
 *   - Sauvegarde automatique de la position (debounced)
 *   - Panneau détail caméra (droite) au clic : nom, IP, driver, statut,
 *     stream, plugins actifs, ancre position/hauteur/objectif
 *   - Bouton "Voir dans Camera Center" (navigation bidirectionnelle)
 *
 * Prévu Phase 2+ : cônes FOV colorés (vert/jaune/rouge), overlays câbles,
 * switches, zones, portes, mesures, export PDF/PNG, audit.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Stage, Layer, Image as KonvaImage, Rect, Circle, Group, Text, Wedge, Line } from "react-konva";
import useImage from "use-image";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  Building2, Camera as CamIcon, ChevronDown, ChevronRight, Compass, ExternalLink,
  FilePlus, FolderTree, HardDrive, Layers as LayersIcon, MapPin, Move,
  Plus, Save, Search, Settings2, Trash2, Upload, X, ZoomIn, ZoomOut,
} from "lucide-react";

// ─────────────────────────────────────────────────────────────────────
// Constantes visuelles
// ─────────────────────────────────────────────────────────────────────
const DEFAULT_CAM = {
  x: 100, y: 100, rotation: 0, height_m: 3,
  angle_h: 90, angle_v: 60, range_m: 20, color: "#0044FF",
  fixture: "wall", lens_mm: 4,
};

const STATUS_COLOR = {
  online: "#00E676", offline: "#FF3333", degraded: "#FFB800",
};
const FIXTURE_LABEL = { wall: "Mur", ceiling: "Plafond", pole: "Mât" };
const PLAN_TYPES = [
  { id: "satellite", label: "Satellite" },
  { id: "rdc", label: "RDC" },
  { id: "etage", label: "Étage" },
  { id: "parking", label: "Parking" },
  { id: "entrepot", label: "Entrepôt" },
  { id: "exterieur", label: "Extérieur" },
  { id: "drone", label: "Vue drone" },
  { id: "autre", label: "Autre" },
];

const STAGE_MIN_ZOOM = 0.15;
const STAGE_MAX_ZOOM = 5;

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────
async function fileToDataUri(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

function useDebouncedCallback(fn, delay) {
  const timerRef = useRef(null);
  return useCallback((...args) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => fn(...args), delay);
  }, [fn, delay]);
}

// ─────────────────────────────────────────────────────────────────────
// Konva : image du plan (utilise use-image pour la précharge async)
// ─────────────────────────────────────────────────────────────────────
function PlanBackground({ src, onSize }) {
  const [img] = useImage(src, "anonymous");
  useEffect(() => {
    if (img && onSize) onSize(img.width, img.height);
  }, [img, onSize]);
  if (!img) return null;
  return <KonvaImage image={img} listening={false} />;
}

// ─────────────────────────────────────────────────────────────────────
// Camera icon (Konva group)
// ─────────────────────────────────────────────────────────────────────
function CameraNode({ cam, selected, onDrag, onDragEnd, onSelect, onDblClick }) {
  const pos = cam.map_position || {};
  const rot = pos.rotation || 0;
  const range = pos.range_m ? pos.range_m * 4 : 60; // 4 px = 1 m visuel
  const angleH = pos.angle_h || 90;
  const status = cam.status || "offline";
  const dotColor = STATUS_COLOR[status] || "#71717a";
  const color = pos.color || DEFAULT_CAM.color;

  return (
    <Group
      x={pos.x || 0}
      y={pos.y || 0}
      rotation={rot}
      draggable
      onDragMove={(e) => onDrag(cam.id, { x: e.target.x(), y: e.target.y() })}
      onDragEnd={(e) => onDragEnd(cam.id, { x: e.target.x(), y: e.target.y() })}
      onClick={() => onSelect(cam.id)}
      onTap={() => onSelect(cam.id)}
      onDblClick={() => onDblClick && onDblClick(cam.id)}
      onDblTap={() => onDblClick && onDblClick(cam.id)}
    >
      {/* Champ de vision — Wedge orienté vers le "haut" du groupe */}
      <Wedge
        radius={range}
        angle={angleH}
        rotation={-angleH / 2 - 90}
        fill={color}
        opacity={selected ? 0.25 : 0.15}
        stroke={color}
        strokeWidth={selected ? 1.5 : 0.5}
      />
      {/* Icône caméra : cercle + petit rectangle-objectif */}
      <Circle radius={9} fill="#0d1117" stroke={color} strokeWidth={2} />
      <Rect x={-2} y={-14} width={4} height={6} fill={color} />
      {/* Point de statut */}
      <Circle x={8} y={-8} radius={3} fill={dotColor} />
      {/* Nom (contre-rotation pour rester lisible) */}
      <Text
        text={cam.name || cam.id?.slice(0, 6)}
        fontSize={11}
        fill="#e6e6e6"
        rotation={-rot}
        x={12}
        y={-6}
        listening={false}
      />
      {/* Halo si sélectionné */}
      {selected && (
        <Circle radius={14} stroke="#00E676" strokeWidth={2} dash={[3, 3]} />
      )}
    </Group>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Camera details panel (right side)
// ─────────────────────────────────────────────────────────────────────
function CameraPanel({ camera, onClose, onChange, onOpenInCenter }) {
  const [local, setLocal] = useState(camera?.map_position || {});
  useEffect(() => setLocal(camera?.map_position || {}), [camera]);

  if (!camera) return null;
  const set = (k, v) => {
    const next = { ...local, [k]: v };
    setLocal(next);
    onChange(next);
  };
  const num = (v) => (v === "" || v === null ? undefined : Number(v));

  return (
    <div className="w-80 bg-card border-l border-border flex flex-col overflow-y-auto" data-testid="map-camera-panel">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">Caméra</div>
          <div className="font-medium truncate">{camera.name}</div>
        </div>
        <button onClick={onClose} className="hover:text-[#FF3333]" data-testid="map-camera-panel-close">
          <X size={16} />
        </button>
      </div>

      <div className="p-4 space-y-4 text-sm">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div><span className="text-muted-foreground">IP : </span><span className="mono">{camera.ip || "—"}</span></div>
          <div><span className="text-muted-foreground">Statut : </span>
            <span className="mono" style={{ color: STATUS_COLOR[camera.status] || "#71717a" }}>{camera.status || "—"}</span>
          </div>
          <div><span className="text-muted-foreground">Marque : </span>{camera.brand || "—"}</div>
          <div><span className="text-muted-foreground">Modèle : </span>{camera.model || "—"}</div>
          <div><span className="text-muted-foreground">Driver : </span>{camera.driver || "—"}</div>
          <div><span className="text-muted-foreground">MAC : </span><span className="mono">{camera.mac || "—"}</span></div>
          <div className="col-span-2"><span className="text-muted-foreground">Firmware : </span>{camera.firmware || "—"}</div>
        </div>

        <div className="pt-3 border-t border-border">
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
            <MapPin size={11} /> Position & FOV
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs">Rotation (°)
              <input type="number" step="1" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
                value={local.rotation ?? 0} onChange={(e) => set("rotation", num(e.target.value))}
                data-testid="map-cam-rotation" />
            </label>
            <label className="text-xs">Portée (m)
              <input type="number" step="0.5" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
                value={local.range_m ?? DEFAULT_CAM.range_m} onChange={(e) => set("range_m", num(e.target.value))}
                data-testid="map-cam-range" />
            </label>
            <label className="text-xs">Angle H (°)
              <input type="number" step="1" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
                value={local.angle_h ?? DEFAULT_CAM.angle_h} onChange={(e) => set("angle_h", num(e.target.value))} />
            </label>
            <label className="text-xs">Angle V (°)
              <input type="number" step="1" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
                value={local.angle_v ?? DEFAULT_CAM.angle_v} onChange={(e) => set("angle_v", num(e.target.value))} />
            </label>
            <label className="text-xs">Hauteur (m)
              <input type="number" step="0.1" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
                value={local.height_m ?? DEFAULT_CAM.height_m} onChange={(e) => set("height_m", num(e.target.value))} />
            </label>
            <label className="text-xs">Objectif (mm)
              <input type="number" step="0.5" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
                value={local.lens_mm ?? DEFAULT_CAM.lens_mm} onChange={(e) => set("lens_mm", num(e.target.value))} />
            </label>
            <label className="text-xs col-span-2">Fixation
              <select className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
                value={local.fixture || "wall"} onChange={(e) => set("fixture", e.target.value)}>
                <option value="wall">Mur</option>
                <option value="ceiling">Plafond</option>
                <option value="pole">Mât</option>
              </select>
            </label>
          </div>
        </div>

        <div className="pt-3 border-t border-border">
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
            <Settings2 size={11} /> Installation
          </div>
          <label className="text-xs block mb-2">Technicien
            <input type="text" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
              value={local.technician || ""} onChange={(e) => set("technician", e.target.value)} />
          </label>
          <label className="text-xs block mb-2">Numéro de série
            <input type="text" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm mono"
              value={local.serial || ""} onChange={(e) => set("serial", e.target.value)} />
          </label>
          <label className="text-xs block mb-2">Date d&apos;installation
            <input type="date" className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm"
              value={local.install_date || ""} onChange={(e) => set("install_date", e.target.value)} />
          </label>
          <label className="text-xs block">Notes installateur
            <textarea className="w-full mt-1 px-2 py-1 bg-background border border-border text-sm min-h-[60px]"
              value={local.install_notes || ""} onChange={(e) => set("install_notes", e.target.value)} />
          </label>
        </div>

        {camera.enabled_plugins?.length > 0 && (
          <div className="pt-3 border-t border-border">
            <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2">Plugins actifs</div>
            <div className="flex flex-wrap gap-1">
              {camera.enabled_plugins.map((p) => (
                <span key={p} className="text-[9px] mono uppercase tracking-wider px-1.5 py-0.5 border border-[#0044FF] text-[#0044FF]">
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="p-4 border-t border-border">
        <button
          onClick={onOpenInCenter}
          className="w-full flex items-center justify-center gap-2 border border-border px-3 py-2 text-xs hover:bg-secondary/50"
          data-testid="map-cam-open-center"
        >
          <ExternalLink size={13} /> Voir dans Camera Center
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Sidebar : hiérarchie Sites > Bâtiments > Plans
// ─────────────────────────────────────────────────────────────────────
function SiteTree({
  sites, buildings, plans, selectedSite, selectedPlan,
  onSelectSite, onSelectPlan, onCreateBuilding, onCreatePlan, onDeletePlan, cameraCounts,
}) {
  const [expanded, setExpanded] = useState({}); // site_id → bool
  const [q, setQ] = useState("");
  const norm = (s) => (s || "").toLowerCase();

  const filteredSites = useMemo(() => {
    if (!q) return sites;
    const qq = norm(q);
    return sites.filter((s) =>
      norm(s.name).includes(qq) || norm(s.client_name).includes(qq)
    );
  }, [sites, q]);

  const buildingsOf = (siteId) => buildings.filter((b) => b.site_id === siteId);
  const plansOf = (siteId, buildingId) => plans.filter((p) =>
    p.site_id === siteId && (buildingId ? p.building_id === buildingId : !p.building_id)
  );

  return (
    <div className="w-72 bg-card border-r border-border flex flex-col overflow-hidden" data-testid="map-site-tree">
      <div className="p-3 border-b border-border">
        <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
          <FolderTree size={11} /> Sites & Plans
        </div>
        <div className="relative">
          <Search size={12} className="absolute top-2 left-2 text-muted-foreground" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher…"
            className="w-full pl-7 pr-2 py-1.5 bg-background border border-border text-xs"
            data-testid="map-tree-search" />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto text-sm">
        {filteredSites.map((s) => {
          const isOpen = expanded[s.id] ?? true;
          const bs = buildingsOf(s.id);
          const orphanPlans = plansOf(s.id, null);
          return (
            <div key={s.id} className="border-b border-border/40">
              <button
                onClick={() => { setExpanded({ ...expanded, [s.id]: !isOpen }); onSelectSite(s.id); }}
                className={`w-full flex items-center gap-1.5 px-3 py-2 text-left hover:bg-secondary/40 ${selectedSite === s.id ? "bg-secondary/60" : ""}`}
                data-testid={`map-tree-site-${s.id}`}
              >
                {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <Building2 size={13} className="text-[#0044FF]" />
                <span className="flex-1 truncate text-xs font-medium">{s.name}</span>
                {s.client_name && <span className="text-[9px] text-muted-foreground truncate">{s.client_name}</span>}
              </button>
              {isOpen && (
                <div className="ml-4 pb-2">
                  {bs.map((b) => (
                    <div key={b.id}>
                      <div className="flex items-center gap-1.5 px-3 py-1 text-xs text-muted-foreground">
                        <HardDrive size={11} />
                        <span className="flex-1 truncate">{b.name}</span>
                      </div>
                      {plansOf(s.id, b.id).map((p) => (
                        <PlanRow key={p.id} p={p} selected={selectedPlan?.id === p.id}
                          onSelect={() => onSelectPlan(p.id)}
                          onDelete={() => onDeletePlan(p.id)}
                          count={cameraCounts[p.id] || 0} />
                      ))}
                    </div>
                  ))}
                  {orphanPlans.map((p) => (
                    <PlanRow key={p.id} p={p} selected={selectedPlan?.id === p.id}
                      onSelect={() => onSelectPlan(p.id)}
                      onDelete={() => onDeletePlan(p.id)}
                      count={cameraCounts[p.id] || 0} />
                  ))}
                  <div className="flex gap-1 px-3 py-1">
                    <button onClick={() => onCreateBuilding(s.id)}
                      className="text-[10px] text-[#0044FF] hover:underline flex items-center gap-1"
                      data-testid={`map-add-building-${s.id}`}>
                      <Plus size={10} /> Bâtiment
                    </button>
                    <button onClick={() => onCreatePlan(s.id)}
                      className="text-[10px] text-[#0044FF] hover:underline flex items-center gap-1 ml-2"
                      data-testid={`map-add-plan-${s.id}`}>
                      <FilePlus size={10} /> Plan
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PlanRow({ p, selected, onSelect, onDelete, count }) {
  return (
    <div className={`group flex items-center gap-1.5 px-3 py-1 hover:bg-secondary/40 cursor-pointer ${selected ? "bg-[#0044FF]/15 border-l-2 border-[#0044FF]" : ""}`}
      onClick={onSelect} data-testid={`map-plan-${p.id}`}>
      <LayersIcon size={11} className="text-muted-foreground" />
      <span className="flex-1 truncate text-xs">{p.name}</span>
      <span className="text-[9px] mono text-muted-foreground">{count}</span>
      <button onClick={(e) => { e.stopPropagation(); onDelete(); }}
        className="opacity-0 group-hover:opacity-100 text-[#FF3333]"
        title="Supprimer">
        <Trash2 size={11} />
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────
export default function MapCenter() {
  const navigate = useNavigate();
  const containerRef = useRef(null);
  const stageRef = useRef(null);

  // Data
  const [sites, setSites] = useState([]);
  const [buildings, setBuildings] = useState([]);
  const [plans, setPlans] = useState([]);
  const [selectedSite, setSelectedSite] = useState(null);
  const [selectedPlan, setSelectedPlan] = useState(null); // full doc with image
  const [cameras, setCameras] = useState([]); // cameras on current plan
  const [selectedCamId, setSelectedCamId] = useState(null);

  // Camera counts per plan (for tree)
  const [cameraCounts, setCameraCounts] = useState({});

  // Canvas state
  const [stageSize, setStageSize] = useState({ w: 800, h: 600 });
  const [planSize, setPlanSize] = useState({ w: 1024, h: 768 });
  const [scale, setScale] = useState(1);
  const [stagePos, setStagePos] = useState({ x: 0, y: 0 });

  // ── Bootstrap ────────────────────────────────────────────────────
  const refreshAll = useCallback(async () => {
    try {
      const [rs, rb, rp] = await Promise.all([
        api.get("/sites"),
        api.get("/site-manager/buildings"),
        api.get("/site-manager/plans"),
      ]);
      setSites(rs.data || []);
      setBuildings(rb.data || []);
      setPlans(rp.data || []);
      if (!selectedSite && rs.data?.length) setSelectedSite(rs.data[0].id);
    } catch (e) { toast.error("Échec chargement Map Center"); }
  }, [selectedSite]);

  useEffect(() => { refreshAll(); }, [refreshAll]);

  // Camera counts
  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/site-manager/cameras");
        const counts = {};
        (r.data || []).forEach((c) => {
          const pid = c.map_position?.plan_id;
          if (pid) counts[pid] = (counts[pid] || 0) + 1;
        });
        setCameraCounts(counts);
      } catch (e) { /* noop */ }
    })();
  }, [plans]);

  // Load plan (with image) and its cameras
  const loadPlan = useCallback(async (planId) => {
    try {
      const [rp, rc] = await Promise.all([
        api.get(`/site-manager/plans/${planId}`),
        api.get(`/site-manager/cameras?plan_id=${planId}`),
      ]);
      setSelectedPlan(rp.data);
      setCameras(rc.data || []);
      setSelectedCamId(null);
      // Reset zoom & pan quand on change de plan
      setScale(1); setStagePos({ x: 0, y: 0 });
    } catch (e) {
      toast.error("Impossible de charger ce plan");
    }
  }, []);

  const onSelectPlan = (planId) => { loadPlan(planId); };

  // ── Resize observer for stage ────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setStageSize({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    setStageSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // ── Wheel zoom (centered on cursor) ──────────────────────────────
  const onWheel = (e) => {
    e.evt.preventDefault();
    const stage = stageRef.current;
    if (!stage) return;
    const oldScale = stage.scaleX();
    const p = stage.getPointerPosition();
    const mp = { x: (p.x - stage.x()) / oldScale, y: (p.y - stage.y()) / oldScale };
    const dir = e.evt.deltaY > 0 ? -1 : 1;
    let newScale = dir > 0 ? oldScale * 1.1 : oldScale / 1.1;
    newScale = Math.max(STAGE_MIN_ZOOM, Math.min(STAGE_MAX_ZOOM, newScale));
    setScale(newScale);
    setStagePos({ x: p.x - mp.x * newScale, y: p.y - mp.y * newScale });
  };

  // ── Camera drag (auto-save debounced) ────────────────────────────
  const saveCameraPos = useDebouncedCallback(async (camId, pos) => {
    try {
      await api.put(`/site-manager/cameras/${camId}/position`, pos);
    } catch (e) { toast.error("Sauvegarde position échouée"); }
  }, 400);

  const onCamDrag = (camId, pos) => {
    setCameras((cs) => cs.map((c) => c.id === camId
      ? { ...c, map_position: { ...(c.map_position || {}), ...pos } }
      : c));
  };
  const onCamDragEnd = (camId, pos) => saveCameraPos(camId, pos);

  const updateCameraDetails = useDebouncedCallback(async (camId, patch) => {
    try { await api.put(`/site-manager/cameras/${camId}/position`, patch); }
    catch (e) { toast.error("Sauvegarde caméra échouée"); }
  }, 500);

  const onCameraChange = (patch) => {
    if (!selectedCamId) return;
    setCameras((cs) => cs.map((c) => c.id === selectedCamId
      ? { ...c, map_position: { ...(c.map_position || {}), ...patch } }
      : c));
    updateCameraDetails(selectedCamId, patch);
  };

  // ── Actions bâtiments / plans ────────────────────────────────────
  const createBuilding = async (siteId) => {
    const name = window.prompt("Nom du bâtiment ?");
    if (!name) return;
    try {
      await api.post("/site-manager/buildings", { site_id: siteId, name, order: 0 });
      await refreshAll();
    } catch (e) { toast.error("Création bâtiment refusée"); }
  };

  const createPlan = async (siteId) => {
    document.getElementById(`hidden-plan-upload-${siteId}`)?.click();
  };
  const onFilePicked = async (siteId, file) => {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) { toast.error("Fichier > 20 MB"); return; }
    try {
      const dataUri = await fileToDataUri(file);
      const name = file.name.replace(/\.[^.]+$/, "");
      const img = new window.Image();
      const done = new Promise((resolve) => { img.onload = resolve; img.onerror = resolve; });
      img.src = dataUri;
      await done;
      const r = await api.post("/site-manager/plans", {
        site_id: siteId, name, type: "autre",
        image_data_uri: dataUri,
        width: img.width || null, height: img.height || null,
      });
      await refreshAll();
      loadPlan(r.data.id);
      toast.success("Plan importé");
    } catch (e) { toast.error("Import plan refusé"); }
  };

  const deletePlan = async (planId) => {
    if (!window.confirm("Supprimer ce plan (les caméras seront désassociées) ?")) return;
    try {
      await api.delete(`/site-manager/plans/${planId}`);
      if (selectedPlan?.id === planId) { setSelectedPlan(null); setCameras([]); }
      await refreshAll();
    } catch (e) { toast.error("Suppression refusée"); }
  };

  // ── Ajout d'une caméra sur le plan par drag depuis la liste ─────
  const [availableCams, setAvailableCams] = useState([]);
  useEffect(() => {
    if (!selectedSite) return;
    api.get("/cameras").then((r) => {
      setAvailableCams((r.data || []).filter((c) => c.site_id === selectedSite));
    }).catch(() => {});
  }, [selectedSite, cameras]);

  const placeCameraOnPlan = async (camId) => {
    if (!selectedPlan) { toast.error("Sélectionnez un plan d'abord"); return; }
    const cx = planSize.w / 2, cy = planSize.h / 2;
    try {
      await api.put(`/site-manager/cameras/${camId}/position`, {
        plan_id: selectedPlan.id, x: cx, y: cy,
        rotation: 0, angle_h: DEFAULT_CAM.angle_h, angle_v: DEFAULT_CAM.angle_v,
        range_m: DEFAULT_CAM.range_m, height_m: DEFAULT_CAM.height_m, fixture: "wall",
      });
      const r = await api.get(`/site-manager/cameras?plan_id=${selectedPlan.id}`);
      setCameras(r.data || []);
      setSelectedCamId(camId);
    } catch (e) { toast.error("Placement caméra refusé"); }
  };

  const selectedCam = cameras.find((c) => c.id === selectedCamId) || null;
  const camerasOnPlan = cameras;

  // Cameras du site pas encore placées sur ce plan
  const unplaced = availableCams.filter(
    (c) => !camerasOnPlan.some((cp) => cp.id === c.id)
  );

  return (
    <div className="h-[calc(100vh-40px)] flex" data-testid="map-center">
      {/* Sidebar tree */}
      <SiteTree
        sites={sites}
        buildings={buildings}
        plans={plans}
        selectedSite={selectedSite}
        selectedPlan={selectedPlan}
        onSelectSite={setSelectedSite}
        onSelectPlan={onSelectPlan}
        onCreateBuilding={createBuilding}
        onCreatePlan={createPlan}
        onDeletePlan={deletePlan}
        cameraCounts={cameraCounts}
      />

      {/* Hidden file inputs per site (used by "add plan") */}
      {sites.map((s) => (
        <input key={s.id} id={`hidden-plan-upload-${s.id}`} type="file"
          accept="image/*"
          style={{ display: "none" }}
          onChange={(e) => onFilePicked(s.id, e.target.files?.[0])}
        />
      ))}

      {/* Canvas + toolbar */}
      <div ref={containerRef} className="flex-1 relative bg-[#0b0b0f] overflow-hidden">
        {/* Toolbar */}
        <div className="absolute top-2 left-2 right-2 z-10 flex items-center gap-2 pointer-events-none">
          <div className="bg-card/90 backdrop-blur border border-border px-3 py-1.5 text-xs pointer-events-auto flex items-center gap-3">
            <span className="text-muted-foreground">Plan :</span>
            <span className="font-medium">{selectedPlan?.name || "—"}</span>
            {selectedPlan && (
              <>
                <span className="text-muted-foreground">·</span>
                <span className="text-muted-foreground">Caméras :</span>
                <span className="mono">{camerasOnPlan.length}</span>
              </>
            )}
          </div>
          <div className="ml-auto flex items-center gap-1 bg-card/90 backdrop-blur border border-border p-1 pointer-events-auto">
            <button onClick={() => setScale((s) => Math.max(STAGE_MIN_ZOOM, s / 1.2))}
              className="p-1 hover:bg-secondary" title="Zoom -" data-testid="map-zoom-out">
              <ZoomOut size={14} />
            </button>
            <span className="mono text-xs px-2">{Math.round(scale * 100)}%</span>
            <button onClick={() => setScale((s) => Math.min(STAGE_MAX_ZOOM, s * 1.2))}
              className="p-1 hover:bg-secondary" title="Zoom +" data-testid="map-zoom-in">
              <ZoomIn size={14} />
            </button>
            <button onClick={() => { setScale(1); setStagePos({ x: 0, y: 0 }); }}
              className="p-1 hover:bg-secondary" title="Recentrer">
              <Compass size={14} />
            </button>
          </div>
        </div>

        {/* Unplaced cameras drawer */}
        {selectedPlan && unplaced.length > 0 && (
          <div className="absolute bottom-2 left-2 z-10 bg-card/95 border border-border px-3 py-2 text-xs pointer-events-auto max-w-md" data-testid="map-unplaced">
            <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1 flex items-center gap-1">
              <CamIcon size={11} /> Caméras à placer ({unplaced.length})
            </div>
            <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
              {unplaced.slice(0, 20).map((c) => (
                <button key={c.id} onClick={() => placeCameraOnPlan(c.id)}
                  className="border border-border px-2 py-0.5 hover:bg-secondary/50 hover:border-[#0044FF] text-[11px]"
                  data-testid={`map-place-cam-${c.id}`}>
                  <span className="w-1.5 h-1.5 inline-block rounded-full mr-1"
                    style={{ background: STATUS_COLOR[c.status] || "#71717a" }} />
                  {c.name}
                </button>
              ))}
              {unplaced.length > 20 && <span className="text-muted-foreground">+{unplaced.length - 20}</span>}
            </div>
          </div>
        )}

        {/* Canvas */}
        <Stage
          ref={stageRef}
          width={stageSize.w}
          height={stageSize.h}
          x={stagePos.x} y={stagePos.y}
          scaleX={scale} scaleY={scale}
          draggable
          onDragEnd={(e) => setStagePos({ x: e.target.x(), y: e.target.y() })}
          onWheel={onWheel}
          onMouseDown={(e) => {
            // click on empty stage (not a camera) → clear selection
            if (e.target === e.target.getStage()) setSelectedCamId(null);
          }}
        >
          <Layer>
            {selectedPlan?.image_data_uri && (
              <PlanBackground src={selectedPlan.image_data_uri} onSize={(w, h) => setPlanSize({ w, h })} />
            )}
            {!selectedPlan && (
              <Text text="Sélectionnez ou importez un plan pour commencer"
                x={40} y={40} fontSize={16} fill="#71717a" />
            )}
            {selectedPlan && camerasOnPlan.length === 0 && (
              <Text text="Aucune caméra sur ce plan. Cliquez sur une caméra dans la liste (en bas) pour la placer."
                x={40} y={planSize.h / 2} fontSize={13} fill="#a1a1aa" width={planSize.w - 80} align="center" />
            )}
            {camerasOnPlan.map((c) => (
              <CameraNode
                key={c.id}
                cam={c}
                selected={selectedCamId === c.id}
                onDrag={onCamDrag}
                onDragEnd={onCamDragEnd}
                onSelect={setSelectedCamId}
                onDblClick={(id) => navigate(`/cameras?focus=${id}`)}
              />
            ))}
          </Layer>
        </Stage>
      </div>

      {/* Camera panel */}
      {selectedCam && (
        <CameraPanel
          camera={selectedCam}
          onClose={() => setSelectedCamId(null)}
          onChange={onCameraChange}
          onOpenInCenter={() => navigate(`/cameras?focus=${selectedCam.id}`)}
        />
      )}
    </div>
  );
}
