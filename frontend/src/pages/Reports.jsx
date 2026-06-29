import React, { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { FileText, FileSpreadsheet, FileType2, Download, Loader2, Calendar } from "lucide-react";
import { toast } from "sonner";

const FORMATS = [
  { key: "csv", label: "CSV", icon: FileText },
  { key: "xlsx", label: "Excel", icon: FileSpreadsheet },
  { key: "pdf", label: "PDF", icon: FileType2 },
];

export default function Reports() {
  const { t, can } = useApp();
  const [types, setTypes] = useState([]);
  const [sites, setSites] = useState([]);
  const [type, setType] = useState("");
  const [format, setFormat] = useState("csv");
  const [siteId, setSiteId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/reports/types").then((r) => { setTypes(r.data); if (r.data[0]) setType(r.data[0].key); }).catch(() => {});
    api.get("/sites").then((r) => setSites(r.data)).catch(() => {});
  }, []);

  const cur = types.find((x) => x.key === type);

  if (!can("technician")) return <Navigate to="/" replace />;

  const generate = async () => {
    if (!type) return;
    setBusy(true);
    try {
      const params = { format };
      if (siteId) params.site_id = siteId;
      if (cur?.date_filter && from) params.date_from = from;
      if (cur?.date_filter && to) params.date_to = to;
      const r = await api.get(`/reports/${type}`, { params, responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url; a.download = `mgvms_${type}.${format}`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(`Rapport ${format.toUpperCase()} généré`);
    } catch (e) { toast.error("Échec de la génération"); } finally { setBusy(false); }
  };

  return (
    <div className="p-4 md:p-6 max-w-3xl" data-testid="reports-page">
      <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
        <FileText size={22} className="text-[#0044FF]" /> {t("rep.title")}
      </h1>
      <p className="text-sm text-muted-foreground mt-0.5 mb-5">{t("rep.subtitle")}</p>

      <div className="border border-border bg-card p-5 space-y-5">
        {/* Type */}
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("rep.type")}</label>
          <div className="grid sm:grid-cols-2 gap-2">
            {types.map((x) => (
              <button key={x.key} onClick={() => setType(x.key)} data-testid={`rep-type-${x.key}`}
                className={`text-left px-3 py-2.5 border text-sm transition-colors ${type === x.key ? "border-[#0044FF] bg-secondary" : "border-border hover:bg-secondary"}`}>
                {x.label}
              </button>
            ))}
          </div>
        </div>

        {/* Format */}
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-2">{t("rep.format")}</label>
          <div className="flex gap-2">
            {FORMATS.map((f) => (
              <button key={f.key} onClick={() => setFormat(f.key)} data-testid={`rep-format-${f.key}`}
                className={`flex items-center gap-2 px-4 py-2 border text-sm transition-colors ${format === f.key ? "border-[#0044FF] bg-secondary" : "border-border hover:bg-secondary"}`}>
                <f.icon size={16} /> {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* Site + dates */}
        <div className="grid sm:grid-cols-3 gap-3">
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("rep.site")}</label>
            <select value={siteId} onChange={(e) => setSiteId(e.target.value)} data-testid="rep-site"
              className="w-full px-3 py-2 bg-card border border-input text-sm outline-none">
              <option value="">{t("rep.all_sites")}</option>
              {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          {cur?.date_filter && (
            <>
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("rep.from")}</label>
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} data-testid="rep-from"
                  className="w-full px-3 py-2 bg-card border border-input text-sm outline-none" />
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("rep.to")}</label>
                <input type="date" value={to} onChange={(e) => setTo(e.target.value)} data-testid="rep-to"
                  className="w-full px-3 py-2 bg-card border border-input text-sm outline-none" />
              </div>
            </>
          )}
        </div>

        <div className="flex items-center justify-between pt-2 border-t border-border">
          <span className="text-[11px] text-muted-foreground">{t("rep.hint")}</span>
          <button onClick={generate} disabled={busy || !type} data-testid="rep-generate-btn"
            className="flex items-center gap-2 px-4 py-2.5 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc] disabled:opacity-60">
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />} {t(busy ? "rep.generating" : "rep.generate")}
          </button>
        </div>
      </div>
    </div>
  );
}
