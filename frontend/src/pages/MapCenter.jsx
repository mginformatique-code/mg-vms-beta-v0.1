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
  Plus, Save, Search, Settings2, Trash2, Upload, X, ZoomIn, ZoomOut, Activity,
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

// v0.5.2.c · Phase 2 — heuristique qualité de couverture.
// Le cône est coloré selon la combinaison (angle horizontal, portée) et la
// hauteur d'installation. Ce n'est pas une simulation optique, juste un
// signal visuel pour l'installateur.
//   Vert  = couverture "correcte" (angle 60-100° · portée 15-30m · hauteur 2.5-4m)
//   Jaune = couverture moyenne
//   Rouge = limite (angle trop large, portée trop courte/longue)
const COVERAGE_COLOR = {
  good: "#00E676",
  medium: "#FFB800",
  poor: "#FF3333",
};
function coverageQuality(pos) {
  const a = pos?.angle_h ?? DEFAULT_CAM.angle_h;
  const r = pos?.range_m ?? DEFAULT_CAM.range_m;
  const h = pos?.height_m ?? DEFAULT_CAM.height_m;
  let score = 100;
  if (a < 40 || a > 130) score -= 30; // trop étroit ou fisheye
  else if (a < 60 || a > 110) score -= 15;
  if (r < 8 || r > 40) score -= 30;
  else if (r < 15 || r > 30) score -= 10;
  if (h < 2 || h > 6) score -= 25;
  else if (h < 2.5 || h > 4.5) score -= 10;
  if (score >= 75) return "good";
  if (score >= 45) return "medium";
  return "poor";
}

// Détection des rôles caméra pour badges (heuristique légère)
function detectCameraRoles(cam) {
  const plugins = (cam.enabled_plugins || []).map((p) => p.toLowerCase());
  const roles = [];
  if (plugins.some((p) => p.includes("alpr") || p.includes("anpr"))) roles.push("anpr");
  if ((cam.driver || "").toLowerCase().includes("ptz") ||
      (cam.model || "").toLowerCase().includes("ptz") ||
      cam.is_ptz) roles.push("ptz");
  if ((cam.model || "").toLowerCase().includes("thermal") ||
      plugins.includes("thermal")) roles.push("thermal");
  if (cam.record_enabled) roles.push("rec");
  if (cam.detect_enabled) roles.push("ai");
  return roles;
}
const ROLE_LABELS = {
  anpr: "ANPR", ptz: "PTZ", thermal: "TH", ai: "IA", rec: "REC",
};
const ROLE_COLORS = {
  anpr: "#0044FF", ptz: "#A855F7", thermal: "#F97316",
  ai: "#00A2FF", rec: "#FF3333",
};

// v0.5.2.c · Phase 3 — audit : détecte les caméras "incomplètes"
function auditCamera(cam) {
  const pos = cam.map_position || {};
  const flags = [];
  if (!cam.status || cam.status === "offline") flags.push("offline");
  if (!(pos.photos && pos.photos.length)) flags.push("no_photo");
  if (pos.height_m == null) flags.push("no_height");
  if (pos.angle_h == null) flags.push("no_angle");
  if (pos.x == null || pos.y == null) flags.push("no_place");
  if (!cam.driver) flags.push("no_driver");
  if (!cam.firmware) flags.push("no_firmware");
  return flags;
}
const AUDIT_LABEL = {
  offline: "Hors ligne",
  no_photo: "Sans photo",
  no_height: "Hauteur non renseignée",
  no_angle: "Angle non renseigné",
  no_place: "Non positionnée",
  no_driver: "Sans driver",
  no_firmware: "Firmware absent",
};
// Types de photos gérées
const PHOTO_TYPES = [
  { id: "real", label: "Réelle" },
  { id: "install", label: "Installation" },
  { id: "cable", label: "Câblage" },
  { id: "cabinet", label: "Armoire" },
  { id: "env", label: "Environnement" },
];

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
function CameraNode({ cam, selected, layers, auditMode, auditFlags, onDrag, onDragEnd, onSelect, onDblClick }) {
  const pos = cam.map_position || {};
  const rot = pos.rotation || 0;
  const range = pos.range_m ? pos.range_m * 4 : 60; // 4 px = 1 m visuel
  const angleH = pos.angle_h || 90;
  const status = cam.status || "offline";
  const dotColor = STATUS_COLOR[status] || "#71717a";
  // v0.5.2.c · Couleur du cône = qualité de couverture (vert/jaune/rouge).
  const covColor = COVERAGE_COLOR[coverageQuality(pos)];
  const roles = detectCameraRoles(cam);
  const showFov = layers?.fov !== false;
  const showName = layers?.name !== false;
  const showBadges = layers?.badges !== false;
  const showStatus = layers?.status !== false;
  const hasAuditIssue = auditMode && auditFlags && auditFlags.length > 0;

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
      {showFov && (
        <Wedge
          radius={range}
          angle={angleH}
          rotation={-angleH / 2 - 90}
          fill={covColor}
          opacity={selected ? 0.32 : 0.20}
          stroke={covColor}
          strokeWidth={selected ? 1.5 : 0.5}
        />
      )}
      {/* Icône caméra */}
      <Circle radius={9} fill="#0d1117" stroke={covColor} strokeWidth={2} />
      <Rect x={-2} y={-14} width={4} height={6} fill={covColor} />
      {/* Point de statut */}
      {showStatus && <Circle x={8} y={-8} radius={3} fill={dotColor} />}
      {/* Nom (contre-rotation) */}
      {showName && (
        <Text
          text={cam.name || cam.id?.slice(0, 6)}
          fontSize={11}
          fill="#e6e6e6"
          rotation={-rot}
          x={12}
          y={-6}
          listening={false}
        />
      )}
      {/* Badges rôles (contre-rotation, en dessous du cercle) */}
      {showBadges && roles.length > 0 && (
        <Group rotation={-rot} y={16} listening={false}>
          {roles.map((r, i) => (
            <Group key={r} x={i * 26 - roles.length * 13}>
              <Rect width={22} height={11} cornerRadius={2} fill={ROLE_COLORS[r]} opacity={0.9} />
              <Text text={ROLE_LABELS[r]} fontSize={8} fill="#fff"
                width={22} height={11} align="center" verticalAlign="middle"
                fontStyle="bold" />
            </Group>
          ))}
        </Group>
      )}
      {/* Halo audit (issues) — jaune si des flags manquent */}
      {hasAuditIssue && (
        <Circle radius={16} stroke="#FFB800" strokeWidth={2.5} dash={[2, 3]} opacity={0.9} />
      )}
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
  const flags = auditCamera(camera);

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

      {flags.length > 0 && (
        <div className="px-4 py-2 bg-[#FFB800]/10 border-b border-[#FFB800]/40" data-testid="map-camera-audit-flags">
          <div className="text-[10px] uppercase tracking-[0.15em] text-[#FFB800] mb-1">
            Audit — {flags.length} point(s)
          </div>
          <div className="flex flex-wrap gap-1">
            {flags.map((f) => (
              <span key={f} className="text-[9px] mono uppercase tracking-wider px-1.5 py-0.5 border border-[#FFB800] text-[#FFB800]">
                {AUDIT_LABEL[f] || f}
              </span>
            ))}
          </div>
        </div>
      )}

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

        {/* v0.5.2.c · Phase 3 — Photos d'installation */}
        <div className="pt-3 border-t border-border">
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
            <CamIcon size={11} /> Photos ({(local.photos || []).length})
          </div>
          <div className="grid grid-cols-3 gap-1 mb-2">
            {(local.photos || []).map((ph, i) => (
              <div key={i} className="relative group aspect-square bg-black/30 border border-border overflow-hidden" data-testid={`map-cam-photo-${i}`}>
                <img src={ph.data_uri} alt={ph.type} className="w-full h-full object-cover" />
                <div className="absolute top-0 left-0 right-0 text-[8px] uppercase tracking-wider px-1 py-0.5 bg-black/70 text-center">
                  {PHOTO_TYPES.find((t) => t.id === ph.type)?.label || ph.type}
                </div>
                <button
                  onClick={() => {
                    const next = (local.photos || []).filter((_, idx) => idx !== i);
                    set("photos", next);
                  }}
                  className="absolute top-0 right-0 bg-black/70 hover:bg-[#FF3333] opacity-0 group-hover:opacity-100 transition p-0.5"
                  title="Supprimer"
                >
                  <X size={10} />
                </button>
              </div>
            ))}
            <label className="aspect-square border-2 border-dashed border-border flex flex-col items-center justify-center cursor-pointer hover:bg-secondary/40 text-[10px] text-muted-foreground gap-1"
              data-testid="map-cam-photo-upload">
              <Upload size={13} />
              <span>Ajouter</span>
              <input type="file" accept="image/*" className="hidden"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  if (f.size > 4 * 1024 * 1024) { toast.error("Photo > 4 MB"); return; }
                  const data = await fileToDataUri(f);
                  const kind = window.prompt(
                    "Type de photo ? (real / install / cable / cabinet / env)",
                    "install",
                  ) || "install";
                  const next = [...(local.photos || []),
                    { type: kind, data_uri: data, uploaded_at: new Date().toISOString() }];
                  set("photos", next);
                }} />
            </label>
          </div>
        </div>
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
// Phase 4 — Outils de mesure (distance/surface/rayon)
// ─────────────────────────────────────────────────────────────────────
function MeasureLayer({ tool, measurements, currentPts, setMeasurements, scaleMPerPx }) {
  const spx = scaleMPerPx || 0.05; // fallback 5 cm/px si pas d'échelle
  const distMeters = (p1, p2) => Math.hypot(p1.x - p2.x, p1.y - p2.y) * spx;
  const polyArea = (pts) => {
    // Formule du lacet
    let a = 0;
    for (let i = 0; i < pts.length; i++) {
      const j = (i + 1) % pts.length;
      a += pts[i].x * pts[j].y - pts[j].x * pts[i].y;
    }
    return Math.abs(a) / 2 * spx * spx;
  };
  return (
    <>
      {measurements.map((m, idx) => {
        if (m.tool === "distance") {
          const [p1, p2] = m.pts;
          const d = distMeters(p1, p2);
          return (
            <Group key={idx} listening={false}>
              <Line points={[p1.x, p1.y, p2.x, p2.y]} stroke="#00E676" strokeWidth={1.5} dash={[5, 3]} />
              <Text x={(p1.x + p2.x) / 2 + 4} y={(p1.y + p2.y) / 2 - 8}
                text={`${d.toFixed(2)} m`} fontSize={11} fill="#00E676" />
            </Group>
          );
        }
        if (m.tool === "surface") {
          const pts = m.pts.flatMap((p) => [p.x, p.y]);
          const a = polyArea(m.pts);
          return (
            <Group key={idx} listening={false}>
              <Line points={[...pts, m.pts[0].x, m.pts[0].y]} stroke="#00A2FF" strokeWidth={1.5} closed={false} />
              <Text x={m.pts[0].x + 4} y={m.pts[0].y - 8}
                text={`${a.toFixed(1)} m²`} fontSize={11} fill="#00A2FF" />
            </Group>
          );
        }
        if (m.tool === "radius") {
          const [c, edge] = m.pts;
          const r = Math.hypot(edge.x - c.x, edge.y - c.y);
          return (
            <Group key={idx} listening={false}>
              <Circle x={c.x} y={c.y} radius={r} stroke="#F97316" strokeWidth={1.5} dash={[5, 3]} />
              <Text x={c.x + 4} y={c.y - 8} text={`R = ${(r * spx).toFixed(2)} m`} fontSize={11} fill="#F97316" />
            </Group>
          );
        }
        return null;
      })}
      {tool && currentPts.length > 0 && (
        <Line
          points={currentPts.flatMap((p) => [p.x, p.y])}
          stroke="#FFB800" strokeWidth={1.5} dash={[5, 3]}
          listening={false}
        />
      )}
    </>
  );
}

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

  // v0.5.2.c · Phase 3 — mode audit + layers
  const [auditMode, setAuditMode] = useState(false);
  const [layers, setLayers] = useState({ fov: true, name: true, badges: true, status: true });
  // v0.5.2.c · Phase 4 — outils de mesure
  const [measureTool, setMeasureTool] = useState(null); // null | 'distance' | 'surface' | 'radius'
  const [measurements, setMeasurements] = useState([]);
  const [measurePts, setMeasurePts] = useState([]);

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
      setMeasurements([]); setMeasurePts([]); setMeasureTool(null);
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

  // v0.5.2.c · Phase 3 — synthèse audit (nb caméras par flag)
  const auditIndex = useMemo(() => {
    const perCam = {};
    camerasOnPlan.forEach((c) => { perCam[c.id] = auditCamera(c); });
    return perCam;
  }, [camerasOnPlan]);
  const auditSummary = useMemo(() => {
    const s = {};
    Object.values(auditIndex).forEach((flags) => {
      flags.forEach((f) => { s[f] = (s[f] || 0) + 1; });
    });
    return s;
  }, [auditIndex]);

  // Handler clic canvas — outils de mesure
  const onStageMouseDown = (e) => {
    if (!measureTool) {
      if (e.target === e.target.getStage()) setSelectedCamId(null);
      return;
    }
    const stage = e.target.getStage();
    const p = stage.getPointerPosition();
    const local = { x: (p.x - stage.x()) / stage.scaleX(),
                    y: (p.y - stage.y()) / stage.scaleY() };
    const next = [...measurePts, local];
    if (measureTool === "distance" && next.length === 2) {
      setMeasurements((ms) => [...ms, { tool: "distance", pts: next }]);
      setMeasurePts([]);
      return;
    }
    if (measureTool === "radius" && next.length === 2) {
      setMeasurements((ms) => [...ms, { tool: "radius", pts: next }]);
      setMeasurePts([]);
      return;
    }
    setMeasurePts(next);
  };
  const finishSurface = () => {
    if (measureTool === "surface" && measurePts.length >= 3) {
      setMeasurements((ms) => [...ms, { tool: "surface", pts: measurePts }]);
      setMeasurePts([]);
    }
  };

  // v0.5.2.c · Phase 4 — exports
  const exportPng = () => {
    const uri = stageRef.current?.toDataURL({ pixelRatio: 2 });
    if (!uri) return;
    const a = document.createElement("a");
    a.href = uri;
    a.download = `map-${selectedPlan?.name || "plan"}.png`;
    a.click();
  };
  const exportCameraCsv = () => {
    const rows = [
      ["Nom", "IP", "Statut", "Driver", "Modèle", "Hauteur (m)",
        "Angle H (°)", "Portée (m)", "Rotation (°)", "Objectif (mm)",
        "Technicien", "N° série", "Date install", "Notes"],
    ];
    camerasOnPlan.forEach((c) => {
      const p = c.map_position || {};
      rows.push([
        c.name, c.ip || "", c.status || "", c.driver || "", c.model || "",
        p.height_m ?? "", p.angle_h ?? "", p.range_m ?? "", p.rotation ?? "",
        p.lens_mm ?? "", p.technician || "", p.serial || "",
        p.install_date || "", (p.install_notes || "").replace(/[\r\n,]+/g, " "),
      ]);
    });
    const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const uri = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
    const a = document.createElement("a");
    a.href = uri;
    a.download = `cameras-${selectedPlan?.name || "plan"}.csv`;
    a.click();
  };
  const exportAuditCsv = () => {
    const rows = [["Caméra", "IP", "Statut", "Problèmes"]];
    camerasOnPlan.forEach((c) => {
      const flags = auditIndex[c.id] || [];
      if (flags.length === 0) return;
      rows.push([c.name, c.ip || "", c.status || "",
                  flags.map((f) => AUDIT_LABEL[f] || f).join(" | ")]);
    });
    const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const uri = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
    const a = document.createElement("a");
    a.href = uri;
    a.download = `audit-${selectedPlan?.name || "plan"}.csv`;
    a.click();
  };
  const exportPdf = async () => {
    // Export PDF minimal via une nouvelle fenêtre imprimable
    const uri = stageRef.current?.toDataURL({ pixelRatio: 2 });
    if (!uri) return;
    const w = window.open("", "_blank");
    if (!w) { toast.error("Popup bloquée"); return; }
    const cams = camerasOnPlan.map((c) => {
      const p = c.map_position || {};
      return `<tr>
        <td>${c.name}</td><td>${c.ip || "—"}</td>
        <td>${c.driver || "—"}</td>
        <td>${p.height_m ?? "—"} m</td>
        <td>${p.angle_h ?? "—"}°</td>
        <td>${p.range_m ?? "—"} m</td>
        <td>${p.lens_mm ?? "—"} mm</td>
      </tr>`;
    }).join("");
    w.document.write(`<!doctype html><html><head><title>MG-VMS · ${selectedPlan?.name || "plan"}</title>
      <style>body{font-family:sans-serif;margin:20px;color:#111}
      h1{font-size:20px;margin-bottom:4px}
      table{width:100%;border-collapse:collapse;margin-top:16px;font-size:11px}
      th,td{border:1px solid #ccc;padding:4px 6px;text-align:left}
      th{background:#f4f4f4}
      img{max-width:100%;border:1px solid #ccc}
      </style></head><body>
      <h1>Rapport d'implantation — ${selectedPlan?.name || "plan"}</h1>
      <div style="color:#666;font-size:12px">Généré par MG-VMS · ${new Date().toLocaleString()}</div>
      <img src="${uri}" alt="Plan" />
      <table><thead><tr>
        <th>Caméra</th><th>IP</th><th>Driver</th><th>Hauteur</th>
        <th>Angle H</th><th>Portée</th><th>Objectif</th>
      </tr></thead><tbody>${cams}</tbody></table>
      <script>setTimeout(()=>window.print(),400)</script>
      </body></html>`);
    w.document.close();
  };

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
        <div className="absolute top-2 left-2 right-2 z-10 flex items-center gap-2 pointer-events-none flex-wrap">
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

          {/* Toggles couches (layers) */}
          <div className="bg-card/90 backdrop-blur border border-border px-2 py-1 text-[11px] pointer-events-auto flex items-center gap-2" data-testid="map-layers">
            <LayersIcon size={12} className="text-muted-foreground" />
            {[
              { k: "fov", label: "FOV" },
              { k: "name", label: "Noms" },
              { k: "badges", label: "IA" },
              { k: "status", label: "Statut" },
            ].map((l) => (
              <label key={l.k} className="flex items-center gap-1 cursor-pointer" data-testid={`map-layer-${l.k}`}>
                <input type="checkbox" checked={layers[l.k]}
                  onChange={() => setLayers({ ...layers, [l.k]: !layers[l.k] })}
                  className="accent-[#0044FF]" />
                {l.label}
              </label>
            ))}
          </div>

          {/* Mode Audit */}
          <button
            onClick={() => setAuditMode((v) => !v)}
            className={`bg-card/90 backdrop-blur border px-3 py-1.5 text-xs pointer-events-auto flex items-center gap-2 ${auditMode ? "border-[#FFB800] text-[#FFB800]" : "border-border"}`}
            data-testid="map-audit-toggle"
          >
            <Activity size={13} /> Audit
            {auditMode && Object.keys(auditSummary).length > 0 && (
              <span className="mono">{Object.values(auditSummary).reduce((a, b) => a + b, 0)}</span>
            )}
          </button>

          {/* Outils de mesure */}
          <div className="bg-card/90 backdrop-blur border border-border p-1 pointer-events-auto flex items-center gap-1" data-testid="map-measure">
            {[
              { id: "distance", label: "D", title: "Distance (2 clics)" },
              { id: "surface", label: "S", title: "Surface (double-clic pour finir)" },
              { id: "radius", label: "R", title: "Rayon (centre puis bord)" },
            ].map((m) => (
              <button key={m.id}
                onClick={() => { setMeasureTool(measureTool === m.id ? null : m.id); setMeasurePts([]); }}
                className={`px-2 py-1 text-[11px] mono ${measureTool === m.id ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}
                title={m.title} data-testid={`map-measure-${m.id}`}
              >{m.label}</button>
            ))}
            {measurements.length > 0 && (
              <button onClick={() => setMeasurements([])} className="px-2 py-1 text-[11px] text-[#FF3333]" title="Effacer">
                <Trash2 size={11} />
              </button>
            )}
          </div>

          {/* Exports */}
          <div className="bg-card/90 backdrop-blur border border-border p-1 pointer-events-auto flex items-center gap-1" data-testid="map-exports">
            <button onClick={exportPng} className="px-2 py-1 text-[11px] hover:bg-secondary" title="Export PNG" data-testid="map-export-png">PNG</button>
            <button onClick={exportPdf} className="px-2 py-1 text-[11px] hover:bg-secondary" title="Rapport PDF (imprimable)" data-testid="map-export-pdf">PDF</button>
            <button onClick={exportCameraCsv} className="px-2 py-1 text-[11px] hover:bg-secondary" title="CSV caméras" data-testid="map-export-csv">CSV</button>
            {auditMode && (
              <button onClick={exportAuditCsv} className="px-2 py-1 text-[11px] text-[#FFB800] hover:bg-secondary" title="Rapport audit CSV" data-testid="map-export-audit">AUDIT</button>
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

        {/* Audit panel — liste des caméras avec problèmes */}
        {auditMode && Object.keys(auditSummary).length > 0 && (
          <div className="absolute top-14 right-2 z-10 bg-card/95 border border-[#FFB800]/40 w-72 max-h-[70vh] overflow-y-auto pointer-events-auto" data-testid="map-audit-panel">
            <div className="px-3 py-2 border-b border-border">
              <div className="text-[10px] uppercase tracking-[0.15em] text-[#FFB800] flex items-center gap-1">
                <Activity size={11} /> Audit — Synthèse
              </div>
              <div className="grid grid-cols-2 gap-1 mt-2 text-[10px]">
                {Object.entries(auditSummary).map(([f, n]) => (
                  <div key={f} className="flex items-center gap-1">
                    <span className="w-1 h-1 rounded-full bg-[#FFB800]" />
                    <span className="flex-1 truncate">{AUDIT_LABEL[f]}</span>
                    <span className="mono">{n}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="divide-y divide-border/40">
              {camerasOnPlan
                .filter((c) => (auditIndex[c.id] || []).length > 0)
                .map((c) => (
                  <button key={c.id} onClick={() => setSelectedCamId(c.id)}
                    className="w-full text-left px-3 py-2 hover:bg-secondary/40" data-testid={`map-audit-cam-${c.id}`}>
                    <div className="text-xs font-medium truncate">{c.name}</div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {(auditIndex[c.id] || []).map((f) => (
                        <span key={f} className="text-[8px] mono uppercase tracking-wider px-1 py-0.5 border border-[#FFB800] text-[#FFB800]">
                          {AUDIT_LABEL[f]}
                        </span>
                      ))}
                    </div>
                  </button>
                ))}
            </div>
          </div>
        )}

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
          draggable={!measureTool}
          onDragEnd={(e) => setStagePos({ x: e.target.x(), y: e.target.y() })}
          onWheel={onWheel}
          onMouseDown={onStageMouseDown}
          onDblClick={(e) => {
            // double-clic pour terminer une surface
            if (measureTool === "surface") finishSurface();
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
                layers={layers}
                auditMode={auditMode}
                auditFlags={auditIndex[c.id]}
                onDrag={onCamDrag}
                onDragEnd={onCamDragEnd}
                onSelect={setSelectedCamId}
                onDblClick={(id) => navigate(`/cameras?focus=${id}`)}
              />
            ))}
            <MeasureLayer
              tool={measureTool}
              measurements={measurements}
              currentPts={measurePts}
              setMeasurements={setMeasurements}
              scaleMPerPx={selectedPlan?.scale_m_per_px}
            />
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
