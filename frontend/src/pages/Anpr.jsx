import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Search, Download, ScanLine, Upload, Loader2, Plus, Trash2, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";

function Plate({ value, status }) {
  const c = status === "black" ? "#FF3333" : status === "white" ? "#00E676" : null;
  return (
    <span className="inline-flex items-center mono font-semibold text-sm tracking-wider px-2 py-0.5 border-2 bg-white text-black" style={{ borderColor: c || "#1a1a1a" }} data-testid="plate-badge">
      <span className="text-[7px] bg-[#0044FF] text-white px-0.5 mr-1 leading-none py-1">F</span>{value}
    </span>
  );
}

export default function Anpr() {
  const { t, can } = useApp();
  const [plates, setPlates] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [watch, setWatch] = useState([]);
  const [wlOpen, setWlOpen] = useState(false);
  const [wlForm, setWlForm] = useState({ plate: "", list_type: "black", reason: "" });
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState(null);
  const [file, setFile] = useState(null);

  const load = async (reset = true) => {
    const offset = reset ? 0 : plates.length;
    const r = await api.get(`/plates?plate=${encodeURIComponent(q)}&limit=50&offset=${offset}`);
    setTotal(parseInt(r.headers["x-total-count"] || "0", 10));
    setPlates((prev) => (reset ? r.data : [...prev, ...r.data]));
  };
  const loadWatch = () => api.get("/watchlist").then((r) => setWatch(r.data));
  useEffect(() => { load(true); loadWatch(); }, []);

  const exportCsv = async () => {
    const token = localStorage.getItem("mg_token");
    const res = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/plates/export`, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await res.blob(); const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "anpr_export.csv"; a.click();
    toast.success("Export CSV téléchargé");
  };

  const addWatch = async () => {
    if (!wlForm.plate) return toast.error("Plaque requise");
    try { await api.post("/watchlist", wlForm); toast.success("Ajouté à la liste"); setWlOpen(false); setWlForm({ plate: "", list_type: "black", reason: "" }); loadWatch(); load(true); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const delWatch = async (id) => { await api.delete(`/watchlist/${id}`); loadWatch(); load(true); };

  const analyze = async () => {
    if (!file) return toast.error("Sélectionnez une image");
    setAiLoading(true); setAiResult(null);
    try {
      const fd = new FormData(); fd.append("file", file);
      const { data } = await api.post("/ai/analyze-plate", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setAiResult(data); toast.success("Analyse IA terminée"); load(true);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setAiLoading(false); }
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <h1 className="font-head font-bold text-2xl tracking-tight">{t("anpr.title")}</h1>
        {can("client") && <button onClick={() => { setAiOpen(true); setAiResult(null); setFile(null); }} data-testid="ai-analyze-btn" className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]"><ScanLine size={16} /> {t("anpr.analyze")}</button>}
      </div>

      <Tabs defaultValue="plates">
        <TabsList className="rounded-none bg-card border border-border">
          <TabsTrigger value="plates" className="rounded-none" data-testid="tab-plates">{t("anpr.plate")}s</TabsTrigger>
          <TabsTrigger value="watch" className="rounded-none" data-testid="tab-watchlist">{t("anpr.watchlist")}</TabsTrigger>
        </TabsList>

        <TabsContent value="plates" className="mt-3">
          <div className="flex gap-2 mb-3">
            <div className="flex-1 relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load(true)} data-testid="plate-search-input"
                placeholder={`${t("common.search")} ${t("anpr.plate").toLowerCase()}...`} className="w-full pl-9 pr-3 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF] mono uppercase" />
            </div>
            <button onClick={() => load(true)} data-testid="plate-search-btn" className="px-4 py-2 bg-[#0044FF] text-white text-sm">{t("common.search")}</button>
            <button onClick={exportCsv} data-testid="export-csv-btn" className="flex items-center gap-2 px-4 py-2 border border-border text-sm hover:bg-secondary"><Download size={15} /> {t("common.export")}</button>
          </div>
          <div className="border border-border bg-card overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-2">{t("anpr.plate")}</th><th className="px-3 py-2">{t("common.date")}</th><th className="px-3 py-2">{t("veh.make")}</th>
                <th className="px-3 py-2">{t("veh.color")}</th><th className="px-3 py-2">{t("common.camera")}</th><th className="px-3 py-2">{t("anpr.direction")}</th><th className="px-3 py-2">{t("common.confidence")}</th>
              </tr></thead>
              <tbody>
                {plates.map((p) => (
                  <tr key={p.id} className="border-b border-border hover:bg-secondary/50" data-testid="plate-row">
                    <td className="px-3 py-2"><Plate value={p.plate} status={p.list_status} /></td>
                    <td className="px-3 py-2 mono text-xs text-muted-foreground">{new Date(p.timestamp).toLocaleString()}</td>
                    <td className="px-3 py-2">{p.vehicle_make} {p.vehicle_model}</td>
                    <td className="px-3 py-2">{p.vehicle_color}</td>
                    <td className="px-3 py-2 text-muted-foreground text-xs">{p.camera_name}</td>
                    <td className="px-3 py-2 text-xs">{p.direction}</td>
                    <td className="px-3 py-2 mono text-xs" style={{ color: p.confidence > 0.9 ? "#00E676" : "#FFB800" }}>{(p.confidence * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between mt-2">
            <span className="text-xs text-muted-foreground mono" data-testid="plates-count">{plates.length} / {total}</span>
            {plates.length < total && (
              <button onClick={() => load(false)} data-testid="load-more-plates" className="px-4 py-2 border border-border text-sm hover:bg-secondary">{t("common.load_more")}</button>
            )}
          </div>
        </TabsContent>

        <TabsContent value="watch" className="mt-3">
          {can("technician") && <button onClick={() => setWlOpen(true)} data-testid="add-watch-btn" className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm mb-3"><Plus size={16} /> {t("common.add")}</button>}
          <div className="border border-border bg-card divide-y divide-border">
            {watch.map((w) => (
              <div key={w.id} className="flex items-center gap-3 px-3 py-2.5" data-testid="watch-row">
                {w.list_type === "black" ? <ShieldAlert size={16} className="mg-offline" /> : <ShieldCheck size={16} className="mg-online" />}
                <Plate value={w.plate} status={w.list_type} />
                <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 border" style={{ borderColor: w.list_type === "black" ? "#FF3333" : "#00E676", color: w.list_type === "black" ? "#FF3333" : "#00E676" }}>{w.list_type === "black" ? t("anpr.blacklist") : t("anpr.whitelist")}</span>
                <span className="text-sm text-muted-foreground flex-1">{w.reason}</span>
                {can("technician") && <button onClick={() => delWatch(w.id)} className="p-1.5 hover:bg-secondary text-[#FF3333]"><Trash2 size={15} /></button>}
              </div>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      {/* Watchlist dialog */}
      <Dialog open={wlOpen} onOpenChange={setWlOpen}>
        <DialogContent className="rounded-none border-border">
          <DialogHeader><DialogTitle className="font-head">{t("anpr.watchlist")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("anpr.plate")}</label><input data-testid="watch-plate" value={wlForm.plate} onChange={(e) => setWlForm({ ...wlForm, plate: e.target.value.toUpperCase() })} className="w-full px-3 py-2 bg-card border border-input outline-none mono uppercase" /></div>
            <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("common.type")}</label><select value={wlForm.list_type} onChange={(e) => setWlForm({ ...wlForm, list_type: e.target.value })} className="w-full px-3 py-2 bg-card border border-input outline-none"><option value="black">{t("anpr.blacklist")}</option><option value="white">{t("anpr.whitelist")}</option></select></div>
            <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("anpr.reason")}</label><input value={wlForm.reason} onChange={(e) => setWlForm({ ...wlForm, reason: e.target.value })} className="w-full px-3 py-2 bg-card border border-input outline-none" /></div>
          </div>
          <DialogFooter>
            <button onClick={() => setWlOpen(false)} className="px-4 py-2 border border-border text-sm">{t("common.cancel")}</button>
            <button onClick={addWatch} data-testid="watch-submit" className="px-4 py-2 bg-[#0044FF] text-white text-sm">{t("common.save")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* AI analyze dialog */}
      <Dialog open={aiOpen} onOpenChange={setAiOpen}>
        <DialogContent className="rounded-none border-border max-w-lg">
          <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><ScanLine size={18} /> {t("anpr.analyze")}</DialogTitle></DialogHeader>
          <label className="block border-2 border-dashed border-border p-6 text-center cursor-pointer hover:border-[#0044FF] transition-colors">
            <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" data-testid="ai-file-input" onChange={(e) => setFile(e.target.files[0])} />
            <Upload size={28} className="mx-auto text-muted-foreground mb-2" />
            <div className="text-sm">{file ? file.name : t("anpr.upload")}</div>
            <div className="text-[10px] text-muted-foreground mt-1">PNG / JPEG / WEBP</div>
          </label>
          {file && <img src={URL.createObjectURL(file)} alt="" className="max-h-48 w-full object-contain bg-black" />}
          {aiResult && (
            <div className="border border-border p-3 text-sm space-y-1 mono" data-testid="ai-result">
              <div className="flex justify-between"><span className="text-muted-foreground">PLATE</span><Plate value={aiResult.plate || "—"} status="none" /></div>
              <div className="flex justify-between"><span className="text-muted-foreground">VEHICLE</span><span>{aiResult.vehicle_make} {aiResult.vehicle_model}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">COLOR</span><span>{aiResult.vehicle_color}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">TYPE</span><span>{aiResult.vehicle_type}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">CONFIDENCE</span><span style={{ color: "#00E676" }}>{((aiResult.confidence || 0) * 100).toFixed(0)}%</span></div>
            </div>
          )}
          <DialogFooter>
            <button onClick={() => setAiOpen(false)} className="px-4 py-2 border border-border text-sm">{t("common.close")}</button>
            <button onClick={analyze} disabled={aiLoading} data-testid="ai-run-btn" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{aiLoading && <Loader2 size={15} className="animate-spin" />} {t("anpr.analyze")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
