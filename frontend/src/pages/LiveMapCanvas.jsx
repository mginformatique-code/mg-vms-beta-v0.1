// v3.54 · Fond de carte interactif ("carte_live") pour MapCenter.jsx —
// alternative au canvas Konva (image statique) pour les plans qui n'en
// sont pas un : une vraie carte navigable (OpenStreetMap / imagerie
// satellite Esri, toutes deux gratuites, sans clé API). Caméras
// positionnées en coordonnées réelles (lat/lng) au lieu de pixels ;
// mêmes champs rotation/angle_h/range_m que le mode pixel pour le cône
// FOV, recalculé en géométrie réelle (voir lib/mapCenterHelpers.js).
import React, { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, Marker, Polygon, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  STATUS_COLOR, COVERAGE_COLOR, coverageQuality, detectCameraRoles,
  ROLE_LABELS, ROLE_COLORS, fovPolygon,
} from "@/lib/mapCenterHelpers";

const TILE_LAYERS = {
  street: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "&copy; OpenStreetMap contributors",
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri &mdash; Esri, Maxar, Earthstar Geographics",
  },
};

function cameraDivIcon(cam, { selected, hasAuditIssue, layers }) {
  const pos = cam.map_position || {};
  const rot = pos.rotation || 0;
  const status = cam.status || "offline";
  const dotColor = STATUS_COLOR[status] || "#71717a";
  const covColor = COVERAGE_COLOR[coverageQuality(pos)];
  const roles = detectCameraRoles(cam);
  const showName = layers?.name !== false;
  const showBadges = layers?.badges !== false;
  const showStatus = layers?.status !== false;

  const badgesHtml = showBadges && roles.length
    ? `<div style="display:flex;gap:2px;margin-top:2px;justify-content:center">${roles.map((r) =>
        `<span style="background:${ROLE_COLORS[r]};color:#fff;font-size:8px;font-weight:bold;padding:1px 3px;border-radius:2px">${ROLE_LABELS[r]}</span>`
      ).join("")}</div>`
    : "";

  return L.divIcon({
    className: "mgvms-cam-marker",
    html: `
      <div style="position:relative;width:32px;height:32px;display:flex;align-items:center;justify-content:center">
        <div style="position:absolute;width:22px;height:22px;border-radius:50%;background:#0d1117;
                    border:2px solid ${covColor};transform:rotate(${rot}deg)">
          <div style="position:absolute;top:-6px;left:50%;transform:translateX(-50%);width:4px;height:6px;background:${covColor}"></div>
        </div>
        ${showStatus ? `<div style="position:absolute;top:2px;right:2px;width:6px;height:6px;border-radius:50%;background:${dotColor};border:1px solid #0d1117"></div>` : ""}
        ${hasAuditIssue ? `<div style="position:absolute;inset:-3px;border-radius:50%;border:2px dashed #FFB800;opacity:0.9"></div>` : ""}
        ${selected ? `<div style="position:absolute;inset:-5px;border-radius:50%;border:2px dashed #00E676"></div>` : ""}
      </div>
      ${showName ? `<div style="text-align:center;font-size:11px;color:#e6e6e6;text-shadow:0 1px 2px #000;white-space:nowrap;margin-top:1px">${(cam.name || cam.id?.slice(0, 6) || "")}</div>` : ""}
      ${badgesHtml}
    `,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

// v3.54 · Écoute les déplacements de la carte pour connaître son centre
// courant (utilisé par MapCenter.jsx pour placer une nouvelle caméra au
// centre de la vue actuelle, comme le fait déjà le mode pixel avec le
// centre du plan) — doit être un enfant de <MapContainer>, useMapEvents
// n'est utilisable que dans ce contexte.
function CenterWatcher({ onCenterChange }) {
  const map = useMapEvents({
    moveend: () => {
      const c = map.getCenter();
      onCenterChange && onCenterChange({ lat: c.lat, lng: c.lng });
    },
  });
  useEffect(() => {
    const c = map.getCenter();
    onCenterChange && onCenterChange({ lat: c.lat, lng: c.lng });
  }, [map, onCenterChange]);
  return null;
}

// Recentre la carte si le plan sélectionné change (nouveau centre initial).
function RecenterOnPlanChange({ center, zoom }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.setView(center, zoom || map.getZoom());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center?.[0], center?.[1]]);
  return null;
}

export default function LiveMapCanvas({
  plan, cameras, selectedCamId, layers, auditMode, auditIndex,
  onSelectCamera, onCameraDragEnd, onCenterChange, onDblClickCamera,
}) {
  const [tileKind, setTileKind] = useState("satellite");
  const initialCenter = useMemo(
    () => [plan.center_lat ?? 46.6, plan.center_lng ?? 1.9],
    [plan.id] // eslint-disable-line react-hooks/exhaustive-deps
  );
  const initialZoom = plan.zoom || (plan.center_lat != null ? 18 : 5);

  return (
    <div className="relative w-full h-full">
      <MapContainer
        center={initialCenter}
        zoom={initialZoom}
        className="w-full h-full"
        // v3.54 · z-index EXPLICITE (pas juste `position:relative`) —
        // sans lui, .leaflet-container ne crée pas de nouveau contexte
        // d'empilement CSS, et les panneaux internes de Leaflet (tuiles,
        // marqueurs, contrôles de zoom, jusqu'à z-index:1000) s'échappent
        // par-dessus la barre d'outils du parent (z-10) — bug constaté en
        // test réel : barre d'outils invisible, présente dans le DOM mais
        // peinte sous la carte.
        style={{ background: "#0b0b0f", zIndex: 0 }}
        data-testid="live-map-canvas"
      >
        <TileLayer key={tileKind} url={TILE_LAYERS[tileKind].url} attribution={TILE_LAYERS[tileKind].attribution} maxZoom={19} />
        <RecenterOnPlanChange center={initialCenter} zoom={initialZoom} />
        <CenterWatcher onCenterChange={onCenterChange} />

        {cameras.map((cam) => {
          const pos = cam.map_position || {};
          if (pos.lat == null || pos.lng == null) return null;
          const hasAuditIssue = auditMode && (auditIndex[cam.id] || []).length > 0;
          const showFov = layers?.fov !== false;
          const covColor = COVERAGE_COLOR[coverageQuality(pos)];
          return (
            <React.Fragment key={cam.id}>
              {showFov && (
                <Polygon
                  positions={fovPolygon(pos.lat, pos.lng, pos)}
                  pathOptions={{
                    color: covColor, weight: selectedCamId === cam.id ? 1.5 : 0.5,
                    fillColor: covColor, fillOpacity: selectedCamId === cam.id ? 0.32 : 0.2,
                  }}
                />
              )}
              <Marker
                position={[pos.lat, pos.lng]}
                draggable
                icon={cameraDivIcon(cam, { selected: selectedCamId === cam.id, hasAuditIssue, layers })}
                eventHandlers={{
                  dragend: (e) => {
                    const { lat, lng } = e.target.getLatLng();
                    onCameraDragEnd(cam.id, { lat, lng });
                  },
                  click: () => onSelectCamera(cam.id),
                  dblclick: () => onDblClickCamera && onDblClickCamera(cam.id),
                }}
              />
            </React.Fragment>
          );
        })}
      </MapContainer>

      {/* Bascule fond de carte — Rues / Satellite */}
      <div className="absolute bottom-2 right-2 z-[1000] bg-card/90 backdrop-blur border border-border p-1 flex items-center gap-1 text-[11px]">
        {[["street", "Rues"], ["satellite", "Satellite"]].map(([k, label]) => (
          <button key={k} onClick={() => setTileKind(k)}
            className={`px-2 py-1 ${tileKind === k ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}
            data-testid={`live-map-tiles-${k}`}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
