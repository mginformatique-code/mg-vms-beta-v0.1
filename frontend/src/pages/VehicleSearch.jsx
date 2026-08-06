import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Search, RotateCcw, Car, X, ScanLine, Layers } from "lucide-react";

const COLORS = ["Blanc", "Noir", "Gris", "Bleu", "Rouge", "Vert", "Jaune", "Orange", "Violet", "Rose", "Marron", "Beige", "Argent"];
const MAKES = ["Renault", "Peugeot", "Citroën", "Volkswagen", "BMW", "Mercedes", "Toyota", "Audi"];
const VTYPES = ["Voiture", "Camion", "Moto", "Bus", "Utilitaire"];
const DIRS = ["Nord", "Sud", "Est", "Ouest", "Entrée", "Sortie"];

// v0.5.1.c · Couleurs des badges plugins pour distinguer visuellement les
// moteurs (core vs cloud vs on-prem).
const PLUGIN_COLORS = {
  "yolov11":        "#0044FF",
  "bytetrack":      "#0044FF",
  "fast-alpr":      "#00E676",
  "google-vision":  "#FFB800",
  "azure-vision":   "#00A2FF",
  "openalpr":       "#A855F7",
  "plate-recognizer": "#EC4899",
  "codeproject-ai": "#84CC16",
  "anpr-eps":       "#F97316",
};
const _colorFor = (name) => PLUGIN_COLORS[name] || "#71717a";

function PluginBadge({ name }) {
  const c = _colorFor(name);
  return (
    <span
      className="text-[9px] mono uppercase tracking-wider px-1.5 py-0.5 border"
      style={{ color: c, borderColor: c }}
      data-testid={`veh-plugin-badge-${name}`}
    >
      {name}
    </span>
  );
}

function DetailModal({ item, onClose }) {
  if (!item) return null;
  const readings = item.anpr_readings || [];
  const plugins = item.plugins_used || [];
  return (
    <div
      className="fixed inset-0 bg-black/70 z-[80] flex items-center justify-center p-4"
      onClick={onClose}
      data-testid="veh-detail-modal"
    >
      <div
        className="bg-card border border-border max-w-5xl w-full max-h-[92vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-1">
              {item.camera_name}
            </div>
            <div className="mono font-bold text-2xl tracking-wider">{item.plate}</div>
          </div>
          <button onClick={onClose} className="hover:text-[#FF3333]" data-testid="veh-detail-close">
            <X size={20} />
          </button>
        </div>

        <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Frame plein cadre */}
          <div>
            <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2">
              Scène complète
            </div>
            <div className="bg-black border border-border h-96 flex items-center justify-center overflow-hidden">
              {item.frame_thumb ? (
                <img
                  src={item.frame_thumb}
                  alt="scène"
                  className="max-h-full max-w-full object-contain"
                  data-testid="veh-detail-frame"
                />
              ) : (
                <span className="text-muted-foreground text-xs">Frame indisponible</span>
              )}
            </div>
          </div>

          {/* Crops : véhicule + plaque */}
          <div className="space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
                <Car size={12} /> Véhicule (YOLO)
              </div>
              <div className="bg-black border border-border h-40 flex items-center justify-center overflow-hidden">
                {item.vehicle_crop ? (
                  <img
                    src={item.vehicle_crop}
                    alt="véhicule"
                    className="max-h-full max-w-full object-contain"
                    data-testid="veh-detail-vehicle-crop"
                  />
                ) : (
                  <span className="text-muted-foreground text-xs">Crop véhicule indisponible</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
                <ScanLine size={12} /> Crop OCR (plaque)
              </div>
              <div className="bg-black border border-border h-24 flex items-center justify-center overflow-hidden">
                {item.plate_crop ? (
                  <img
                    src={item.plate_crop}
                    alt="plaque"
                    className="max-h-full max-w-full object-contain"
                    data-testid="veh-detail-plate-crop"
                  />
                ) : (
                  <span className="text-muted-foreground text-xs">Crop OCR indisponible</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Multi-plugins + lectures */}
        <div className="p-4 border-t border-border space-y-3">
          {plugins.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
                <Layers size={12} /> Plugins utilisés ({plugins.length})
              </div>
              <div className="flex flex-wrap gap-1" data-testid="veh-detail-plugins">
                {plugins.map((p) => <PluginBadge key={p} name={p} />)}
              </div>
            </div>
          )}
          {readings.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-2 flex items-center gap-1">
                <ScanLine size={12} /> Lectures multi-moteurs ({readings.length})
              </div>
              <table className="w-full text-sm" data-testid="veh-detail-readings">
                <thead className="text-left text-muted-foreground text-xs">
                  <tr>
                    <th className="py-1">Moteur</th>
                    <th className="py-1">Plaque lue</th>
                    <th className="py-1 text-right">Confiance</th>
                  </tr>
                </thead>
                <tbody>
                  {readings.map((r, i) => (
                    <tr key={i} className="border-t border-border/40">
                      <td className="py-1.5"><PluginBadge name={r.engine} /></td>
                      <td className="py-1.5 mono font-medium">{r.plate || "—"}</td>
                      <td className="py-1.5 mono text-right">{Math.round((r.confidence || 0) * 100)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-border grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div><span className="text-muted-foreground">Site : </span>{item.site_name}</div>
          <div><span className="text-muted-foreground">Type : </span>{item.vehicle_type || "—"}</div>
          <div><span className="text-muted-foreground">Couleur : </span>{item.vehicle_color || "—"}</div>
          <div><span className="text-muted-foreground">Date : </span>{new Date(item.timestamp).toLocaleString()}</div>
        </div>
      </div>
    </div>
  );
}

export default function VehicleSearch() {
  const { t } = useApp();
  const [sites, setSites] = useState([]);
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [f, setF] = useState({ plate: "", color: "", make: "", vtype: "", site_id: "", direction: "", date_from: "", date_to: "" });

  useEffect(() => { api.get("/sites").then((r) => setSites(r.data)); }, []);
  useEffect(() => { const id = setTimeout(search, 300); return () => clearTimeout(id); }, [f]); // recherche auto à chaque filtre

  const search = () => {
    const params = new URLSearchParams();
    Object.entries(f).forEach(([k, v]) => { if (v) params.append(k, v); });
    api.get(`/plates?${params.toString()}`).then((r) => setResults(r.data));
  };
  const reset = () => { setF({ plate: "", color: "", make: "", vtype: "", site_id: "", direction: "", date_from: "", date_to: "" }); api.get("/plates").then((r) => setResults(r.data)); };

  const sel = "w-full px-2.5 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]";

  return (
    <div className="p-4">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-4">{t("veh.title")}</h1>
      <div className="bg-card border border-border p-4 mb-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
          <input placeholder={t("anpr.plate")} value={f.plate} onChange={(e) => setF({ ...f, plate: e.target.value.toUpperCase() })} data-testid="veh-plate" className={`${sel} mono uppercase`} />
          <select value={f.color} onChange={(e) => setF({ ...f, color: e.target.value })} data-testid="veh-color" className={sel}><option value="">{t("veh.color")} — {t("common.all")}</option>{COLORS.map((c) => <option key={c}>{c}</option>)}</select>
          <select value={f.make} onChange={(e) => setF({ ...f, make: e.target.value })} data-testid="veh-make" className={sel}><option value="">{t("veh.make")} — {t("common.all")}</option>{MAKES.map((c) => <option key={c}>{c}</option>)}</select>
          <select value={f.vtype} onChange={(e) => setF({ ...f, vtype: e.target.value })} className={sel}><option value="">{t("common.type")} — {t("common.all")}</option>{VTYPES.map((c) => <option key={c}>{c}</option>)}</select>
          <select value={f.site_id} onChange={(e) => setF({ ...f, site_id: e.target.value })} className={sel}><option value="">{t("common.site")} — {t("common.all")}</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          <select value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })} className={sel}><option value="">{t("anpr.direction")} — {t("common.all")}</option>{DIRS.map((c) => <option key={c}>{c}</option>)}</select>
          <input type="datetime-local" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} className={sel} />
          <input type="datetime-local" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} className={sel} />
        </div>
        <div className="flex gap-2">
          <button onClick={search} data-testid="veh-search-btn" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm"><Search size={15} /> {t("common.search")}</button>
          <button onClick={reset} className="flex items-center gap-2 px-4 py-2 border border-border text-sm hover:bg-secondary"><RotateCcw size={15} /> {t("common.reset")}</button>
          <span className="ml-auto text-sm text-muted-foreground self-center mono">{results.length} {t("veh.results")}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
        {results.map((p) => (
          <button
            key={p.id}
            onClick={() => setSelected(p)}
            className="bg-card border border-border overflow-hidden hover:border-[#0044FF] transition-colors text-left"
            data-testid="veh-result-card"
          >
            <div className="relative h-32 bg-black">
              <img src={p.vehicle_crop} alt="" className="w-full h-full object-cover opacity-90" onError={(e) => { e.target.style.display = "none"; }} />
              {p.list_status !== "none" && <span className="absolute top-1 right-1 text-[9px] uppercase px-1.5 py-0.5 text-white" style={{ background: p.list_status === "black" ? "#FF3333" : "#00E676" }}>{p.list_status}</span>}
            </div>
            <div className="p-3">
              <div className="mono font-semibold text-sm tracking-wider px-2 py-0.5 border-2 border-black bg-white text-black inline-flex items-center mb-2"><span className="text-[7px] bg-[#0044FF] text-white px-0.5 mr-1 py-1">F</span>{p.plate}</div>
              <div className="text-sm font-medium flex items-center gap-1"><Car size={13} className="text-muted-foreground" /> {p.vehicle_make} {p.vehicle_model}</div>
              <div className="text-xs text-muted-foreground mt-1">{p.vehicle_color} · {p.vehicle_type} · {p.direction}</div>
              {(p.plugins_used || []).length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2" data-testid="veh-card-plugins">
                  {(p.plugins_used || []).slice(0, 4).map((n) => <PluginBadge key={n} name={n} />)}
                  {(p.plugins_used || []).length > 4 && (
                    <span className="text-[9px] mono text-muted-foreground">+{p.plugins_used.length - 4}</span>
                  )}
                </div>
              )}
              <div className="text-[10px] mono text-muted-foreground mt-2 pt-2 border-t border-border">{p.camera_name} · {new Date(p.timestamp).toLocaleString()}</div>
            </div>
          </button>
        ))}
      </div>

      {selected && <DetailModal item={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
