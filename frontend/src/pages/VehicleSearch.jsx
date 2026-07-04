import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Search, RotateCcw, Car } from "lucide-react";

const COLORS = ["Blanc", "Noir", "Gris", "Bleu", "Rouge", "Vert", "Jaune", "Orange", "Violet", "Rose", "Marron", "Beige", "Argent"];
const MAKES = ["Renault", "Peugeot", "Citroën", "Volkswagen", "BMW", "Mercedes", "Toyota", "Audi"];
const VTYPES = ["Voiture", "Camion", "Moto", "Bus", "Utilitaire"];
const DIRS = ["Nord", "Sud", "Est", "Ouest", "Entrée", "Sortie"];

export default function VehicleSearch() {
  const { t } = useApp();
  const [sites, setSites] = useState([]);
  const [results, setResults] = useState([]);
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
          <div key={p.id} className="bg-card border border-border overflow-hidden hover:border-[#0044FF] transition-colors" data-testid="veh-result-card">
            <div className="relative h-32 bg-black">
              <img src={p.vehicle_crop} alt="" className="w-full h-full object-cover opacity-90" onError={(e) => { e.target.style.display = "none"; }} />
              {p.list_status !== "none" && <span className="absolute top-1 right-1 text-[9px] uppercase px-1.5 py-0.5 text-white" style={{ background: p.list_status === "black" ? "#FF3333" : "#00E676" }}>{p.list_status}</span>}
            </div>
            <div className="p-3">
              <div className="mono font-semibold text-sm tracking-wider px-2 py-0.5 border-2 border-black bg-white text-black inline-flex items-center mb-2"><span className="text-[7px] bg-[#0044FF] text-white px-0.5 mr-1 py-1">F</span>{p.plate}</div>
              <div className="text-sm font-medium flex items-center gap-1"><Car size={13} className="text-muted-foreground" /> {p.vehicle_make} {p.vehicle_model}</div>
              <div className="text-xs text-muted-foreground mt-1">{p.vehicle_color} · {p.vehicle_type} · {p.direction}</div>
              <div className="text-[10px] mono text-muted-foreground mt-2 pt-2 border-t border-border">{p.camera_name} · {new Date(p.timestamp).toLocaleString()}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
