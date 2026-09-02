import React, { useCallback, useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, Terminal } from "lucide-react";

/**
 * v3.22 · Logs système — déplacé depuis l'onglet Debug de Suivi des
 * performances (retour utilisateur : n'a rien à faire mêlé au diagnostic
 * du pipeline IA) vers son propre sous-menu, à côté de Rapports/Journal
 * d'audit/Journal de diagnostic.
 */
export default function SystemLogs() {
  const { t } = useApp();
  const [logs, setLogs] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/diagnostics/logs?tail=200").catch(() => ({ data: "" }));
      setLogs(typeof r.data === "string" ? r.data : JSON.stringify(r.data, null, 2));
    } catch (e) {
      setLogs("(endpoint indisponible sur ce backend)");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-4 max-w-5xl" data-testid="system-logs-page">
      <div className="mb-5">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Terminal size={22} /> {t("nav.system_logs")}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">Journal brut du backend (tail 200 lignes).</p>
      </div>

      <Card className="p-4 space-y-3">
        <div className="flex justify-between items-center">
          <div className="text-sm text-muted-foreground">Logs récents</div>
          <Button size="sm" variant="ghost" onClick={load} disabled={loading}>
            <RefreshCw className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`} />Rafraîchir
          </Button>
        </div>
        <pre className="text-xs font-mono bg-black/40 p-3 rounded max-h-[70vh] overflow-auto">
          {logs || "…"}
        </pre>
      </Card>
    </div>
  );
}
