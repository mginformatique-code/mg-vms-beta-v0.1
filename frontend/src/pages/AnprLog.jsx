import React, { useCallback, useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, ScanLine } from "lucide-react";

/**
 * v3.31 · Journal ANPR — tableau des véhicules les plus lus, toutes
 * caméras confondues. Demande explicite : un tableau, rien de plus.
 */
export default function AnprLog() {
  const { t } = useApp();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/vehicles/anpr-log/top?limit=200").catch(() => ({ data: { items: [] } }));
      setItems(r.data?.items || []);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-4 max-w-5xl" data-testid="anpr-log-page">
      <div className="mb-5">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <ScanLine size={22} /> {t("nav.anpr_log")}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Véhicules les plus lus par l'ANPR, toutes caméras confondues — trié par occurrences.
        </p>
      </div>

      <Card className="p-4 space-y-3">
        <div className="flex justify-between items-center">
          <div className="text-sm text-muted-foreground">{items.length} plaque(s)</div>
          <Button size="sm" variant="ghost" onClick={load} disabled={loading}>
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`} />Rafraîchir
          </Button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="anpr-log-table">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="pb-2 pr-4">#</th>
                <th className="pb-2 pr-4">Plaque</th>
                <th className="pb-2 pr-4">Occurrences</th>
                <th className="pb-2 pr-4">Caméras</th>
                <th className="pb-2 pr-4">Couleur</th>
                <th className="pb-2 pr-4">Type</th>
                <th className="pb-2">Dernière détection</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={it.plate} className="border-t border-border/40" data-testid="anpr-log-row">
                  <td className="py-2 pr-4 font-mono text-muted-foreground">{i + 1}</td>
                  <td className="py-2 pr-4 font-mono font-semibold">{it.plate}</td>
                  <td className="py-2 pr-4 font-mono">{it.occurrences}</td>
                  <td className="py-2 pr-4 font-mono">{it.cameras_count}</td>
                  <td className="py-2 pr-4">{it.vehicle_color || "—"}</td>
                  <td className="py-2 pr-4">{it.vehicle_type || "—"}</td>
                  <td className="py-2 font-mono text-xs">{it.last_seen || "—"}</td>
                </tr>
              ))}
              {items.length === 0 && !loading && (
                <tr><td colSpan={7} className="py-6 text-center text-muted-foreground" data-testid="anpr-log-empty">
                  Aucune plaque détectée.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
