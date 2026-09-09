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
 *
 * v3.54 · Carte interactive ("carte_live") : fond de carte navigable
 * (OpenStreetMap / satellite Esri, gratuits, sans clé API) en alternative
 * à l'image statique — voir LiveMapCanvas.jsx et lib/mapCenterHelpers.js.
 * Additif : le canvas Konva/l'image statique restent inchangés pour tous
 * les plans existants. Import PDF (rasterisé côté navigateur en PNG,
 * pdfjs-dist) ajouté sur le même pipeline d'import que les images.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Stage, Layer, Image as KonvaImage, Rect, Circle, Group, Text, Wedge, Line } from "react-konva";
import useImage from "use-image";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  Building2, Camera as CamIcon, ChevronDown, ChevronRight, Compass, ExternalLink,
  FilePlus, FolderTree, HardDrive, Layers as LayersIcon, MapPin, Move, MapPinned,
  Plus, Save, Search, Settings2, Trash2, Upload, X, ZoomIn, ZoomOut, Activity,
  Link2, Unlink, Pencil, Box as BoxIcon,
} from "lucide-react";
import LiveMapCanvas from "./LiveMapCanvas";
import MapContextMenu from "@/components/MapContextMenu";
import AddressPickerModal from "@/components/AddressPickerModal";
import { generateMapReportPdf } from "@/lib/mapReportPdf";
import {
  DEFAULT_CAM, STATUS_COLOR, COVERAGE_COLOR, coverageQuality,
  detectCameraRoles, ROLE_LABELS, ROLE_COLORS, auditCamera, AUDIT_LABEL,
  TYPE_ICON, EQUIPMENT_TYPES, LINK_TYPES,
} from "@/lib/mapCenterHelpers";

// ─────────────────────────────────────────────────────────────────────
// Constantes visuelles
// ─────────────────────────────────────────────────────────────────────
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
// v3.55 · Petit "icône" rond coloré pour le sélecteur de type de
// connexion dans MapContextMenu (qui attend un composant `icon`).
function colorDotIcon(color) {
  return function ColorDot() {
    return <span style={{ width: 10, height: 10, borderRadius: 5, background: color, display: "inline-block" }} />;
  };
}

async function fileToDataUri(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

// v3.54 · Import PDF — rasterise la 1ère page en PNG côté navigateur
// (pdfjs-dist) avant de réutiliser TEL QUEL le pipeline d'import image
// existant (onFilePicked ci-dessous) : pas de nouvel endpoint, le backend
// ne voit jamais de PDF, juste une image comme les autres.
async function pdfFirstPageToDataUri(file) {
  const pdfjsLib = await import("pdfjs-dist");
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url
  ).toString();
  const buf = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
  const page = await pdf.getPage(1);
  const viewport = page.getViewport({ scale: 2 });
  const canvas = document.createElement("canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  const ctx = canvas.getContext("2d");
  await page.render({ canvasContext: ctx, viewport }).promise;
  return { dataUri: canvas.toDataURL("image/png"), width: viewport.width, height: viewport.height };
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
function CameraNode({ cam, selected, layers, auditMode, auditFlags, onDrag, onDragEnd, onSelect, onDblClick, onContextMenu }) {
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
      onClick={(e) => onSelect(cam.id, e.evt)}
      onTap={() => onSelect(cam.id)}
      onDblClick={() => onDblClick && onDblClick(cam.id)}
      onDblTap={() => onDblClick && onDblClick(cam.id)}
      onContextMenu={(e) => { e.evt.preventDefault(); e.cancelBubble = true; onContextMenu && onContextMenu(cam.id, e.evt); }}
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
// v3.55 · Équipement réseau (switch/NVR/routeur/...) — même objet que
// Réseau → Supervision réseau (db.equipment), juste positionné ici.
// Pas de FOV/badges/audit (propres aux caméras) : icône + statut + nom.
// ─────────────────────────────────────────────────────────────────────
// v3.55 · Abréviation par type — un vrai rendu d'icône lucide-react DANS
// le canvas Konva demanderait de sérialiser le SVG en image à la volée
// (fragile, coût inutile pour un petit glyphe statique) ; le badge texte
// est natif Konva, fiable, et déjà lisible à cette taille. La vraie icône
// lucide reste utilisée partout ailleurs (tiroir, menu contextuel,
// Network.jsx) — seul le glyphe SUR le canvas est simplifié.
const TYPE_ABBR = { Switch: "SW", Routeur: "RT", NAS: "NAS", UPS: "UPS", Serveur: "SRV", NVR: "NVR", Générique: "?" };

function EquipmentNode({ eq, selected, showName, showStatus, onDrag, onDragEnd, onSelect, onContextMenu }) {
  const dotColor = STATUS_COLOR[eq.status] || "#71717a";
  return (
    <Group
      x={eq.x || 0}
      y={eq.y || 0}
      draggable
      onDragMove={(e) => onDrag(eq.id, { x: e.target.x(), y: e.target.y() })}
      onDragEnd={(e) => onDragEnd(eq.id, { x: e.target.x(), y: e.target.y() })}
      onClick={(e) => onSelect(eq.id, e.evt)}
      onTap={() => onSelect(eq.id)}
      onContextMenu={(e) => { e.evt.preventDefault(); e.cancelBubble = true; onContextMenu && onContextMenu(eq.id, e.evt); }}
    >
      <Rect x={-14} y={-9} width={28} height={18} cornerRadius={3} fill="#0d1117" stroke="#71717a" strokeWidth={2} />
      <Text text={TYPE_ABBR[eq.type] || "?"} fontSize={8} fill="#e6e6e6" fontStyle="bold"
            width={28} height={18} x={-14} y={-9} align="center" verticalAlign="middle" listening={false} />
      {showStatus && <Circle x={14} y={-9} radius={3} fill={dotColor} />}
      {showName && (
        <Text text={eq.name || "—"} fontSize={11} fill="#e6e6e6" x={18} y={-6} listening={false} />
      )}
      {selected && <Rect x={-18} y={-13} width={36} height={26} cornerRadius={4} stroke="#00E676" strokeWidth={2} dash={[3, 3]} />}
    </Group>
  );
}

// ─────────────────────────────────────────────────────────────────────
// v3.55 · Connexion typée (câble) entre deux éléments d'un plan.
// ─────────────────────────────────────────────────────────────────────
function LinkLine({ link, from, to, onContextMenu }) {
  if (!from || !to) return null;
  const meta = LINK_TYPES[link.link_type] || LINK_TYPES.other;
  const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
  return (
    <Group onContextMenu={(e) => { e.evt.preventDefault(); e.cancelBubble = true; onContextMenu && onContextMenu(link.id, e.evt); }}>
      <Line points={[from.x, from.y, to.x, to.y]} stroke={meta.color} strokeWidth={2}
            dash={meta.dashed ? [6, 4] : undefined} hitStrokeWidth={12} />
      {link.label && (
        <Text text={link.label} x={mid.x + 4} y={mid.y - 14} fontSize={10} fill={meta.color} listening={false} />
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
          {/* v3.58 · Corrige "Marque" qui lisait `camera.brand` — un champ
              qui n'existe pas sur le document caméra (voir db.cameras,
              le vrai champ est `manufacturer`) — donc toujours vide,
              signalé par l'utilisateur en comparant avec Camera Center
              (qui, lui, lit déjà le bon champ). "Driver" aligné sur le
              même repli que Camera Center (CameraCenter.jsx) : pas de
              champ dédié en base, toujours "onvif" en pratique. */}
          <div><span className="text-muted-foreground">Marque : </span>{camera.manufacturer || "—"}</div>
          <div><span className="text-muted-foreground">Modèle : </span>{camera.model || "—"}</div>
          <div><span className="text-muted-foreground">Driver : </span>{camera.driver || "onvif"}</div>
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
  onSelectSite, onSelectPlan, onCreateBuilding, onCreatePlan, onCreateLiveMap, onDeletePlan, cameraCounts,
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
                    <button onClick={() => onCreateLiveMap(s.id)}
                      className="text-[10px] text-[#0044FF] hover:underline flex items-center gap-1 ml-2"
                      title="Carte interactive (OpenStreetMap / satellite, gratuite)"
                      data-testid={`map-add-livemap-${s.id}`}>
                      <MapPinned size={10} /> Carte
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
  const Icon = p.type === "carte_live" ? MapPinned : LayersIcon;
  return (
    <div className={`group flex items-center gap-1.5 px-3 py-1 hover:bg-secondary/40 cursor-pointer ${selected ? "bg-[#0044FF]/15 border-l-2 border-[#0044FF]" : ""}`}
      onClick={onSelect} data-testid={`map-plan-${p.id}`}>
      <Icon size={11} className="text-muted-foreground" />
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
  const [reportGenerating, setReportGenerating] = useState(false);
  const [addressPickerOpen, setAddressPickerOpen] = useState(false);
  const pendingLiveMapRef = useRef(null);

  // Data
  const [sites, setSites] = useState([]);
  const [buildings, setBuildings] = useState([]);
  const [plans, setPlans] = useState([]);
  const [selectedSite, setSelectedSite] = useState(null);
  const [selectedPlan, setSelectedPlan] = useState(null); // full doc with image
  const [cameras, setCameras] = useState([]); // cameras on current plan
  const [selectedCamId, setSelectedCamId] = useState(null);

  // v3.55 · Équipements réseau + connexions du plan courant, et menu
  // contextuel clic-droit — voir plan "Carte interactive : clic-droit,
  // équipements réseau, connexions".
  const [equipment, setEquipment] = useState([]); // équipements positionnés sur ce plan
  const [selectedEqId, setSelectedEqId] = useState(null);
  const [links, setLinks] = useState([]);
  const [contextMenu, setContextMenu] = useState(null); // {x, y, items} | null
  const [linkingFrom, setLinkingFrom] = useState(null); // {kind, id} | null

  useEffect(() => {
    if (!linkingFrom) return;
    const onKey = (e) => { if (e.key === "Escape") setLinkingFrom(null); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [linkingFrom]);

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
      const [rp, rc, re, rl] = await Promise.all([
        api.get(`/site-manager/plans/${planId}`),
        api.get(`/site-manager/cameras?plan_id=${planId}`),
        api.get(`/network/equipment?plan_id=${planId}`),
        api.get(`/site-manager/plan-links?plan_id=${planId}`),
      ]);
      setSelectedPlan(rp.data);
      setCameras(rc.data || []);
      setEquipment(re.data || []);
      setLinks(rl.data || []);
      setSelectedCamId(null);
      setSelectedEqId(null);
      setLinkingFrom(null);
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

  // v3.54 · Carte live — Leaflet ne notifie qu'à la fin du glisser (pas
  // d'équivalent continu à onDragMove), donc on met à jour l'état local
  // ET on persiste en un seul geste (onCamDrag seul ne suffirait pas ici).
  const onLiveMapCamDragEnd = (camId, pos) => { onCamDrag(camId, pos); saveCameraPos(camId, pos); };

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
      let dataUri, width, height;
      if (file.type === "application/pdf") {
        const res = await pdfFirstPageToDataUri(file);
        dataUri = res.dataUri; width = res.width; height = res.height;
      } else {
        dataUri = await fileToDataUri(file);
        const img = new window.Image();
        const done = new Promise((resolve) => { img.onload = resolve; img.onerror = resolve; });
        img.src = dataUri;
        await done;
        width = img.width || null; height = img.height || null;
      }
      const name = file.name.replace(/\.[^.]+$/, "");
      const r = await api.post("/site-manager/plans", {
        site_id: siteId, name, type: "autre",
        image_data_uri: dataUri, width, height,
      });
      await refreshAll();
      loadPlan(r.data.id);
      toast.success("Plan importé");
    } catch (e) { toast.error("Import plan refusé"); }
  };

  // v3.54 · Carte interactive (Leaflet/OSM+satellite gratuits) — additive,
  // aucune image stockée (voir PlanInput côté backend).
  // v3.58 · Emplacement initial demandé par ADRESSE (avec suggestions au
  // fil de la frappe, voir AddressPickerModal) plutôt que par
  // latitude/longitude saisies à la main — demande explicite. La
  // géolocalisation navigateur reste proposée dans ce même écran plutôt
  // que comme une étape séparée.
  const applyLiveMapCenter = async (lat, lng) => {
    const pending = pendingLiveMapRef.current;
    if (!pending) return;
    try {
      const r = await api.post("/site-manager/plans", {
        site_id: pending.siteId, name: pending.name, type: "carte_live",
        center_lat: lat, center_lng: lng, zoom: 18,
      });
      await refreshAll();
      loadPlan(r.data.id);
      toast.success("Carte créée");
    } catch (e) { toast.error("Création de la carte refusée"); }
    finally { pendingLiveMapRef.current = null; }
  };
  const createLiveMap = (siteId) => {
    const name = window.prompt("Nom de la carte ?", "Carte");
    if (!name) return;
    pendingLiveMapRef.current = { siteId, name };
    setAddressPickerOpen(true);
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

  // v3.54 · Centre courant de la carte live (mis à jour par LiveMapCanvas
  // sur chaque déplacement) — sert uniquement à placer une NOUVELLE caméra
  // au centre de la vue actuelle, comme le fait déjà le mode pixel avec le
  // centre du plan (planSize.w/2, h/2) ; jamais persisté sur le plan lui-même.
  const [liveMapCenter, setLiveMapCenter] = useState(null);

  const placeCameraOnPlan = async (camId) => {
    if (!selectedPlan) { toast.error("Sélectionnez un plan d'abord"); return; }
    const isLiveMap = selectedPlan.type === "carte_live";
    const placement = isLiveMap
      ? { lat: liveMapCenter?.lat ?? selectedPlan.center_lat ?? 46.6, lng: liveMapCenter?.lng ?? selectedPlan.center_lng ?? 1.9 }
      : { x: planSize.w / 2, y: planSize.h / 2 };
    try {
      await api.put(`/site-manager/cameras/${camId}/position`, {
        plan_id: selectedPlan.id, ...placement,
        rotation: 0, angle_h: DEFAULT_CAM.angle_h, angle_v: DEFAULT_CAM.angle_v,
        range_m: DEFAULT_CAM.range_m, height_m: DEFAULT_CAM.height_m, fixture: "wall",
      });
      const r = await api.get(`/site-manager/cameras?plan_id=${selectedPlan.id}`);
      setCameras(r.data || []);
      setSelectedCamId(camId);
    } catch (e) { toast.error("Placement caméra refusé"); }
  };

  // v3.55 · "Retirer du plan" — geste qui existait déjà côté API
  // (DELETE /cameras/{id}/position) mais jamais exposé en UI.
  const retireCameraFromPlan = async (camId) => {
    try {
      await api.delete(`/site-manager/cameras/${camId}/position`);
      if (selectedPlan) await loadPlan(selectedPlan.id);
    } catch (e) { toast.error("Retrait refusé"); }
  };

  // ── Équipements réseau (db.equipment, backend/network.py) ─────────
  const saveEquipmentPos = useDebouncedCallback(async (eqId, pos) => {
    try { await api.put(`/network/equipment/${eqId}/position`, pos); }
    catch (e) { toast.error("Sauvegarde position équipement échouée"); }
  }, 400);
  const onEqDrag = (eqId, pos) => {
    setEquipment((es) => es.map((eq) => eq.id === eqId ? { ...eq, ...pos } : eq));
  };
  const onEqDragEnd = (eqId, pos) => saveEquipmentPos(eqId, pos);
  const onLiveMapEqDragEnd = (eqId, pos) => { onEqDrag(eqId, pos); saveEquipmentPos(eqId, pos); };

  const [availableEquipment, setAvailableEquipment] = useState([]);
  const refreshAvailableEquipment = useCallback(() => {
    if (!selectedSite) return;
    api.get(`/network/equipment?site_id=${selectedSite}`).then((r) => {
      setAvailableEquipment(r.data || []);
    }).catch(() => {});
  }, [selectedSite]);
  useEffect(() => { refreshAvailableEquipment(); }, [refreshAvailableEquipment, equipment]);

  const placeEquipmentOnPlan = async (eqId) => {
    if (!selectedPlan) { toast.error("Sélectionnez un plan d'abord"); return; }
    const placement = selectedPlan.type === "carte_live"
      ? { lat: liveMapCenter?.lat ?? selectedPlan.center_lat ?? 46.6, lng: liveMapCenter?.lng ?? selectedPlan.center_lng ?? 1.9 }
      : { x: planSize.w / 2, y: planSize.h / 2 };
    try {
      await api.put(`/network/equipment/${eqId}/position`, { plan_id: selectedPlan.id, ...placement });
      await loadPlan(selectedPlan.id);
      setSelectedEqId(eqId);
    } catch (e) { toast.error("Placement équipement refusé"); }
  };

  // v3.55 · Clic-droit sur une zone vide → "Ajouter un équipement" — crée
  // l'équipement (inventaire réseau réel, voir network.py) puis le
  // positionne directement au point cliqué.
  const createEquipmentAt = async (type, placement) => {
    const name = window.prompt(`Nom du ${type} ?`, type);
    if (!name || !selectedPlan) return;
    try {
      const r = await api.post("/network/equipment", { name, type, site_id: selectedSite });
      await api.put(`/network/equipment/${r.data.id}/position`, { plan_id: selectedPlan.id, ...placement });
      await loadPlan(selectedPlan.id);
      setSelectedEqId(r.data.id);
    } catch (e) { toast.error("Création équipement refusée"); }
  };

  const renameEquipment = async (eq) => {
    const name = window.prompt("Nouveau nom ?", eq.name);
    if (!name || name === eq.name) return;
    try {
      // PUT /network/equipment/{id} remplace le document (EquipmentInput) —
      // on renvoie donc ses propres champs, seul le nom change.
      await api.put(`/network/equipment/${eq.id}`, {
        name, type: eq.type, site_id: eq.site_id, ip: eq.ip || "",
        model: eq.model || "", vendor: eq.vendor || "", parent_id: eq.parent_id || null,
      });
      if (selectedPlan) await loadPlan(selectedPlan.id);
    } catch (e) { toast.error("Renommage refusé"); }
  };

  const removeEquipmentFromPlan = async (eqId) => {
    try {
      await api.delete(`/network/equipment/${eqId}/position`);
      if (selectedPlan) await loadPlan(selectedPlan.id);
    } catch (e) { toast.error("Retrait refusé"); }
  };

  const deleteEquipmentEntirely = async (eq) => {
    if (!window.confirm(`Supprimer définitivement « ${eq.name} » de l'inventaire réseau (pas juste de ce plan) ?`)) return;
    try {
      await api.delete(`/network/equipment/${eq.id}`);
      if (selectedPlan) await loadPlan(selectedPlan.id);
    } catch (e) { toast.error("Suppression refusée"); }
  };

  // ── Connexions (site_plan_links, backend/routes/site_manager.py) ──
  const createLink = async (fromKind, fromId, toKind, toId, linkType) => {
    try {
      await api.post("/site-manager/plan-links", {
        plan_id: selectedPlan.id, from_kind: fromKind, from_id: fromId,
        to_kind: toKind, to_id: toId, link_type: linkType,
      });
      await loadPlan(selectedPlan.id);
    } catch (e) { toast.error("Connexion refusée"); }
  };
  const renameLink = async (link) => {
    const label = window.prompt("Nom de la connexion ?", link.label || "");
    if (label == null) return;
    try {
      await api.put(`/site-manager/plan-links/${link.id}`, { label });
      if (selectedPlan) await loadPlan(selectedPlan.id);
    } catch (e) { toast.error("Renommage refusé"); }
  };
  const deleteLink = async (linkId) => {
    try {
      await api.delete(`/site-manager/plan-links/${linkId}`);
      if (selectedPlan) await loadPlan(selectedPlan.id);
    } catch (e) { toast.error("Suppression refusée"); }
  };

  // "Attacher une connexion" : clic sur la 1ère extrémité arme le mode
  // (bandeau affiché), clic sur la 2e extrémité ouvre le petit sélecteur
  // de type (réutilise MapContextMenu comme simple liste de choix).
  const startLinking = (kind, id) => setLinkingFrom({ kind, id });
  const openLinkTypePicker = (toKind, toId, clientX, clientY) => {
    const from = linkingFrom;
    setLinkingFrom(null);
    if (!from || (from.kind === toKind && from.id === toId)) return;
    setContextMenu({
      x: clientX, y: clientY,
      items: Object.entries(LINK_TYPES).map(([key, meta]) => ({
        type: "item", label: meta.label,
        icon: colorDotIcon(meta.color),
        onClick: () => createLink(from.kind, from.id, toKind, toId, key),
      })),
    });
  };

  const selectedCam = cameras.find((c) => c.id === selectedCamId) || null;
  const camerasOnPlan = cameras;
  // v3.54 · Mesure/export PNG/PDF restent hors périmètre v1 pour une carte
  // live (mesure géo-référencée et export DOM/tuiles = calculs différents
  // du mode pixel Konva) — CSV reste dispo, indépendant du rendu.
  const isLiveMap = selectedPlan?.type === "carte_live";

  // Cameras du site pas encore placées sur ce plan
  const unplaced = availableCams.filter(
    (c) => !camerasOnPlan.some((cp) => cp.id === c.id)
  );
  // v3.55 · Équipements du site pas encore placés sur ce plan.
  const unplacedEquipment = availableEquipment.filter(
    (eq) => !equipment.some((e) => e.id === eq.id)
  );

  // v3.55 · Position (pixels) d'une extrémité de connexion — utilisée pour
  // tracer la ligne en mode Konva ; le mode Leaflet a son équivalent
  // géographique dans LiveMapCanvas.jsx.
  const resolveEndpointPos = useCallback((kind, id) => {
    if (kind === "camera") {
      const c = cameras.find((x) => x.id === id);
      const p = c?.map_position;
      return p && p.x != null && p.y != null ? { x: p.x, y: p.y } : null;
    }
    const eq = equipment.find((x) => x.id === id);
    return eq && eq.x != null && eq.y != null ? { x: eq.x, y: eq.y } : null;
  }, [cameras, equipment]);

  // v3.55 · Constructeurs de menu contextuel — mêmes items dans les deux
  // modes (Konva/Leaflet), MapContextMenu se charge de l'affichage.
  const buildEquipmentSubmenu = (placement) => ({
    type: "submenu", label: "Ajouter un équipement", icon: BoxIcon,
    options: EQUIPMENT_TYPES.map((t) => ({
      label: t, icon: TYPE_ICON[t], onClick: () => createEquipmentAt(t, placement),
    })),
  });
  const cameraMenuItems = (camId, clientX, clientY) => [
    { type: "item", label: "Attacher une connexion", icon: Link2, onClick: () => startLinking("camera", camId) },
    { type: "item", label: "Retirer du plan", icon: Unlink, onClick: () => retireCameraFromPlan(camId) },
    { type: "item", label: "Voir dans Camera Center", icon: ExternalLink, onClick: () => navigate(`/cameras?focus=${camId}`) },
  ];
  const equipmentMenuItems = (eq) => [
    { type: "item", label: "Renommer", icon: Pencil, onClick: () => renameEquipment(eq) },
    { type: "item", label: "Attacher une connexion", icon: Link2, onClick: () => startLinking("equipment", eq.id) },
    { type: "item", label: "Retirer du plan", icon: Unlink, onClick: () => removeEquipmentFromPlan(eq.id) },
    { type: "separator" },
    { type: "item", label: "Supprimer définitivement", icon: Trash2, danger: true, onClick: () => deleteEquipmentEntirely(eq) },
  ];
  const linkMenuItems = (link) => [
    { type: "item", label: "Renommer", icon: Pencil, onClick: () => renameLink(link) },
    { type: "item", label: "Supprimer", icon: Trash2, danger: true, onClick: () => deleteLink(link.id) },
  ];

  // Clic (gauche) sur une caméra/un équipement pendant "Attacher une
  // connexion" = choix de la 2e extrémité, sinon sélection normale.
  const onSelectCamera = (camId, evt) => {
    if (linkingFrom) { openLinkTypePicker("camera", camId, evt?.clientX ?? 0, evt?.clientY ?? 0); return; }
    setSelectedCamId(camId); setSelectedEqId(null);
  };
  const onSelectEquipment = (eqId, evt) => {
    if (linkingFrom) { openLinkTypePicker("equipment", eqId, evt?.clientX ?? 0, evt?.clientY ?? 0); return; }
    setSelectedEqId(eqId); setSelectedCamId(null);
  };

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
      if (e.target === e.target.getStage()) { setSelectedCamId(null); setSelectedEqId(null); }
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
  // v3.57 · Remplace l'ancien export minimal (window.print() + une seule
  // image aplatie) par un vrai rapport multi-pages "CCTV design tool"
  // (page de garde, vue d'ensemble, une page détaillée par caméra, liste
  // récapitulative) — voir lib/mapReportPdf.js. Identité/textes et
  // bibliothèque photo/objectifs par modèle réglés depuis la nouvelle page
  // /map/report-settings, chargés ici à la demande (pas de state global
  // pour un contenu utilisé uniquement au moment de l'export).
  const exportPdf = async () => {
    if (camerasOnPlan.length === 0) { toast.error("Aucune caméra positionnée sur ce plan"); return; }
    setReportGenerating(true);
    try {
      const [tplRes, catalogRes] = await Promise.all([
        api.get("/site-manager/report-template"),
        api.get("/site-manager/camera-catalog"),
      ]);
      const siteName = sites.find((s) => s.id === selectedSite)?.name || "";
      await generateMapReportPdf({
        plan: selectedPlan,
        siteName,
        cameras: camerasOnPlan,
        stageRef,
        isLiveMap,
        reportTemplate: tplRes.data,
        catalogList: catalogRes.data,
      });
    } catch (e) {
      toast.error("Échec de la génération du rapport PDF");
    } finally {
      setReportGenerating(false);
    }
  };

  return (
    <div className="h-[calc(100vh-40px)] flex" data-testid="map-center">
      <AddressPickerModal
        open={addressPickerOpen}
        onClose={() => setAddressPickerOpen(false)}
        onPick={applyLiveMapCenter}
      />

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
        onCreateLiveMap={createLiveMap}
        onDeletePlan={deletePlan}
        cameraCounts={cameraCounts}
      />

      {/* Hidden file inputs per site (used by "add plan") */}
      {sites.map((s) => (
        <input key={s.id} id={`hidden-plan-upload-${s.id}`} type="file"
          accept="image/*,application/pdf"
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

          {/* Outils de mesure — hors périmètre v1 pour une carte live */}
          {!isLiveMap && (
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
          )}

          {/* Exports — PNG reste réservé aux plans image (simple
              stage.toDataURL() Konva) ; le rapport PDF (v3.57) recompose
              lui-même l'image pour une carte live (voir
              lib/mapReportRenderer.js), donc disponible dans les deux
              modes. CSV indépendant du rendu, disponible partout. */}
          <div className="bg-card/90 backdrop-blur border border-border p-1 pointer-events-auto flex items-center gap-1" data-testid="map-exports">
            {!isLiveMap && (
              <button onClick={exportPng} className="px-2 py-1 text-[11px] hover:bg-secondary" title="Export PNG" data-testid="map-export-png">PNG</button>
            )}
            <button onClick={exportPdf} disabled={reportGenerating}
              className="px-2 py-1 text-[11px] hover:bg-secondary disabled:opacity-50"
              title="Rapport PDF détaillé (page de garde, vue d'ensemble, une page par caméra)"
              data-testid="map-export-pdf">
              {reportGenerating ? "Génération…" : "PDF"}
            </button>
            <button onClick={() => navigate("/map/report-settings")}
              className="px-2 py-1 text-[11px] hover:bg-secondary" title="Réglages du rapport PDF"
              data-testid="map-report-settings-link">
              <Settings2 size={12} />
            </button>
            <button onClick={exportCameraCsv} className="px-2 py-1 text-[11px] hover:bg-secondary" title="CSV caméras" data-testid="map-export-csv">CSV</button>
            {auditMode && (
              <button onClick={exportAuditCsv} className="px-2 py-1 text-[11px] text-[#FFB800] hover:bg-secondary" title="Rapport audit CSV" data-testid="map-export-audit">AUDIT</button>
            )}
          </div>

          {/* Zoom — spécifique au canvas Konva, Leaflet a déjà les siens */}
          {!isLiveMap && (
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
          )}
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

        {/* Unplaced cameras/equipment drawers — empilés verticalement */}
        {selectedPlan && (unplaced.length > 0 || unplacedEquipment.length > 0) && (
          <div className="absolute bottom-2 left-2 z-10 flex flex-col gap-2 pointer-events-none">
            {unplaced.length > 0 && (
              <div className="bg-card/95 border border-border px-3 py-2 text-xs pointer-events-auto max-w-md" data-testid="map-unplaced">
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

            {/* v3.55 · Équipements réseau du site pas encore placés sur ce plan */}
            {unplacedEquipment.length > 0 && (
              <div className="bg-card/95 border border-border px-3 py-2 text-xs pointer-events-auto max-w-md" data-testid="map-unplaced-equipment">
                <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1 flex items-center gap-1">
                  <BoxIcon size={11} /> Équipements à placer ({unplacedEquipment.length})
                </div>
                <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                  {unplacedEquipment.slice(0, 20).map((eq) => {
                    const Icon = TYPE_ICON[eq.type] || BoxIcon;
                    return (
                      <button key={eq.id} onClick={() => placeEquipmentOnPlan(eq.id)}
                        className="border border-border px-2 py-0.5 hover:bg-secondary/50 hover:border-[#0044FF] text-[11px] flex items-center gap-1"
                        data-testid={`map-place-eq-${eq.id}`}>
                        <Icon size={11} />
                        {eq.name}
                      </button>
                    );
                  })}
                  {unplacedEquipment.length > 20 && <span className="text-muted-foreground">+{unplacedEquipment.length - 20}</span>}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Canvas — carte live (Leaflet) ou plan image/PDF (Konva) */}
        {isLiveMap ? (
          <LiveMapCanvas
            plan={selectedPlan}
            cameras={camerasOnPlan}
            selectedCamId={selectedCamId}
            equipment={equipment}
            selectedEqId={selectedEqId}
            links={links}
            linkingFrom={linkingFrom}
            layers={layers}
            auditMode={auditMode}
            auditIndex={auditIndex}
            onSelectCamera={onSelectCamera}
            onSelectEquipment={onSelectEquipment}
            onCameraDragEnd={onLiveMapCamDragEnd}
            onEquipmentDragEnd={onLiveMapEqDragEnd}
            onCenterChange={setLiveMapCenter}
            onDblClickCamera={(id) => navigate(`/cameras?focus=${id}`)}
            onContextMenuCamera={(id, evt) => setContextMenu({ x: evt.clientX, y: evt.clientY, items: cameraMenuItems(id) })}
            onContextMenuEquipment={(eq, evt) => setContextMenu({ x: evt.clientX, y: evt.clientY, items: equipmentMenuItems(eq) })}
            onContextMenuLink={(link, evt) => setContextMenu({ x: evt.clientX, y: evt.clientY, items: linkMenuItems(link) })}
            onContextMenuEmpty={(placement, evt) => setContextMenu({ x: evt.clientX, y: evt.clientY, items: [buildEquipmentSubmenu(placement)] })}
          />
        ) : (
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
            onContextMenu={(e) => {
              e.evt.preventDefault();
              if (e.target !== e.target.getStage()) return; // géré par le nœud lui-même
              if (!selectedPlan) return;
              const stage = e.target.getStage();
              const p = stage.getPointerPosition();
              const placement = { x: (p.x - stage.x()) / stage.scaleX(), y: (p.y - stage.y()) / stage.scaleY() };
              setContextMenu({ x: e.evt.clientX, y: e.evt.clientY, items: [buildEquipmentSubmenu(placement)] });
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
              {selectedPlan && camerasOnPlan.length === 0 && equipment.length === 0 && (
                <Text text="Aucune caméra sur ce plan. Cliquez sur une caméra dans la liste (en bas) pour la placer, ou clic-droit pour ajouter un équipement."
                  x={40} y={planSize.h / 2} fontSize={13} fill="#a1a1aa" width={planSize.w - 80} align="center" />
              )}
              {links.map((link) => (
                <LinkLine key={link.id} link={link}
                  from={resolveEndpointPos(link.from_kind, link.from_id)}
                  to={resolveEndpointPos(link.to_kind, link.to_id)}
                  onContextMenu={(id, evt) => setContextMenu({ x: evt.clientX, y: evt.clientY, items: linkMenuItems(link) })}
                />
              ))}
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
                  onSelect={(id, evt) => onSelectCamera(id, evt)}
                  onDblClick={(id) => navigate(`/cameras?focus=${id}`)}
                  onContextMenu={(id, evt) => setContextMenu({ x: evt.clientX, y: evt.clientY, items: cameraMenuItems(id) })}
                />
              ))}
              {equipment.map((eq) => (
                <EquipmentNode
                  key={eq.id}
                  eq={eq}
                  selected={selectedEqId === eq.id}
                  showName={layers?.name !== false}
                  showStatus={layers?.status !== false}
                  onDrag={onEqDrag}
                  onDragEnd={onEqDragEnd}
                  onSelect={(id, evt) => onSelectEquipment(id, evt)}
                  onContextMenu={(id, evt) => setContextMenu({ x: evt.clientX, y: evt.clientY, items: equipmentMenuItems(eq) })}
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
        )}
      </div>

      {/* v3.55 · Bandeau "Attacher une connexion" */}
      {linkingFrom && (
        <div className="absolute top-14 left-1/2 -translate-x-1/2 z-20 bg-card border border-[#0044FF] px-3 py-1.5 text-xs flex items-center gap-2">
          <Link2 size={13} className="text-[#0044FF]" />
          Cliquez sur l'élément à relier — <button className="underline" onClick={() => setLinkingFrom(null)}>Annuler (Échap)</button>
        </div>
      )}

      {/* v3.55 · Menu contextuel clic-droit (Konva + Leaflet) */}
      {contextMenu && (
        <MapContextMenu x={contextMenu.x} y={contextMenu.y} items={contextMenu.items} onClose={() => setContextMenu(null)} />
      )}

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
