import React, { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

/**
 * v3.22 · État des conteneurs Docker (Suivi des performances → Debug).
 *
 * Le backend n'a jamais d'accès direct à Docker (pas de socket monté,
 * décision du 31/08) — les données viennent de GET /system/containers,
 * qui relit un instantané écrit côté hôte par un timer systemd toutes
 * les 10s (voir install.sh::mgvms-container-status-watch).
 */
function timeAgo(iso) {
  if (!iso) return "?";
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "?";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h${m % 60 ? (m % 60) + "min" : ""}`;
  const d = Math.floor(h / 24);
  return `${d}j`;
}

function dotColor(c) {
  if (!c.running) return "#FF3333";
  if (c.health === "unhealthy") return "#FF3333";
  if (c.health === "starting") return "#FFB800";
  return "#00E676"; // healthy ou "n/a" (pas de healthcheck déclaré)
}

function ContainerCard({ c }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      className="relative border border-border p-3 bg-card"
      data-testid={`container-card-${c.name}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="flex items-center gap-2">
        <span
          className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
          style={{ background: dotColor(c) }}
        />
        <span className="text-sm font-medium truncate">{c.name}</span>
      </div>
      <div className="text-[11px] text-muted-foreground mt-1">
        {c.running ? `en marche · ${timeAgo(c.started_at)}` : c.status}
        {c.health !== "n/a" && c.health ? ` · ${c.health}` : ""}
      </div>

      {hover && (
        <div className="absolute z-10 left-0 top-full mt-1 w-72 border border-border bg-popover shadow-lg p-3 text-[11px] space-y-1"
             data-testid={`container-tooltip-${c.name}`}>
          <div><span className="text-muted-foreground">Nom complet : </span>{c.name}</div>
          <div><span className="text-muted-foreground">Image : </span>{c.image}</div>
          <div><span className="text-muted-foreground">IP interne : </span>{c.internal_ip || "—"}</div>
          <div><span className="text-muted-foreground">Statut : </span>{c.status}{c.health !== "n/a" ? ` (${c.health})` : ""}</div>
          <div><span className="text-muted-foreground">Démarré : </span>{c.started_at ? new Date(c.started_at).toLocaleString("fr-FR") : "—"}</div>
          <div><span className="text-muted-foreground">Redémarrages : </span>{c.restart_count ?? 0}</div>
          {c.ports && c.ports.length > 0 && (
            <div>
              <span className="text-muted-foreground">Ports publiés : </span>
              {c.ports.map((p) => p.host?.length ? `${p.container}→${p.host.join(",")}` : null).filter(Boolean).join(" · ") || "—"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ContainerStatusPanel() {
  const [data, setData] = useState(null);
  const load = useCallback(async () => {
    try {
      const r = await api.get("/system/containers");
      setData(r.data);
    } catch (e) {
      setData({ containers: [], stale: true, error: "endpoint indisponible" });
    }
  }, []);
  useEffect(() => {
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, [load]);

  const containers = data?.containers || [];

  return (
    <Card className="p-4 space-y-3" data-testid="container-status-panel">
      <div className="flex justify-between items-center">
        <div className="text-sm text-muted-foreground">
          État des conteneurs
          {data?.stale && containers.length > 0 && (
            <span className="text-[#FFB800] ml-2">(instantané ancien — {data.age_seconds}s)</span>
          )}
        </div>
        <Button size="sm" variant="ghost" onClick={load}>
          <RefreshCw className="w-4 h-4 mr-2" />Rafraîchir
        </Button>
      </div>

      {data?.error && containers.length === 0 && (
        <div className="text-[11px] text-muted-foreground">{data.error}</div>
      )}

      {containers.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
          {containers.map((c) => <ContainerCard key={c.name} c={c} />)}
        </div>
      )}
    </Card>
  );
}
