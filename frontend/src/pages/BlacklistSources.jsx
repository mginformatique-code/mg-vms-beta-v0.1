import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Ban, Plus, RefreshCw, Trash2, Pencil, Loader2, CheckCircle2, XCircle,
  Clock, Copy, Webhook, Globe, FileSpreadsheet,
} from "lucide-react";

/**
 * v3.73 · Administration — Sources de blacklist externes.
 *
 * Gros chantier ANPR (voir docs.mg-vms.com/Chantiers) — première tranche :
 * connexion générique à une source externe (API REST JSON, CSV distant, ou
 * webhook poussé) + synchronisation automatique. La comparaison
 * déterministe elle-même (chaque plaque détectée vs `db.watchlist`) et
 * l'alerte qui en découle existent déjà (routers.py::maybe_blacklist_alert)
 * — cette page ne fait qu'alimenter automatiquement cette même liste
 * depuis l'extérieur, au lieu du seul import CSV manuel déjà existant
 * (Administration → Plugins → ANPR).
 */

const KIND_META = {
  rest_json: { labelKey: "blsrc.kind_rest", icon: Globe },
  csv_url: { labelKey: "blsrc.kind_csv", icon: FileSpreadsheet },
  webhook: { labelKey: "blsrc.kind_webhook", icon: Webhook },
};

const EMPTY_FORM = {
  name: "", kind: "rest_json", url: "", http_method: "GET",
  auth_type: "none", auth_header_name: "X-API-Key",
  auth_key: "", auth_username: "", auth_password: "",
  json_plate_path: "plates", csv_column: "plate",
  sync_interval_minutes: 60, enabled: true,
};

function StatusBadge({ source }) {
  const { t } = useApp();
  if (source.kind === "webhook") {
    return <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 border border-[#A855F7] text-[#A855F7]">{t("blsrc.status_direct")}</span>;
  }
  if (!source.last_sync_at) {
    return <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 border border-border text-muted-foreground">{t("blsrc.status_never")}</span>;
  }
  const ok = source.last_sync_status === "ok";
  const Icon = ok ? CheckCircle2 : XCircle;
  const color = ok ? "#00E676" : "#FF3333";
  return (
    <span className="flex items-center gap-1 text-[10px] uppercase tracking-wider px-2 py-0.5 border" style={{ borderColor: color, color }}>
      <Icon size={11} /> {ok ? `${source.last_sync_count} ${t("blsrc.plates_suffix")}` : t("blsrc.status_fail")} · {new Date(source.last_sync_at).toLocaleString()}
    </span>
  );
}

function SourceForm({ initial, onSaved, onClose }) {
  const { t } = useApp();
  const [form, setForm] = useState(initial || EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const editing = !!initial?.id;
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async () => {
    if (!form.name.trim()) return toast.error(t("blsrc.err_name_required"));
    if (form.kind !== "webhook" && !form.url.trim()) return toast.error(t("blsrc.err_url_required"));
    setSaving(true);
    try {
      const payload = { ...form };
      delete payload.id;
      let created = null;
      if (editing) {
        await api.put(`/blacklist-sources/${initial.id}`, payload);
        toast.success(t("blsrc.toast_updated"));
      } else {
        const { data } = await api.post("/blacklist-sources", payload);
        created = data;
        toast.success(t("blsrc.toast_created"));
      }
      onSaved(created);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("blsrc.err_save_failed"));
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-3 text-sm">
      <label className="block text-xs">{t("blsrc.name_label")}
        <input className="inp mt-1" value={form.name} onChange={(e) => set("name", e.target.value)}
          data-testid="bl-source-name" />
      </label>

      <label className="block text-xs">{t("blsrc.kind_label")}
        <select className="inp mt-1" value={form.kind} onChange={(e) => set("kind", e.target.value)} data-testid="bl-source-kind">
          {Object.entries(KIND_META).map(([k, m]) => <option key={k} value={k}>{t(m.labelKey)}</option>)}
        </select>
      </label>

      {form.kind !== "webhook" && (
        <>
          <label className="block text-xs">{t("blsrc.url_label")} {form.kind === "rest_json" ? t("blsrc.url_suffix_api") : t("blsrc.url_suffix_csv")}
            <input className="inp mt-1" value={form.url} onChange={(e) => set("url", e.target.value)}
              placeholder="https://…" data-testid="bl-source-url" />
          </label>

          <label className="block text-xs">{t("blsrc.auth_label")}
            <select className="inp mt-1" value={form.auth_type} onChange={(e) => set("auth_type", e.target.value)} data-testid="bl-source-auth-type">
              <option value="none">{t("blsrc.auth_none")}</option>
              <option value="api_key">{t("blsrc.auth_api_key")}</option>
              <option value="bearer">{t("blsrc.auth_bearer")}</option>
              <option value="basic">{t("blsrc.auth_basic")}</option>
            </select>
          </label>

          {form.auth_type === "api_key" && (
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-xs">{t("blsrc.header_name_label")}
                <input className="inp mt-1" value={form.auth_header_name} onChange={(e) => set("auth_header_name", e.target.value)} />
              </label>
              <label className="block text-xs">{t("blsrc.api_key_label")} {editing && <span className="text-muted-foreground">{t("blsrc.leave_blank_fem")}</span>}
                <input className="inp mt-1" type="password" value={form.auth_key} onChange={(e) => set("auth_key", e.target.value)} />
              </label>
            </div>
          )}
          {form.auth_type === "bearer" && (
            <label className="block text-xs">{t("blsrc.auth_bearer")} {editing && <span className="text-muted-foreground">{t("blsrc.leave_blank_masc")}</span>}
              <input className="inp mt-1" type="password" value={form.auth_key} onChange={(e) => set("auth_key", e.target.value)} />
            </label>
          )}
          {form.auth_type === "basic" && (
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-xs">{t("blsrc.username_label")}
                <input className="inp mt-1" value={form.auth_username} onChange={(e) => set("auth_username", e.target.value)} />
              </label>
              <label className="block text-xs">{t("blsrc.password_label")} {editing && <span className="text-muted-foreground">{t("blsrc.leave_blank_masc")}</span>}
                <input className="inp mt-1" type="password" value={form.auth_password} onChange={(e) => set("auth_password", e.target.value)} />
              </label>
            </div>
          )}

          {form.kind === "rest_json" ? (
            <label className="block text-xs">{t("blsrc.json_path_label")}
              <input className="inp mt-1" value={form.json_plate_path} onChange={(e) => set("json_plate_path", e.target.value)}
                placeholder="plates  ou  data.items[].plate" />
              <p className="text-[10px] text-muted-foreground mt-1">
                {t("blsrc.json_help_pre")} <code>[]</code> {t("blsrc.json_help_mid")} <code>{"{\"plates\":[\"AB123CD\"]}"}</code> → <code>plates</code>.
              </p>
            </label>
          ) : (
            <label className="block text-xs">{t("blsrc.csv_column_label")}
              <input className="inp mt-1" value={form.csv_column} onChange={(e) => set("csv_column", e.target.value)} />
            </label>
          )}

          <label className="block text-xs">{t("blsrc.sync_freq_label")}
            <select className="inp mt-1" value={form.sync_interval_minutes}
              onChange={(e) => set("sync_interval_minutes", Number(e.target.value))} data-testid="bl-source-interval">
              <option value={5}>{t("blsrc.freq_5min")}</option>
              <option value={15}>{t("blsrc.freq_15min")}</option>
              <option value={30}>{t("blsrc.freq_30min")}</option>
              <option value={60}>{t("blsrc.freq_1h")}</option>
              <option value={360}>{t("blsrc.freq_6h")}</option>
              <option value={1440}>{t("blsrc.freq_1day")}</option>
            </select>
          </label>
        </>
      )}

      {form.kind === "webhook" && !editing && (
        <p className="text-xs text-muted-foreground border border-border p-2">
          {t("blsrc.webhook_note")}
        </p>
      )}

      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} /> {t("blsrc.enabled_label")}
      </label>

      <div className="flex justify-end gap-2 pt-2">
        <button onClick={onClose} className="px-3 py-1.5 text-xs border border-border hover:bg-secondary">{t("blsrc.cancel")}</button>
        <button onClick={submit} disabled={saving} data-testid="bl-source-save"
          className="px-3 py-1.5 text-xs bg-[#0044FF] text-white disabled:opacity-50 flex items-center gap-1.5">
          {saving && <Loader2 size={12} className="animate-spin" />} {editing ? t("blsrc.save_btn") : t("blsrc.create_btn")}
        </button>
      </div>
    </div>
  );
}

function WebhookInfoDialog({ source, onClose }) {
  const { t } = useApp();
  const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
  const url = `${base}/api/blacklist-sources/webhook/${source.id}?token=${source.webhook_secret}`;
  const copy = () => { navigator.clipboard?.writeText(url); toast.success(t("blsrc.toast_url_copied")); };
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="rounded-none border-border max-w-lg">
        <DialogHeader><DialogTitle className="font-head flex items-center gap-2"><Webhook size={16} /> {source.name}</DialogTitle></DialogHeader>
        <div className="space-y-2 text-sm">
          <p className="text-xs text-muted-foreground">
            {t("blsrc.webhook_config_pre")} <code>POST</code> {t("blsrc.webhook_config_mid")}
            <code>{" {\"plate\": \"AB123CD\"} "}</code> {t("blsrc.webhook_config_or")} <code>{" {\"plates\": [\"AB123CD\", ...]} "}</code>.
          </p>
          <div className="flex items-center gap-2 border border-border p-2">
            <code className="text-[11px] flex-1 break-all">{url}</code>
            <button onClick={copy} className="p-1.5 hover:bg-secondary" title={t("blsrc.copy_title")}><Copy size={13} /></button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function BlacklistSources() {
  const { t } = useApp();
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null = fermé, {} = création, {...} = édition
  const [webhookInfo, setWebhookInfo] = useState(null);
  const [syncingId, setSyncingId] = useState(null);

  const load = () => {
    setLoading(true);
    api.get("/blacklist-sources").then((r) => setSources(r.data || [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const syncNow = async (s) => {
    setSyncingId(s.id);
    try {
      const { data } = await api.post(`/blacklist-sources/${s.id}/sync-now`);
      if (data.ok === false) toast.error(`${t("blsrc.err_sync_prefix")} ${data.error}`);
      else toast.success(`${t("blsrc.toast_synced_prefix")} ${data.total} ${t("blsrc.plates_suffix")} (+${data.added}/-${data.removed})`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("blsrc.err_sync_failed"));
    } finally { setSyncingId(null); }
  };

  const remove = async (s) => {
    if (!window.confirm(`${t("blsrc.confirm_delete_prefix")} "${s.name}" ${t("blsrc.confirm_delete_suffix")}`)) return;
    try { await api.delete(`/blacklist-sources/${s.id}`); toast.success(t("blsrc.toast_deleted")); load(); }
    catch (e) { toast.error(t("blsrc.err_delete_refused")); }
  };

  const openWebhookInfo = async (s) => {
    const { data } = await api.get(`/blacklist-sources/${s.id}`);
    setWebhookInfo(data);
  };

  return (
    <div className="p-4 max-w-4xl" data-testid="blacklist-sources-page">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2"><Ban size={22} /> {t("blsrc.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("blsrc.description")}
          </p>
        </div>
        <button onClick={() => setEditing({})} data-testid="bl-source-new"
          className="px-3 py-1.5 bg-[#0044FF] text-white text-xs flex items-center gap-1.5 shrink-0">
          <Plus size={14} /> {t("blsrc.new_source")}
        </button>
      </div>

      {loading ? (
        <div className="text-sm text-muted-foreground py-8 text-center">{t("blsrc.loading")}</div>
      ) : sources.length === 0 ? (
        <div className="text-sm text-muted-foreground py-8 text-center border border-dashed border-border">
          {t("blsrc.empty_state")}
        </div>
      ) : (
        <div className="space-y-2">
          {sources.map((s) => {
            const Meta = KIND_META[s.kind];
            return (
              <div key={s.id} className="border border-border p-3 flex items-center gap-3" data-testid="bl-source-row">
                <Meta.icon size={16} className="text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium flex items-center gap-2">
                    {s.name}
                    {!s.enabled && <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border border-border text-muted-foreground">{t("blsrc.disabled_badge")}</span>}
                  </div>
                  <div className="text-xs text-muted-foreground truncate mono">{t(Meta.labelKey)}{s.kind !== "webhook" ? ` · ${s.url}` : ""}</div>
                </div>
                <StatusBadge source={s} />
                {s.kind === "webhook" ? (
                  <button onClick={() => openWebhookInfo(s)} className="p-1.5 border border-border hover:bg-secondary" title={t("blsrc.view_webhook_title")}>
                    <Webhook size={13} />
                  </button>
                ) : (
                  <button onClick={() => syncNow(s)} disabled={syncingId === s.id} className="p-1.5 border border-border hover:bg-secondary disabled:opacity-40" title={t("blsrc.sync_now_title")}>
                    {syncingId === s.id ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                  </button>
                )}
                <button onClick={() => setEditing(s)} className="p-1.5 border border-border hover:bg-secondary" title={t("blsrc.edit_title")}><Pencil size={13} /></button>
                <button onClick={() => remove(s)} className="p-1.5 border border-border hover:bg-secondary text-[#FF3333]" title={t("blsrc.delete_title")}><Trash2 size={13} /></button>
              </div>
            );
          })}
        </div>
      )}

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="rounded-none border-border max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-head">{editing?.id ? t("blsrc.edit_source_title") : t("blsrc.new_source_title")}</DialogTitle></DialogHeader>
          {editing && (
            <SourceForm
              initial={editing.id ? editing : null}
              onSaved={(created) => {
                setEditing(null);
                load();
                if (created?.kind === "webhook") setWebhookInfo(created);
              }}
              onClose={() => setEditing(null)}
            />
          )}
        </DialogContent>
      </Dialog>

      {webhookInfo && <WebhookInfoDialog source={webhookInfo} onClose={() => setWebhookInfo(null)} />}
    </div>
  );
}
