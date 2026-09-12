import React, { useState, useEffect } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Edit2, Save, X, Play, Zap, Loader2, ChevronRight } from "lucide-react";

const getTriggerTypes = (t) => [
  { type: "event.type", label: t("wf.trig_event_type"),
    fields: [{ key: "event_type", label: t("wf.fld_event_type"), placeholder: t("wf.ph_event_type_example") }] },
  { type: "zone.enter", label: t("wf.trig_zone_enter"),
    fields: [{ key: "zone_id", label: t("wf.fld_zone_id_all"), placeholder: t("wf.ph_uuid_or_empty") }] },
  { type: "zone.exit", label: t("wf.trig_zone_exit"),
    fields: [{ key: "zone_id", label: t("wf.fld_zone_id"), placeholder: t("wf.ph_uuid_or_empty") }] },
  { type: "zone.present", label: t("wf.trig_zone_present"),
    fields: [{ key: "zone_id", label: t("wf.fld_zone_id"), placeholder: t("wf.ph_uuid_or_empty") }] },
  { type: "plate.enter", label: t("wf.trig_plate_enter"), fields: [] },
  { type: "plate.exit",  label: t("wf.trig_plate_exit"),  fields: [] },
];

const getConditionTypes = (t) => [
  { type: "time_between", label: t("wf.cond_time_between"),
    fields: [{ key: "start", label: t("wf.fld_start_hhmm"), placeholder: "08:00" },
             { key: "end", label: t("wf.fld_end_hhmm"), placeholder: "18:00" }] },
  { type: "camera_is", label: t("wf.cond_camera_in_list"),
    fields: [{ key: "cameras", label: t("wf.fld_ids_csv"), isCsv: true, placeholder: "cam-1,cam-2" }] },
  { type: "plate_in_list", label: t("wf.cond_plate_status"),
    fields: [{ key: "lists", label: t("wf.fld_lists_csv"), isCsv: true, placeholder: "black" }] },
  { type: "field_equals", label: t("wf.cond_field_equals"),
    fields: [{ key: "path", label: t("wf.fld_path_example"), placeholder: "data.plate" },
             { key: "value", label: t("wf.fld_expected_value"), placeholder: "AB-123-CD" }] },
  { type: "field_regex", label: t("wf.cond_field_regex"),
    fields: [{ key: "path", label: t("wf.fld_path"), placeholder: "data.plate" },
             { key: "pattern", label: t("wf.fld_regex"), placeholder: "^AB-" }] },
];

const getActionTypes = (t) => [
  { type: "webhook",        label: "Webhook HTTP" },
  { type: "mqtt",           label: "MQTT publish" },
  { type: "home_assistant", label: "Home Assistant service" },
  { type: "tuya",           label: "Tuya Cloud device" },
  { type: "plugin",         label: "Plugin EventConsumer" },
  { type: "tts",            label: "Text-to-speech" },
  { type: "delay",          label: t("wf.action_delay") },
];

const EMPTY = { name: "", enabled: true, description: "",
                 triggers: [], conditions: [], actions: [] };


export default function Workflows() {
  const { t } = useApp();
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/workflows");
      setList(data.workflows || []);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const startEdit = (w) => setEditing(w ? JSON.parse(JSON.stringify(w)) : { ...EMPTY });

  const save = async () => {
    if (!editing.name) { toast.error(t("wf.err_name_required")); return; }
    setSaving(true);
    try {
      const payload = {
        name: editing.name, enabled: editing.enabled, description: editing.description || "",
        triggers: editing.triggers || [], conditions: editing.conditions || [],
        actions: editing.actions || [],
      };
      if (editing.id) {
        await api.put(`/workflows/${editing.id}`, payload);
        toast.success(t("wf.toast_updated"));
      } else {
        await api.post("/workflows", payload);
        toast.success(t("wf.toast_created"));
      }
      setEditing(null);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message); }
    finally { setSaving(false); }
  };

  const remove = async (id) => {
    if (!window.confirm(t("wf.confirm_delete"))) return;
    try {
      await api.delete(`/workflows/${id}`);
      toast.success(t("wf.toast_deleted"));
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message); }
  };

  const run = async (id) => {
    try {
      const { data } = await api.post(`/workflows/${id}/run`, {});
      const ok = data.status === "ok";
      toast[ok ? "success" : "error"](`${t("wf.toast_execution")} ${data.workflow_name} → ${data.status}`);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || e.message); }
  };

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto" data-testid="workflows-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-head font-bold text-2xl flex items-center gap-2">
            <Zap size={22} className="text-[#FFB800]" /> Workflows
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("wf.subtitle")}
          </p>
        </div>
        <button onClick={() => startEdit(null)} data-testid="workflow-create"
                className="flex items-center gap-2 px-3 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0044FF]/90">
          <Plus size={14} /> {t("wf.btn_new")}
        </button>
      </div>

      {loading ? (
        <div className="text-center text-muted-foreground py-12">
          <Loader2 size={20} className="animate-spin inline mr-2" /> {t("common.loading")}
        </div>
      ) : list.length === 0 ? (
        <div className="border border-dashed border-border p-8 text-center text-muted-foreground text-sm">
          {t("wf.empty_state")}
        </div>
      ) : (
        <div className="space-y-2" data-testid="workflows-list">
          {list.map((w) => {
            const rt = w.runtime || {};
            const okColor = rt.last_status === "ok" ? "#00E676" : rt.last_status === "error" ? "#FF3333" : "#888";
            return (
              <div key={w.id} className="border border-border p-3 bg-card flex items-start gap-3"
                   data-testid={`workflow-${w.id}`}>
                <div className="w-1.5 self-stretch" style={{ background: w.enabled ? "#00E676" : "#FF3333" }} />
                <div className="flex-1 min-w-0">
                  <div className="font-semibold flex items-center gap-2">
                    {w.name}
                    <span className="text-[10px] mono text-muted-foreground">
                      · {w.triggers?.length || 0} trigger(s) · {w.conditions?.length || 0} cond · {w.actions?.length || 0} action(s)
                    </span>
                  </div>
                  {w.description && (
                    <div className="text-xs text-muted-foreground mt-0.5">{w.description}</div>
                  )}
                  <div className="text-[10px] mono text-muted-foreground mt-1 flex flex-wrap gap-x-3">
                    <span>{t("wf.lbl_executions")} {w.execution_count || 0}</span>
                    <span style={{ color: okColor }}>{t("wf.lbl_status")} {rt.last_status || "idle"}</span>
                    {rt.last_run_at && <span>{t("wf.lbl_last_run")} {new Date(rt.last_run_at).toLocaleString()}</span>}
                  </div>
                  {w.triggers?.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1 text-[10px] mono">
                      {w.triggers.map((t2, i) => (
                        <span key={i} className="px-1.5 py-0.5 border border-border">
                          <ChevronRight size={9} className="inline" /> {t2.type}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex gap-1">
                  <button onClick={() => run(w.id)} title={t("wf.tooltip_run_now")}
                          data-testid={`workflow-${w.id}-run`}
                          className="p-1.5 border border-[#00E676] text-[#00E676] hover:bg-[#00E676]/10 text-xs">
                    <Play size={11} />
                  </button>
                  <button onClick={() => startEdit(w)}
                          data-testid={`workflow-${w.id}-edit`}
                          className="p-1.5 border border-border hover:bg-secondary text-xs">
                    <Edit2 size={11} />
                  </button>
                  <button onClick={() => remove(w.id)}
                          data-testid={`workflow-${w.id}-delete`}
                          className="p-1.5 border border-[#FF3333] text-[#FF3333] hover:bg-[#FF3333]/10 text-xs">
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {editing && (
        <WorkflowEditor
          workflow={editing}
          onChange={setEditing}
          onSave={save}
          onCancel={() => setEditing(null)}
          saving={saving}
        />
      )}
    </div>
  );
}


function WorkflowEditor({ workflow, onChange, onSave, onCancel, saving }) {
  const { t } = useApp();
  const TRIGGER_TYPES = getTriggerTypes(t);
  const CONDITION_TYPES = getConditionTypes(t);
  const ACTION_TYPES = getActionTypes(t);
  const update = (patch) => onChange({ ...workflow, ...patch });

  const addBlock = (kind, type) => {
    const arr = [...(workflow[kind] || [])];
    if (kind === "actions") arr.push({ type, config: {} });
    else arr.push({ type, ...(type === "camera_is" || type === "plate_in_list" ? {} : {}) });
    update({ [kind]: arr });
  };
  const updateBlock = (kind, idx, patch) => {
    const arr = [...(workflow[kind] || [])];
    arr[idx] = { ...arr[idx], ...patch };
    update({ [kind]: arr });
  };
  const removeBlock = (kind, idx) => {
    update({ [kind]: (workflow[kind] || []).filter((_, i) => i !== idx) });
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
         onClick={onCancel} data-testid="workflow-editor-modal">
      <div className="bg-card border border-border max-w-3xl w-full max-h-[92vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border sticky top-0 bg-card z-10">
          <div className="font-head font-semibold">
            {workflow.id ? t("common.edit") : t("wf.new")} workflow
          </div>
          <button onClick={onCancel} data-testid="workflow-editor-close"><X size={16} /></button>
        </div>

        <div className="p-5 space-y-4">
          <div className="grid grid-cols-3 gap-3 items-end">
            <div className="col-span-2">
              <label className="text-xs text-muted-foreground block mb-1">{t("common.name")}</label>
              <input value={workflow.name} onChange={(e) => update({ name: e.target.value })}
                     data-testid="workflow-name"
                     className="w-full px-2 py-1.5 bg-background border border-input outline-none text-sm" />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={workflow.enabled}
                     onChange={(e) => update({ enabled: e.target.checked })}
                     data-testid="workflow-enabled" />
              {t("common.active")}
            </label>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">{t("wf.fld_description")}</label>
            <input value={workflow.description || ""} onChange={(e) => update({ description: e.target.value })}
                   className="w-full px-2 py-1.5 bg-background border border-input outline-none text-sm" />
          </div>

          {/* TRIGGERS */}
          <Block title={t("wf.block_triggers_title")} color="#00E676"
                 onAdd={(type) => addBlock("triggers", type)} choices={TRIGGER_TYPES}>
            {(workflow.triggers || []).map((tr, i) => (
              <FieldRow key={i} spec={TRIGGER_TYPES.find(x => x.type === tr.type)}
                         obj={tr} onChange={(p) => updateBlock("triggers", i, p)}
                         onRemove={() => removeBlock("triggers", i)}
                         testid={`trigger-${i}`} />
            ))}
          </Block>

          {/* CONDITIONS */}
          <Block title={t("wf.block_conditions_title")} color="#FFB800"
                 onAdd={(type) => addBlock("conditions", type)} choices={CONDITION_TYPES}>
            {(workflow.conditions || []).map((c, i) => (
              <FieldRow key={i} spec={CONDITION_TYPES.find(x => x.type === c.type)}
                         obj={c} onChange={(p) => updateBlock("conditions", i, p)}
                         onRemove={() => removeBlock("conditions", i)}
                         testid={`condition-${i}`} />
            ))}
          </Block>

          {/* ACTIONS */}
          <Block title={t("wf.block_actions_title")} color="#0044FF"
                 onAdd={(type) => addBlock("actions", type)} choices={ACTION_TYPES}>
            {(workflow.actions || []).map((a, i) => (
              <div key={i} className="border border-border p-2 space-y-1" data-testid={`action-${i}`}>
                <div className="flex items-center justify-between">
                  <span className="text-sm mono font-semibold">{a.type}</span>
                  <button onClick={() => removeBlock("actions", i)}
                          className="text-[#FF3333] hover:opacity-80"><Trash2 size={12} /></button>
                </div>
                <textarea
                  value={JSON.stringify(a.config || {}, null, 2)}
                  onChange={(e) => {
                    try { updateBlock("actions", i, { config: JSON.parse(e.target.value || "{}") }); }
                    catch (_) { /* garde local */ }
                  }}
                  rows={4}
                  data-testid={`action-${i}-config`}
                  className="w-full px-2 py-1 bg-background border border-input outline-none text-xs mono"
                />
              </div>
            ))}
          </Block>
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-border sticky bottom-0 bg-card">
          <button onClick={onCancel} className="px-4 py-2 border border-border text-sm hover:bg-secondary">
            {t("common.cancel")}
          </button>
          <button onClick={onSave} disabled={saving}
                  data-testid="workflow-editor-save"
                  className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            {t("common.save")}
          </button>
        </div>
      </div>
    </div>
  );
}


function Block({ title, color, children, onAdd, choices }) {
  const { t } = useApp();
  return (
    <div className="border-l-2 pl-3" style={{ borderColor: color }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{title}</span>
        <select onChange={(e) => { if (e.target.value) { onAdd(e.target.value); e.target.value = ""; } }}
                defaultValue=""
                className="text-xs px-2 py-1 bg-background border border-input">
          <option value="">{t("wf.select_add")}</option>
          {choices.map((c) => <option key={c.type} value={c.type}>{c.label}</option>)}
        </select>
      </div>
      <div className="space-y-2">
        {children}
      </div>
    </div>
  );
}


function FieldRow({ spec, obj, onChange, onRemove, testid }) {
  if (!spec) return null;
  return (
    <div className="border border-border p-2 flex items-start gap-2" data-testid={testid}>
      <div className="flex-1 space-y-1">
        <div className="text-xs mono font-semibold">{spec.label}</div>
        <div className="grid grid-cols-2 gap-2">
          {(spec.fields || []).map((f) => (
            <input key={f.key}
                   placeholder={f.placeholder}
                   value={f.isCsv ? (obj[f.key] || []).join(",") : (obj[f.key] || "")}
                   onChange={(e) => onChange({
                     [f.key]: f.isCsv
                       ? e.target.value.split(",").map(s => s.trim()).filter(Boolean)
                       : e.target.value,
                   })}
                   className="px-2 py-1 bg-background border border-input outline-none text-xs mono" />
          ))}
        </div>
      </div>
      <button onClick={onRemove} className="text-[#FF3333] hover:opacity-80"><Trash2 size={12} /></button>
    </div>
  );
}
