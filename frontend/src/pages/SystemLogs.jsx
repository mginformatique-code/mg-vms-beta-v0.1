import React, { useState } from "react";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Terminal, Loader2, LogOut, RefreshCw } from "lucide-react";
import HoldToRevealInput from "@/components/ui/hold-to-reveal-input";

/**
 * v3.27 · Logs système — n'affichait jusqu'ici jamais rien : le frontend
 * appelait `/api/diagnostics/logs`, un endpoint qui n'a jamais existé côté
 * backend. Reconstruit pour afficher les DERNIERS logs Debian (journalctl)
 * + les derniers logs de chaque conteneur Docker, via le même principe que
 * la console shell hôte (Suivi des performances → Debug) : identifiants
 * Linux réels saisis ici, jamais stockés ni journalisés, utilisés une
 * seule fois pour ouvrir une connexion SSH sortante ponctuelle vers
 * l'hôte — voir backend/routes/console_ssh.py::host_logs.
 */
export default function SystemLogs() {
  const { t } = useApp();
  const [status, setStatus] = useState("form"); // form | loading | loaded | error
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [activeTab, setActiveTab] = useState("syslog");

  const fetchLogs = async (e) => {
    e?.preventDefault();
    if (!username || !password) return;
    setStatus("loading");
    setError("");
    try {
      const { data: res } = await api.post("/system/console/host-logs", { username, password });
      setPassword(""); // effacé du state dès la réponse — jamais conservé plus longtemps que nécessaire
      setData(res);
      setActiveTab("syslog");
      setStatus("loaded");
    } catch (e2) {
      setPassword("");
      setError(e2.response?.data?.detail || t("syslog.fetch_failed"));
      setStatus("error");
    }
  };

  const reset = () => {
    setStatus("form"); setUsername(""); setPassword(""); setError(""); setData(null);
  };

  const containers = data ? Object.keys(data.docker || {}) : [];
  const activeText = activeTab === "syslog" ? (data?.syslog || "") : (data?.docker?.[activeTab] || "");

  return (
    <div className="p-4 max-w-5xl" data-testid="system-logs-page">
      <div className="mb-5">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Terminal size={22} /> {t("nav.system_logs")}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {t("syslog.subtitle")}
        </p>
      </div>

      <Card className="p-4 space-y-3">
        {status === "form" && (
          <form onSubmit={fetchLogs} className="space-y-2 max-w-sm" data-testid="system-logs-login-form">
            <p className="text-[11px] text-muted-foreground">
              {t("syslog.login_notice")}
            </p>
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("syslog.field_username")}</label>
              <input value={username} onChange={(e) => setUsername(e.target.value)}
                     autoComplete="off" data-testid="system-logs-username"
                     className="w-full px-3 py-2 bg-background border border-input outline-none text-sm focus:border-[#0044FF]" />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{t("syslog.field_password")}</label>
              <HoldToRevealInput value={password} onChange={(e) => setPassword(e.target.value)}
                     autoComplete="off" data-testid="system-logs-password"
                     className="w-full px-3 py-2 bg-background border border-input outline-none text-sm focus:border-[#0044FF]" />
            </div>
            <button type="submit" disabled={!username || !password} data-testid="system-logs-fetch-btn"
                    className="px-4 py-2 bg-[#0044FF] text-white text-sm disabled:opacity-40">
              {t("syslog.fetch_btn")}
            </button>
          </form>
        )}

        {status === "loading" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={15} className="animate-spin" /> {t("syslog.connecting")}
          </div>
        )}

        {status === "error" && (
          <div className="space-y-2">
            <p className="text-[12px] text-[#FF3333]">{typeof error === "string" ? error : JSON.stringify(error)}</p>
            <button onClick={reset} data-testid="system-logs-retry"
                    className="px-3 py-1.5 border border-border hover:bg-secondary text-xs">
              {t("syslog.retry_btn")}
            </button>
          </div>
        )}

        {status === "loaded" && (
          <>
            <div className="flex justify-between items-center flex-wrap gap-2">
              <div className="flex flex-wrap border border-border">
                <button onClick={() => setActiveTab("syslog")}
                        className={`px-3 py-1.5 text-xs ${activeTab === "syslog" ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}
                        data-testid="system-logs-tab-syslog">
                  {t("syslog.tab_system")}
                </button>
                {containers.map((name) => (
                  <button key={name} onClick={() => setActiveTab(name)}
                          className={`px-3 py-1.5 text-xs font-mono ${activeTab === name ? "bg-[#0044FF] text-white" : "hover:bg-secondary"}`}
                          data-testid={`system-logs-tab-${name}`}>
                    {name}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <button onClick={reset} className="text-[11px] flex items-center gap-1 px-2 py-1 border border-border hover:bg-secondary"
                        data-testid="system-logs-refresh">
                  <RefreshCw size={12} /> {t("syslog.refresh_btn")}
                </button>
                <button onClick={reset} data-testid="system-logs-disconnect"
                        className="text-[11px] flex items-center gap-1 px-2 py-1 border border-border hover:bg-secondary">
                  <LogOut size={12} /> {t("syslog.close_btn")}
                </button>
              </div>
            </div>
            <pre className="text-xs font-mono bg-black/40 p-3 rounded max-h-[65vh] overflow-auto" data-testid="system-logs-content">
              {activeText || t("syslog.no_output")}
            </pre>
          </>
        )}
      </Card>
    </div>
  );
}
