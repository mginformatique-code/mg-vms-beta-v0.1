import React, { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import {
  Boxes, Zap, GitBranch, Trophy, Vote, ClipboardList, RefreshCw, PlayCircle,
  AlertTriangle, CheckCircle2, XCircle, Clock, FileJson, Package, Settings2, PackageX, WrenchIcon,
  Download, ChevronDown, ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import PluginConfigDialog from "@/pages/PluginConfigDialog";

const FUSION_MODES = [
  { id: "cascade", label: "Cascade", desc: "Séquentiel, stop dès confidence ≥ seuil (économise quota cloud)", Icon: GitBranch },
  { id: "highest", label: "Meilleure confidence", desc: "Parallèle, retient le résultat le plus confiant", Icon: Trophy },
  { id: "compare", label: "Comparaison", desc: "Parallèle, remonte toutes les divergences (QA)", Icon: ClipboardList },
  { id: "vote",    label: "Vote majoritaire", desc: "Parallèle, vote caractère par caractère (fusion)", Icon: Vote },
];

const IFACE_BADGE = {
  FrameAnalyzer:    { color: "#0044FF", label: "FrameAnalyzer" },
  PlateRecognizer:  { color: "#FFB800", label: "PlateRecognizer" },
  EventConsumer:    { color: "#A855F7", label: "EventConsumer" },
};

const STATE_META = {
  ready:              { color: "#00E676", label: "READY",       Icon: CheckCircle2, desc: "Prêt à recevoir des frames" },
  not_configured:    { color: "#FFB800", label: "À CONFIGURER", Icon: Settings2,   desc: "Configuration requise" },
  missing_dependency:{ color: "#A855F7", label: "DEP MANQUANTE",Icon: PackageX,    desc: "Dépendance Python/système absente" },
  error:              { color: "#FF3333", label: "ERREUR",       Icon: XCircle,    desc: "Erreur au chargement" },
  disabled:           { color: "#666",    label: "DÉSACTIVÉ",    Icon: WrenchIcon,   desc: "Désactivé manuellement" },
};

export default function PluginManagerNG() {
  const [bus, setBus] = useState(null);
  const [policy, setPolicy] = useState(null);
  const [loaderData, setLoaderData] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [savingPolicy, setSavingPolicy] = useState(false);

  // Config dialog
  const [configPlugin, setConfigPlugin] = useState(null);
  // Install deps jobs par plugin
  const [installJobs, setInstallJobs] = useState({});
  // Catégories dépliées
  const [expandedGroups, setExpandedGroups] = useState({ "object-detection": true, "anpr": true });

  // Multi-ANPR test panel
  const [testMode, setTestMode] = useState("cascade");
  const [testThreshold, setTestThreshold] = useState(0.85);
  const [testMocks, setTestMocks] = useState([
    { engine: "plate-recognizer", text: "AB-123-CD", confidence: 0.98 },
    { engine: "paddle-ocr",       text: "AB-123-CD", confidence: 0.91 },
    { engine: "easyocr",          text: "AB-125-CD", confidence: 0.72 },
  ]);
  const [testResult, setTestResult] = useState(null);
  const [running, setRunning] = useState(false);

  const load = async () => {
    setRefreshing(true);
    try {
      const [busR, polR, ldR] = await Promise.all([
        api.get("/plugins/bus"),
        api.get("/plugins/policy"),
        api.get("/plugins/loader"),
      ]);
      setBus(busR.data);
      setPolicy(polR.data);
      setLoaderData(ldR.data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Erreur chargement bus");
    } finally {
      setRefreshing(false);
    }
  };
  useEffect(() => { load(); const iv = setInterval(load, 15000); return () => clearInterval(iv); }, []);

  const toggleEntry = async (name, enabled) => {
    try {
      await api.post(`/plugins/bus/${name}/${enabled ? "enable" : "disable"}`);
      toast.success(`${name} ${enabled ? "activé" : "désactivé"} sur le bus`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  const installDeps = async (name) => {
    setInstallJobs((prev) => ({ ...prev, [name]: { status: "running", log: "" } }));
    try {
      const { data } = await api.post(`/plugins/${name}/install-deps`, {});
      setInstallJobs((prev) => ({ ...prev, [name]: data }));
      toast.info(`Installation en cours pour ${name}…`);
      // Polling
      const iv = setInterval(async () => {
        try {
          const r = await api.get(`/plugins/${name}/install-status`);
          setInstallJobs((prev) => ({ ...prev, [name]: r.data }));
          if (r.data.status !== "running") {
            clearInterval(iv);
            if (r.data.status === "success") {
              toast.success(`${name} : dépendances installées · état re-évalué`);
              load();
            } else {
              toast.error(`${name} : installation ${r.data.status} (rc=${r.data.returncode})`);
            }
          }
        } catch (err) {
          clearInterval(iv);
        }
      }, 3000);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
      setInstallJobs((prev) => {
        const c = { ...prev };
        delete c[name];
        return c;
      });
    }
  };

  const toggleGroup = (g) => setExpandedGroups((prev) => ({ ...prev, [g]: !prev[g] }));

  const savePolicy = async (patch) => {
    setSavingPolicy(true);
    try {
      const { data } = await api.put("/plugins/policy/anpr", patch);
      setPolicy((prev) => ({ ...prev, anpr: data }));
      toast.success("Politique ANPR mise à jour");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSavingPolicy(false);
    }
  };

  const runTest = async () => {
    setRunning(true);
    setTestResult(null);
    try {
      const { data } = await api.post("/plugins/test/multi-anpr", {
        mode: testMode,
        cascade_threshold: testThreshold,
        inject_mocks: testMocks,
      });
      setTestResult(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setRunning(false);
    }
  };

  const updateMock = (idx, field, value) => {
    setTestMocks((prev) => prev.map((m, i) => i === idx ? { ...m, [field]: value } : m));
  };

  const dynamicMap = Object.fromEntries((loaderData?.loaded || []).map((p) => [p.name, p]));

  return (
    <div className="space-y-6 mt-8" data-testid="plugin-manager-ng">
      {/* Header */}
      <div className="border-t border-border pt-6">
        <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
          <h2 className="font-head font-bold text-xl tracking-tight flex items-center gap-2">
            <Boxes size={20} className="text-[#0044FF]" />
            Plugin Manager NG
            <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 border border-[#0044FF] text-[#0044FF] mono">Preview</span>
          </h2>
          <button
            onClick={load}
            data-testid="plugin-ng-refresh"
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-border hover:bg-secondary"
          >
            <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} /> Rafraîchir
          </button>
        </div>
        <p className="text-sm text-muted-foreground">
          Bus multi-plugin conforme au chapitre 11 (§11.6). Chaque frame vidéo est dispatchée en parallèle
          vers tous les plugins actifs de l&apos;interface concernée, avec isolation crash + timeout par plugin.
        </p>
      </div>

      {/* Bus entries */}
      <section className="bg-card border border-border p-4" data-testid="plugin-bus-section">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-head font-semibold text-base flex items-center gap-2">
            <Zap size={16} className="text-[#00E676]" /> Bus runtime
          </h3>
          {bus && (
            <div className="text-[11px] text-muted-foreground mono flex items-center gap-3 flex-wrap">
              <span>Total : <b className="text-foreground">{bus.counts.total}</b></span>
              <span>FrameAnalyzer : <b className="text-foreground">{bus.counts.frame_analyzers}</b></span>
              <span>PlateRecognizer : <b className="text-foreground">{bus.counts.plate_recognizers}</b></span>
              <span>Actifs : <b className="text-[#00E676]">{bus.counts.enabled}</b></span>
              <span>Dispatch : <b className="text-[#00E676]">{bus.entries.filter((e) => e.dispatchable).length}</b></span>
            </div>
          )}
        </div>

        {!bus ? (
          <div className="text-xs text-muted-foreground">Chargement…</div>
        ) : bus.entries.length === 0 ? (
          <div className="text-xs text-muted-foreground py-4 text-center">Aucun plugin enregistré sur le bus.</div>
        ) : (
          <div className="space-y-3" data-testid="plugin-bus-entries">
            {(() => {
              // Groupement par provider_group depuis loaderData
              const groups = {};
              for (const e of bus.entries) {
                const dyn = dynamicMap[e.name];
                const g = dyn?.provider_group || (dyn?.categories?.[0]) || "other";
                (groups[g] = groups[g] || []).push(e);
              }
              const GROUP_META = {
                "object-detection": { label: "Object Detection Providers", color: "#0044FF",
                                       desc: "Détecteurs d'objets — activez le provider adapté à votre matériel (CPU / GPU / TensorRT / OpenVINO / ONNX)" },
                "anpr":             { label: "ANPR Providers", color: "#FFB800",
                                       desc: "Lecture de plaques d'immatriculation — plusieurs moteurs peuvent tourner en fusion (cascade/vote/highest)" },
                "other":            { label: "Autres", color: "#A855F7", desc: "" },
              };
              const sorted = Object.keys(groups).sort((a, b) => {
                const order = ["object-detection", "anpr", "other"];
                return order.indexOf(a) - order.indexOf(b);
              });
              return sorted.map((g) => {
                const meta = GROUP_META[g] || GROUP_META.other;
                const opened = expandedGroups[g] !== false;
                const entries = groups[g];
                const readyCount = entries.filter((e) => e.state === "ready").length;
                const Chev = opened ? ChevronDown : ChevronRight;
                return (
                  <div key={g} className="border border-border" data-testid={`plugin-group-${g}`}>
                    <button
                      onClick={() => toggleGroup(g)}
                      className="w-full flex items-center gap-2 px-3 py-2 bg-secondary/40 hover:bg-secondary transition-colors"
                    >
                      <Chev size={14} />
                      <span className="font-head font-bold text-sm" style={{ color: meta.color }}>
                        {meta.label}
                      </span>
                      <span className="mono text-[11px] text-muted-foreground">({entries.length})</span>
                      <span className="ml-auto text-[10px] mono">
                        <span className="text-[#00E676]">{readyCount} ready</span>
                        <span className="text-muted-foreground"> · {entries.length - readyCount} pending</span>
                      </span>
                    </button>
                    {opened && meta.desc && (
                      <div className="px-3 py-1.5 text-[11px] text-muted-foreground border-b border-border bg-background/40">
                        {meta.desc}
                      </div>
                    )}
                    {opened && (
                      <div className="divide-y divide-border">
                        {entries.map((e) => {
                          const badge = IFACE_BADGE[e.interface] || { color: "#666", label: e.interface };
                          const state = STATE_META[e.state] || STATE_META.ready;
                          const StateIcon = state.Icon;
                          const dyn = dynamicMap[e.name];
                          const hasSchema = dyn?.has_config_schema;
                          const hasDeps = (dyn?.python_dependencies || []).length > 0;
                          const canInstall = hasDeps && e.state === "missing_dependency";
                          const installJob = installJobs[e.name];
                          const installing = installJob?.status === "running";
                          return (
                            <div
                              key={e.name}
                              className="flex items-center gap-3 p-2.5"
                              style={{ borderLeftColor: state.color, borderLeftWidth: 3 }}
                              data-testid={`bus-row-${e.name}`}
                            >
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="font-head font-semibold text-sm">
                                    {dyn?.display_name || e.name}
                                  </span>
                                  <span className="text-[10px] mono text-muted-foreground">{e.name}</span>
                                  <span
                                    className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border"
                                    style={{ borderColor: badge.color, color: badge.color }}
                                  >
                                    {badge.label}
                                  </span>
                                  <span
                                    className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border flex items-center gap-1"
                                    style={{ borderColor: state.color, color: state.color }}
                                    data-testid={`bus-state-${e.name}`}
                                    title={state.desc}
                                  >
                                    <StateIcon size={9} /> {state.label}
                                  </span>
                                  <span className="text-[10px] mono text-muted-foreground">order {e.order}</span>
                                  {dyn && dyn.loaded && (
                                    <span
                                      className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 border border-[#00E676]/50 text-[#00E676] flex items-center gap-1"
                                      title={dyn.manifest_path}
                                    >
                                      <FileJson size={9} /> manifest v{dyn.version}
                                    </span>
                                  )}
                                </div>
                                {e.state_message && e.state !== "ready" && (
                                  <div className="text-[11px] mt-1 mono" style={{ color: state.color }} data-testid={`bus-state-msg-${e.name}`}>
                                    {e.state_message}
                                  </div>
                                )}
                                {installing && (
                                  <div className="text-[10px] mt-1 text-[#0044FF] flex items-center gap-1">
                                    <RefreshCw size={10} className="animate-spin" /> Installation pip en cours ({installJob.deps?.join(", ")})…
                                  </div>
                                )}
                                {installJob && installJob.status && installJob.status !== "running" && (
                                  <details className="mt-1">
                                    <summary className="text-[10px] cursor-pointer text-muted-foreground">
                                      Log installation (rc={installJob.returncode}, {installJob.status})
                                    </summary>
                                    <pre className="text-[9px] mono bg-black/40 p-2 mt-1 overflow-x-auto max-h-40 whitespace-pre-wrap">{installJob.log || "(vide)"}</pre>
                                  </details>
                                )}
                                <div className="flex items-center gap-4 mt-1 text-[10px] mono text-muted-foreground">
                                  <span>calls: {e.calls}</span>
                                  <span className={e.errors > 0 ? "text-[#FF3333]" : ""}>errors: {e.errors}</span>
                                  <span className={e.timeouts > 0 ? "text-[#FFB800]" : ""}>timeouts: {e.timeouts}</span>
                                  <span>last: {e.last_ms.toFixed(1)}ms</span>
                                </div>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                {canInstall && (
                                  <button
                                    onClick={() => installDeps(e.name)}
                                    disabled={installing}
                                    className="flex items-center gap-1 px-2 py-1 text-[11px] border border-[#A855F7]/60 text-[#A855F7] hover:bg-[#A855F7]/10 transition-colors disabled:opacity-50"
                                    data-testid={`bus-install-${e.name}`}
                                    title={`pip install ${(dyn?.python_dependencies || []).join(' ')}`}
                                  >
                                    <Download size={11} /> Installer
                                  </button>
                                )}
                                {hasSchema && (
                                  <button
                                    onClick={() => setConfigPlugin(e.name)}
                                    className="flex items-center gap-1 px-2 py-1 text-[11px] border border-border hover:border-[#0044FF] hover:text-[#0044FF] transition-colors"
                                    data-testid={`bus-configure-${e.name}`}
                                    title="Configurer ce plugin"
                                  >
                                    <Settings2 size={11} /> Configurer
                                  </button>
                                )}
                                <Switch
                                  checked={e.enabled}
                                  onCheckedChange={(v) => toggleEntry(e.name, v)}
                                  data-testid={`bus-toggle-${e.name}`}
                                />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              });
            })()}
          </div>
        )}

        {/* Loader errors */}
        {loaderData?.loaded?.some((p) => p.error) && (
          <div className="mt-3 border border-[#FFB800]/40 bg-[#FFB800]/5 p-2 text-[11px]" data-testid="loader-errors">
            <div className="flex items-center gap-1.5 font-semibold text-[#FFB800] mb-1">
              <AlertTriangle size={12} /> Erreurs du loader dynamique
            </div>
            {loaderData.loaded.filter((p) => p.error).map((p) => (
              <div key={p.name} className="mono">
                <b>{p.name}</b> — {p.error}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Multi-ANPR policy */}
      <section className="bg-card border border-border p-4" data-testid="plugin-policy-section">
        <h3 className="font-head font-semibold text-base flex items-center gap-2 mb-3">
          <Package size={16} className="text-[#FFB800]" /> Politique multi-ANPR
        </h3>
        {!policy ? (
          <div className="text-xs text-muted-foreground">Chargement…</div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2 mb-4" data-testid="policy-mode-grid">
              {FUSION_MODES.map((m) => {
                const active = policy.anpr.mode === m.id;
                const M = m.Icon;
                return (
                  <button
                    key={m.id}
                    onClick={() => savePolicy({ mode: m.id })}
                    disabled={savingPolicy}
                    data-testid={`policy-mode-${m.id}`}
                    className={`text-left p-3 border transition-colors ${
                      active
                        ? "border-[#0044FF] bg-[#0044FF]/5"
                        : "border-border hover:border-[#0044FF]/60"
                    }`}
                  >
                    <div className="flex items-center gap-1.5 mb-1">
                      <M size={14} className={active ? "text-[#0044FF]" : "text-muted-foreground"} />
                      <span className="font-head font-semibold text-sm">{m.label}</span>
                      {active && <CheckCircle2 size={12} className="text-[#00E676] ml-auto" />}
                    </div>
                    <div className="text-[10px] text-muted-foreground leading-snug">{m.desc}</div>
                  </button>
                );
              })}
            </div>

            {policy.anpr.mode === "cascade" && (
              <div className="border-t border-border pt-3" data-testid="cascade-threshold-config">
                <Label className="text-xs mb-2 block">
                  Seuil de confiance pour stopper la cascade :{" "}
                  <span className="mono text-foreground font-bold">
                    {(policy.anpr.cascade_threshold * 100).toFixed(0)}%
                  </span>
                </Label>
                <Slider
                  value={[policy.anpr.cascade_threshold]}
                  min={0.5}
                  max={0.99}
                  step={0.01}
                  onValueCommit={([v]) => savePolicy({ cascade_threshold: v })}
                  data-testid="cascade-threshold-slider"
                />
                <p className="text-[10px] text-muted-foreground mt-1">
                  Dès qu&apos;un moteur retourne une plaque avec confidence ≥ seuil, les moteurs suivants
                  ne sont pas appelés. Utile pour économiser un quota cloud coûteux.
                </p>
              </div>
            )}
          </>
        )}
      </section>

      {/* Test multi-ANPR panel */}
      <section className="bg-card border border-border p-4" data-testid="plugin-test-section">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-head font-semibold text-base flex items-center gap-2">
            <PlayCircle size={16} className="text-[#A855F7]" /> Test multi-ANPR (avec mocks)
          </h3>
          <Button
            onClick={runTest}
            disabled={running}
            size="sm"
            data-testid="run-multi-anpr-test"
          >
            {running ? "Exécution…" : "Lancer le test"}
          </Button>
        </div>

        <p className="text-xs text-muted-foreground mb-3">
          Injecte temporairement N moteurs ANPR factices sur le bus, exécute un cycle
          complet avec la politique choisie, puis nettoie. Aucune caméra ni quota consommé.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Config */}
          <div className="space-y-3">
            <div>
              <Label className="text-xs">Mode fusion</Label>
              <div className="grid grid-cols-4 gap-1 mt-1">
                {FUSION_MODES.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setTestMode(m.id)}
                    data-testid={`test-mode-${m.id}`}
                    className={`text-[10px] px-2 py-1 border transition-colors ${
                      testMode === m.id
                        ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF]"
                        : "border-border hover:border-[#0044FF]/60"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>

            {testMode === "cascade" && (
              <div>
                <Label className="text-xs">Seuil cascade : <span className="mono">{(testThreshold * 100).toFixed(0)}%</span></Label>
                <Slider
                  value={[testThreshold]}
                  min={0.5}
                  max={0.99}
                  step={0.01}
                  onValueChange={([v]) => setTestThreshold(v)}
                  className="mt-2"
                  data-testid="test-threshold-slider"
                />
              </div>
            )}

            <div>
              <Label className="text-xs mb-1 block">Mocks injectés</Label>
              <div className="space-y-1.5" data-testid="test-mocks">
                {testMocks.map((m, i) => (
                  <div key={i} className="grid grid-cols-[1fr_1fr_80px] gap-1.5 text-xs">
                    <Input
                      value={m.engine}
                      onChange={(e) => updateMock(i, "engine", e.target.value)}
                      placeholder="engine"
                      className="h-8 text-xs"
                      data-testid={`mock-${i}-engine`}
                    />
                    <Input
                      value={m.text}
                      onChange={(e) => updateMock(i, "text", e.target.value.toUpperCase())}
                      placeholder="AB-123-CD"
                      className="h-8 text-xs mono"
                      data-testid={`mock-${i}-text`}
                    />
                    <Input
                      type="number"
                      step="0.01"
                      min="0"
                      max="1"
                      value={m.confidence}
                      onChange={(e) => updateMock(i, "confidence", parseFloat(e.target.value) || 0)}
                      className="h-8 text-xs mono"
                      data-testid={`mock-${i}-conf`}
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Result */}
          <div className="border border-border bg-background/60 p-3">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
              Résultat
            </div>
            {!testResult ? (
              <div className="text-xs text-muted-foreground italic">
                Cliquez sur « Lancer le test » pour exécuter le pipeline.
              </div>
            ) : (
              <div className="space-y-2 text-xs" data-testid="test-result">
                <div>
                  <span className="text-muted-foreground">Mode : </span>
                  <span className="mono font-bold">{testResult.mode}</span>
                  {testResult.divergence && (
                    <span className="ml-2 text-[10px] px-1.5 py-0.5 border border-[#FFB800] text-[#FFB800]">
                      DIVERGENCE
                    </span>
                  )}
                </div>
                <div>
                  <span className="text-muted-foreground">Moteurs appelés : </span>
                  <span className="mono">{testResult.engines_called.join(", ") || "—"}</span>
                </div>
                {testResult.final ? (
                  <div className="border border-[#00E676] bg-[#00E676]/5 p-2" data-testid="test-final-plate">
                    <div className="text-[10px] uppercase tracking-wider text-[#00E676] mb-1 flex items-center gap-1">
                      <CheckCircle2 size={10} /> Plaque retenue
                    </div>
                    <div className="mono font-bold text-lg">{testResult.final.text}</div>
                    <div className="mono text-[10px] text-muted-foreground">
                      confidence: {(testResult.final.confidence * 100).toFixed(1)}%
                      {" · "}
                      engine: {testResult.final.engine}
                      {" · "}
                      {testResult.final.processing_ms}ms
                    </div>
                  </div>
                ) : (
                  <div className="border border-[#FF3333]/40 p-2 text-[#FF3333] text-[11px]">
                    <XCircle size={12} className="inline mr-1" /> Aucune plaque retenue
                  </div>
                )}
                <details className="mt-2">
                  <summary className="text-[10px] uppercase tracking-wider text-muted-foreground cursor-pointer">
                    Détail par moteur ({testResult.all_results.length})
                  </summary>
                  <div className="mt-1.5 space-y-1">
                    {testResult.all_results.map((r) => (
                      <div key={r.engine} className="mono text-[11px] border-l-2 border-border pl-2">
                        <b>{r.engine}</b>{" "}
                        {r.plates.length === 0 ? (
                          <span className="text-muted-foreground italic">aucun résultat</span>
                        ) : (
                          r.plates.map((p, i) => (
                            <span key={i} className="ml-2">
                              {p.text} <span className="text-muted-foreground">({(p.confidence * 100).toFixed(0)}%)</span>
                            </span>
                          ))
                        )}
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Config dialog (formulaire dynamique depuis JSON Schema) */}
      <PluginConfigDialog
        open={!!configPlugin}
        pluginName={configPlugin}
        onOpenChange={(v) => !v && setConfigPlugin(null)}
        onSaved={load}
      />
    </div>
  );
}
