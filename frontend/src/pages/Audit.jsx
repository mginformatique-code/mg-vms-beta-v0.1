import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { ScrollText } from "lucide-react";

const ACTION_COLOR = (a) => a.includes("delete") || a.includes("failed") ? "#FF3333" : a.includes("create") || a.includes("login") ? "#00E676" : "#0044FF";

export default function Audit() {
  const { t } = useApp();
  const [logs, setLogs] = useState([]);
  useEffect(() => { api.get("/audit").then((r) => setLogs(r.data)).catch(() => {}); }, []);

  return (
    <div className="p-4">
      <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2 mb-4"><ScrollText size={22} /> {t("audit.title")}</h1>
      <div className="border border-border bg-card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="px-3 py-2">{t("common.date")}</th><th className="px-3 py-2">{t("audit.user")}</th><th className="px-3 py-2">{t("audit.action")}</th><th className="px-3 py-2">{t("audit.target")}</th><th className="px-3 py-2">Détails</th>
          </tr></thead>
          <tbody>
            {logs.map((l) => (
              <tr key={l.id} className="border-b border-border hover:bg-secondary/50" data-testid="audit-row">
                <td className="px-3 py-2 mono text-xs text-muted-foreground whitespace-nowrap">{new Date(l.timestamp).toLocaleString()}</td>
                <td className="px-3 py-2 text-xs">{l.user_email}</td>
                <td className="px-3 py-2"><span className="text-[10px] uppercase tracking-wider mono" style={{ color: ACTION_COLOR(l.action) }}>{l.action}</span></td>
                <td className="px-3 py-2 text-xs mono">{l.target}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{l.details}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
