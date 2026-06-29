import React, { useEffect, useMemo, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import {
  Plus, RefreshCw, Loader2, Trash2, Activity, Network as NetIcon, Router, Server, HardDrive,
  BatteryCharging, Cctv, Box, Wifi, WifiOff, AlertTriangle, MonitorPlay, X,
} from "lucide-react";
import { toast } from "sonner";

const TYPES = ["Switch", "Routeur", "NAS", "UPS", "Serveur", "NVR", "Caméra", "Générique"];
const TYPE_ICON = { Switch: NetIcon, Routeur: Router, NAS: HardDrive, UPS: BatteryCharging, Serveur: Server, NVR: MonitorPlay, Caméra: Cctv, Générique: Box };
const STATUS_COLOR = { online: "#00E676", warning: "#FFB800", offline: "#FF3333" };

const NODE_W = 156, NODE_H = 58, H_GAP = 36, V_GAP = 92;

function statusLabel(t, s) {
  return s === "online" ? t("common.online") : s === "warning" ? t("net.warning") : t("common.offline");
}
function fmtUptime(sec) {
  if (!sec) return "—";
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600);
  return d > 0 ? `${d}j ${h}h` : `${h}h`;
}

function Stat({ label, value, color }) {
  return (
    <div className="px-3 py-2 border border-border bg-card" data-testid={`net-stat-${label}`}>
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-xl font-head font-bold mono" style={{ color }}>{value}</div>
    </div>
  );
}

function Topology({ nodes, edges, onSelect }) {
  const layout = useMemo(() => {
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const depth = {};
    const getDepth = (n, guard = 0) => {
      if (n.id in depth) return depth[n.id];
      const pid = n.parent_id;
      const d = pid && byId[pid] && guard < 20 ? getDepth(byId[pid], guard + 1) + 1 : 0;
      depth[n.id] = d;
      return d;
    };
    nodes.forEach((n) => getDepth(n));
    const levels = {};
    nodes.forEach((n) => { (levels[depth[n.id]] ||= []).push(n); });
    const maxLevelW = Math.max(1, ...Object.values(levels).map((l) => l.length)) * (NODE_W + H_GAP);
    const pos = {};
    Object.entries(levels).forEach(([lvl, arr]) => {
      const levelW = arr.length * (NODE_W + H_GAP);
      const offset = (maxLevelW - levelW) / 2;
      arr.forEach((n, i) => {
        pos[n.id] = { x: offset + i * (NODE_W + H_GAP) + H_GAP / 2, y: Number(lvl) * (NODE_H + V_GAP) + 20 };
      });
    });
    const height = (Math.max(...Object.keys(levels).map(Number)) + 1) * (NODE_H + V_GAP);
    return { pos, width: maxLevelW, height };
  }, [nodes]);

  return (
    <div className="border border-border bg-card overflow-auto" data-testid="net-topology" style={{ maxHeight: "62vh" }}>
      <div className="relative" style={{ width: layout.width + H_GAP, height: layout.height + 20, minWidth: "100%" }}>
        <svg className="absolute inset-0 pointer-events-none" width={layout.width + H_GAP} height={layout.height + 20}>
          {edges.map((e, i) => {
            const p = layout.pos[e.source], c = layout.pos[e.target];
            if (!p || !c) return null;
            return (
              <line key={i} x1={p.x + NODE_W / 2} y1={p.y + NODE_H} x2={c.x + NODE_W / 2} y2={c.y}
                stroke={e.status === "up" ? "#3a3a4a" : "#FF3333"} strokeWidth={e.status === "up" ? 1.5 : 2}
                strokeDasharray={e.status === "up" ? "" : "5 4"} />
            );
          })}
        </svg>
        {nodes.map((n) => {
          const p = layout.pos[n.id];
          if (!p) return null;
          const Icon = TYPE_ICON[n.type] || Box;
          const col = STATUS_COLOR[n.status];
          return (
            <button key={n.id} data-testid={`net-node-${n.id}`} onClick={() => onSelect(n)}
              className="absolute bg-background border-l-4 hover:bg-secondary transition-colors text-left flex items-center gap-2 px-2"
              style={{ left: p.x, top: p.y, width: NODE_W, height: NODE_H, borderLeftColor: col, borderTop: "1px solid hsl(var(--border))", borderRight: "1px solid hsl(var(--border))", borderBottom: "1px solid hsl(var(--border))" }}>
              <Icon size={20} style={{ color: col }} strokeWidth={1.5} className="shrink-0" />
              <div className="min-w-0">
                <div className="text-xs font-medium truncate">{n.name}</div>
                <div className="text-[10px] text-muted-foreground truncate">{n.type} · {n.ip || "—"}</div>
              </div>
              <span className="absolute top-1 right-1 w-2 h-2 rounded-full" style={{ backgroundColor: col }} />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function Network() {
  const { t, can } = useApp();
  const [tab, setTab] = useState("topology");
  const [topo, setTopo] = useState({ nodes: [], edges: [] });
  const [stats, setStats] = useState({ total: 0, online: 0, warning: 0, offline: 0, ups_on_battery: 0 });
  const [sites, setSites] = useState([]);
  const [filterSite, setFilterSite] = useState("");
  const [polling, setPolling] = useState(false);
  const [sheet, setSheet] = useState(null);
  const [pinging, setPinging] = useState(false);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: "", type: "Switch", site_id: "", ip: "", model: "", vendor: "", parent_id: "" });

  const load = () => {
    const params = filterSite ? { site_id: filterSite } : {};
    api.get("/network/topology", { params }).then((r) => setTopo(r.data)).catch(() => {});
    api.get("/network/stats").then((r) => setStats(r.data)).catch(() => {});
  };
  useEffect(() => { api.get("/sites").then((r) => setSites(r.data)).catch(() => {}); }, []);
  useEffect(load, [filterSite]);
  useEffect(() => {
    const i = setInterval(load, 30000);  // reflète le poll serveur périodique
    return () => clearInterval(i);
  }, [filterSite]);

  const poll = async () => {
    setPolling(true);
    try {
      const params = filterSite ? { site_id: filterSite } : {};
      const { data } = await api.post("/network/poll", null, { params });
      toast.success(`${data.polled} équipements sondés · ${data.alerts_raised} alerte(s)`);
      load();
    } catch (e) { toast.error("Échec du sondage"); } finally { setPolling(false); }
  };

  const ping = async (eq) => {
    setPinging(true);
    try {
      const { data } = await api.post(`/network/equipment/${eq.id}/ping`);
      setSheet(data.equipment);
      data.result === "ok" ? toast.success(`${eq.name}: ${data.equipment.latency_ms} ms`) : toast.error(`${eq.name}: timeout`);
      load();
    } catch (e) { toast.error("Échec du ping"); } finally { setPinging(false); }
  };

  const submit = async () => {
    if (!form.name || !form.site_id) return toast.error("Nom et site requis");
    setSaving(true);
    try {
      await api.post("/network/equipment", { ...form, parent_id: form.parent_id || null });
      toast.success("Équipement ajouté"); setOpen(false); load();
      setForm({ name: "", type: "Switch", site_id: "", ip: "", model: "", vendor: "", parent_id: "" });
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  const del = async (eq) => {
    if (!window.confirm(`Supprimer ${eq.name} ?`)) return;
    await api.delete(`/network/equipment/${eq.id}`); toast.success("Supprimé"); setSheet(null); load();
  };

  const nodes = topo.nodes;

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="network-page">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
            <NetIcon size={22} className="text-[#0044FF]" /> {t("net.title")}
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">{t("net.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select value={filterSite} onChange={(e) => setFilterSite(e.target.value)} data-testid="net-site-filter"
            className="px-3 py-2 bg-card border border-input text-sm outline-none">
            <option value="">{t("common.all")} — {t("nav.sites")}</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          {can("technician") && (
            <button onClick={poll} disabled={polling} data-testid="net-poll-btn"
              className="flex items-center gap-2 px-3 py-2 border border-border text-sm hover:bg-secondary">
              {polling ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />} {t(polling ? "net.polling" : "net.poll")}
            </button>
          )}
          {can("technician") && (
            <button onClick={() => setOpen(true)} data-testid="net-add-btn"
              className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]"><Plus size={16} /> {t("net.add")}</button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <Stat label={t("net.stat.total")} value={stats.total} />
        <Stat label={t("net.stat.online")} value={stats.online} color="#00E676" />
        <Stat label={t("net.stat.warning")} value={stats.warning} color="#FFB800" />
        <Stat label={t("net.stat.offline")} value={stats.offline} color="#FF3333" />
        <Stat label={t("net.stat.ups_battery")} value={stats.ups_on_battery} color="#FFB800" />
      </div>

      <div className="flex items-center gap-1 border-b border-border">
        {[["topology", t("net.topology")], ["list", t("net.list")]].map(([k, lbl]) => (
          <button key={k} onClick={() => setTab(k)} data-testid={`net-tab-${k}`}
            className={`px-4 py-2 text-sm border-b-2 -mb-px transition-colors ${tab === k ? "border-[#0044FF] text-foreground font-medium" : "border-transparent text-muted-foreground hover:text-foreground"}`}>{lbl}</button>
        ))}
        <span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground">{t("net.simulated")}</span>
      </div>

      {nodes.length === 0 ? (
        <div className="text-muted-foreground text-sm py-16 text-center">{t("net.no_equipment")}</div>
      ) : tab === "topology" ? (
        <Topology nodes={nodes} edges={topo.edges} onSelect={setSheet} />
      ) : (
        <div className="border border-border bg-card overflow-x-auto" data-testid="net-list">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="px-3 py-2">{t("common.status")}</th><th className="px-3 py-2">{t("common.name")}</th>
              <th className="px-3 py-2">{t("net.type")}</th><th className="px-3 py-2">{t("net.ip")}</th>
              <th className="px-3 py-2">{t("common.site")}</th><th className="px-3 py-2">{t("net.latency")}</th>
              <th className="px-3 py-2 text-right">{t("common.actions")}</th>
            </tr></thead>
            <tbody>
              {nodes.map((n) => {
                const Icon = TYPE_ICON[n.type] || Box; const col = STATUS_COLOR[n.status];
                return (
                  <tr key={n.id} className="border-b border-border hover:bg-secondary/50 cursor-pointer" data-testid="net-row" onClick={() => setSheet(n)}>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: col }}>
                        {n.status === "online" ? <Wifi size={13} /> : n.status === "warning" ? <AlertTriangle size={13} /> : <WifiOff size={13} />}
                        {statusLabel(t, n.status)}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-medium flex items-center gap-2"><Icon size={15} className="text-muted-foreground" />{n.name}</td>
                    <td className="px-3 py-2"><span className="text-[10px] px-1.5 py-0.5 border border-border">{n.type}</span></td>
                    <td className="px-3 py-2 mono text-xs">{n.ip || "—"}</td>
                    <td className="px-3 py-2 text-muted-foreground">{n.site_name}</td>
                    <td className="px-3 py-2 mono text-xs">{n.latency_ms != null ? `${n.latency_ms} ms` : "—"}</td>
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => ping(n)} data-testid="net-ping-btn" title={t("net.ping")} className="p-1.5 hover:bg-secondary"><Activity size={15} /></button>
                        {can("technician") && <button onClick={() => del(n)} data-testid="net-delete-btn" className="p-1.5 hover:bg-secondary text-[#FF3333]"><Trash2 size={15} /></button>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Fiche équipement */}
      {sheet && (
        <Dialog open={!!sheet} onOpenChange={(o) => !o && setSheet(null)}>
          <DialogContent className="rounded-none border-border max-w-md" data-testid="net-sheet">
            <DialogHeader>
              <DialogTitle className="font-head flex items-center gap-2">
                {React.createElement(TYPE_ICON[sheet.type] || Box, { size: 18, style: { color: STATUS_COLOR[sheet.status] } })}
                {sheet.name}
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-2 text-sm">
              <Row label={t("common.status")}><span style={{ color: STATUS_COLOR[sheet.status] }}>{statusLabel(t, sheet.status)}</span></Row>
              <Row label={t("net.type")}>{sheet.type}</Row>
              <Row label={t("net.ip")}><span className="mono text-xs">{sheet.ip || "—"}</span></Row>
              <Row label={t("net.vendor")}>{sheet.vendor || "—"}</Row>
              <Row label={t("net.model")}>{sheet.model || "—"}</Row>
              <Row label={t("common.site")}>{sheet.site_name}</Row>
              <Row label={t("net.latency")}><span className="mono text-xs">{sheet.latency_ms != null ? `${sheet.latency_ms} ms` : "—"}</span></Row>
              <Row label={t("net.uptime")}>{fmtUptime(sheet.uptime_sec)}</Row>
              {sheet.type === "UPS" && (
                <>
                  <Row label={t("net.battery")}>{sheet.battery_pct != null ? `${sheet.battery_pct}%` : "—"}</Row>
                  <Row label={t("net.on_battery")}><span style={{ color: sheet.on_battery ? "#FFB800" : "#00E676" }}>{sheet.on_battery ? "⚠ " + t("net.on_battery") : t("common.online")}</span></Row>
                  {sheet.on_battery && <Row label={t("net.autonomy")}>{sheet.autonomy_min ? `${sheet.autonomy_min} min` : "—"}</Row>}
                </>
              )}
            </div>
            <DialogFooter>
              {can("technician") && <button onClick={() => del(sheet)} className="px-4 py-2 border border-border text-sm text-[#FF3333] hover:bg-secondary flex items-center gap-2"><Trash2 size={15} /> {t("common.delete")}</button>}
              <button onClick={() => ping(sheet)} disabled={pinging} data-testid="net-sheet-ping" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{pinging ? <Loader2 size={15} className="animate-spin" /> : <Activity size={15} />} {t("net.ping")}</button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {/* Ajout */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="rounded-none border-border max-w-lg">
          <DialogHeader><DialogTitle className="font-head">{t("net.add")}</DialogTitle></DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("common.name")}><input data-testid="net-form-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp" /></Field>
            <Field label={t("net.type")}><select data-testid="net-form-type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="inp">{TYPES.map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label={t("common.site")}>
              <select data-testid="net-form-site" value={form.site_id} onChange={(e) => setForm({ ...form, site_id: e.target.value })} className="inp">
                <option value="">—</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label={t("net.ip")}><input data-testid="net-form-ip" value={form.ip} onChange={(e) => setForm({ ...form, ip: e.target.value })} className="inp mono text-xs" placeholder="10.0.0.1" /></Field>
            <Field label={t("net.vendor")}><input value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} className="inp" /></Field>
            <Field label={t("net.model")}><input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} className="inp" /></Field>
            <div className="col-span-2"><Field label={t("net.parent")}>
              <select value={form.parent_id} onChange={(e) => setForm({ ...form, parent_id: e.target.value })} className="inp">
                <option value="">— ({t("common.none")})</option>
                {nodes.filter((n) => !filterSite || n.site_id === form.site_id).map((n) => <option key={n.id} value={n.id}>{n.name} ({n.type})</option>)}
              </select>
            </Field></div>
          </div>
          <DialogFooter>
            <button onClick={() => setOpen(false)} className="px-4 py-2 border border-border text-sm hover:bg-secondary">{t("common.cancel")}</button>
            <button onClick={submit} disabled={saving} data-testid="net-form-submit" className="px-4 py-2 bg-[#0044FF] text-white text-sm flex items-center gap-2">{saving && <Loader2 size={15} className="animate-spin" />}{t("common.save")}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <style>{`.inp{width:100%;padding:0.5rem 0.625rem;background:hsl(var(--card));border:1px solid hsl(var(--input));font-size:0.875rem;outline:none}.inp:focus{border-color:#0044FF}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return <div><label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</label>{children}</div>;
}
function Row({ label, children }) {
  return <div className="flex items-center justify-between border-b border-border/60 py-1.5"><span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span><span className="text-sm">{children}</span></div>;
}
