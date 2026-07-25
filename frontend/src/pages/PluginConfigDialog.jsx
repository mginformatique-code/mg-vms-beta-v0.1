/**
 * Modal de configuration d'un plugin ANPR — génère un formulaire à partir
 * du JSON Schema exposé par `/api/plugins/loader/{name}/schema`.
 *
 * Support minimal (v2.30 PoC) :
 *   - string / string[password / number / boolean / array-of-strings /
 *     string-enum
 *   - Les champs sensibles (api_token, secret_key, api_key, password, token)
 *     affichent "***" pour la valeur existante, et le PUT accepte "***" comme
 *     "ne pas changer" (préserve les secrets côté serveur).
 *
 * En v3.0 : remplacer par react-jsonschema-form avec support complet (nested,
 * refs, conditionals).
 */
import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { AlertTriangle, Info } from "lucide-react";

const SENSITIVE_KEYS = new Set(["api_token", "secret_key", "api_key", "password", "token", "subscription_key"]);

export default function PluginConfigDialog({ open, pluginName, onOpenChange, onSaved }) {
  const [schema, setSchema] = useState(null);
  const [config, setConfig] = useState({});
  const [keysSet, setKeysSet] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !pluginName) return;
    setLoading(true);
    Promise.all([
      api.get(`/plugins/loader/${pluginName}/schema`).catch(() => ({ data: null })),
      api.get(`/plugins/${pluginName}/config`).catch(() => ({ data: { config: {}, keys_set: [] } })),
    ])
      .then(([sR, cR]) => {
        setSchema(sR.data);
        setConfig(cR.data?.config || {});
        setKeysSet(cR.data?.keys_set || []);
      })
      .finally(() => setLoading(false));
  }, [open, pluginName]);

  const handleField = (key, value) => setConfig((prev) => ({ ...prev, [key]: value }));

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/plugins/${pluginName}/config`, config);
      toast.success(`Config de ${pluginName} enregistrée · rechargement à chaud effectué`);
      onSaved?.();
      onOpenChange(false);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Erreur d'enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const renderField = (key, prop) => {
    const value = config[key];
    const isSensitive = SENSITIVE_KEYS.has(key) || prop.format === "password";
    const required = (schema?.required || []).includes(key);

    // Enum → select
    if (Array.isArray(prop.enum)) {
      return (
        <select
          value={value ?? prop.default ?? ""}
          onChange={(e) => handleField(key, e.target.value)}
          className="w-full bg-background border border-border h-9 px-2 text-sm"
          data-testid={`config-field-${key}`}
        >
          <option value="">— choisir —</option>
          {prop.enum.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    }
    // Boolean → switch
    if (prop.type === "boolean") {
      return (
        <Switch
          checked={!!value}
          onCheckedChange={(v) => handleField(key, v)}
          data-testid={`config-field-${key}`}
        />
      );
    }
    // Number
    if (prop.type === "number" || prop.type === "integer") {
      return (
        <Input
          type="number"
          value={value ?? prop.default ?? ""}
          min={prop.minimum}
          max={prop.maximum}
          step={prop.type === "integer" ? 1 : "any"}
          onChange={(e) => handleField(key, e.target.value === "" ? undefined : Number(e.target.value))}
          className="h-9 text-sm"
          data-testid={`config-field-${key}`}
        />
      );
    }
    // Array of strings (comma-separated input)
    if (prop.type === "array" && prop.items?.type === "string") {
      const arrValue = Array.isArray(value) ? value : (prop.default || []);
      return (
        <Input
          value={arrValue.join(",")}
          onChange={(e) => handleField(key, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
          placeholder="valeurs séparées par virgule (ex: fr,us,de)"
          className="h-9 text-sm mono"
          data-testid={`config-field-${key}`}
        />
      );
    }
    // String (default) — masque si sensible
    return (
      <Input
        type={isSensitive ? "password" : "text"}
        value={value ?? ""}
        onChange={(e) => handleField(key, e.target.value)}
        placeholder={isSensitive && keysSet.includes(key) ? "*** (déjà configuré — laisser vide pour conserver)" : (prop.default || "")}
        className="h-9 text-sm"
        data-testid={`config-field-${key}`}
      />
    );
  };

  const properties = schema?.properties || {};

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="plugin-config-dialog">
        <DialogHeader>
          <DialogTitle className="font-head">
            Configurer&nbsp;: <span className="mono text-[#0044FF]">{pluginName}</span>
          </DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="text-sm text-muted-foreground py-8 text-center">Chargement du schéma…</div>
        ) : !schema ? (
          <div className="text-sm text-muted-foreground py-8 text-center flex items-center justify-center gap-2">
            <AlertTriangle size={14} className="text-[#FFB800]" /> Aucun schéma de configuration défini pour ce plugin.
          </div>
        ) : (
          <div className="space-y-4 py-2" data-testid="config-fields">
            {schema.description && (
              <div className="text-xs text-muted-foreground flex items-start gap-1.5 border-l-2 border-[#0044FF] pl-2">
                <Info size={12} className="mt-0.5 shrink-0 text-[#0044FF]" />
                <span>{schema.description}</span>
              </div>
            )}
            {Object.entries(properties).map(([key, prop]) => {
              const required = (schema.required || []).includes(key);
              return (
                <div key={key} className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-2 items-start">
                  <div>
                    <Label htmlFor={`f-${key}`} className="text-xs flex items-center gap-1">
                      {prop.title || key}
                      {required && <span className="text-[#FF3333]">*</span>}
                    </Label>
                    {prop.description && (
                      <div className="text-[10px] text-muted-foreground mt-0.5 leading-snug">{prop.description}</div>
                    )}
                  </div>
                  <div id={`f-${key}`}>{renderField(key, prop)}</div>
                </div>
              );
            })}
          </div>
        )}

        <DialogFooter className="border-t border-border pt-3">
          <Button variant="outline" onClick={() => onOpenChange(false)} data-testid="config-cancel">
            Annuler
          </Button>
          <Button
            onClick={save}
            disabled={saving || loading || !schema}
            data-testid="config-save"
          >
            {saving ? "Enregistrement…" : "Enregistrer et recharger"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
