/**
 * PipelineDesigner — Assemble un pipeline v2 : Camera → Detector → Tracker → ANPR → Fusion → Consumer.
 *
 * v0.4 · Preview de la future refonte Pipeline Designer. Utilise l'endpoint
 * /api/plugins/catalog + endpoint interne /api/pipeline-v2/describe pour construire
 * la vue. L'utilisateur choisit par étape un ou plusieurs providers.
 *
 * L'objectif à terme est de remplacer la case unique "Détection IA" par cette UI.
 */
import React, { useEffect, useState } from "react";
import { Cpu, MousePointerClick, Car, GitMerge, Zap, ArrowRight, Puzzle, Search } from "lucide-react";
import api from "@/lib/api";

const STAGE_META = [
  { id: "detectors",   label: "Detector",   icon: Cpu,               color: "#00E5FF", filter: (p) => p.interface === "FrameAnalyzer" || (p.categories||[]).some(c => /detect|vision|yolo/i.test(c)) },
  { id: "trackers",    label: "Tracker",    icon: MousePointerClick, color: "#00E676", filter: (p) => p.interface === "Tracker" || (p.categories||[]).some(c => /track/i.test(c)) },
  { id: "recognizers", label: "ANPR",       icon: Car,               color: "#FFB800", filter: (p) => p.interface === "PlateRecognizer" || (p.categories||[]).some(c => /anpr|lpr|plate/i.test(c)) },
  { id: "consumers",   label: "Consumer",   icon: Puzzle,            color: "#B085FF", filter: (p) => p.interface === "PipelineConsumer" || (p.categories||[]).some(c => /count|zone|workflow|fire|weapon|ppe/i.test(c)) },
];

const FUSION_STRATEGIES = [
  { id: "highest_confidence", label: "Highest confidence", desc: "Garde le reading avec la meilleure confiance" },
  { id: "majority_vote",       label: "Majority vote",       desc: "Consensus par texte (majoritaire l'emporte)" },
  { id: "weighted_vote",       label: "Weighted vote",       desc: "Vote pondéré par provider" },
  { id: "cascade",             label: "Cascade",             desc: "Essaie providers dans l'ordre" },
  { id: "first_success",       label: "First success",       desc: "Tout premier résultat non-vide" },
  { id: "best_latency",        label: "Best latency",        desc: "Le plus rapide (SLA)" },
];

function StageBlock({ stage, count, onClick }) {
  const Icon = stage.icon;
  return (
    <button onClick={onClick}
      className="flex flex-col items-center min-w-[130px] p-3 border border-border hover:border-[#00E5FF] transition-colors bg-secondary/30"
      data-testid={`stage-block-${stage.id}`}>
      <Icon size={20} style={{ color: stage.color }} />
      <div className="text-xs font-medium mt-1">{stage.label}</div>
      <div className="text-[10px] mono text-muted-foreground mt-0.5">
        {count > 0 ? `${count} sélectionné${count > 1 ? "s" : ""}` : "aucun"}
      </div>
    </button>
  );
}

export default function PipelineDesigner() {
  const [catalog, setCatalog] = useState({ groups: [] });
  const [selection, setSelection] = useState({
    detectors: [], trackers: [], recognizers: [], consumers: [],
  });
  const [fusion, setFusion] = useState({ strategy: "highest_confidence", min_confidence: 0.5 });
  const [openStage, setOpenStage] = useState(null);

  useEffect(() => {
    (async () => {
      try { const { data } = await api.get("/plugins/catalog"); setCatalog(data); }
      catch (e) { /* silent */ }
    })();
  }, []);

  const allPlugins = catalog.groups.flatMap(g => g.plugins);
  const stagePluginList = (stage) => allPlugins.filter(stage.filter);

  const toggle = (stageId, name) => {
    setSelection((s) => {
      const cur = s[stageId] || [];
      const next = cur.includes(name) ? cur.filter(n => n !== name) : [...cur, name];
      return { ...s, [stageId]: next };
    });
  };

  return (
    <div className="p-4" data-testid="pipeline-designer">
      <div className="mb-4">
        <h1 className="font-head font-bold text-2xl tracking-tight flex items-center gap-2">
          <Zap size={22} className="text-[#00E5FF]" /> Pipeline Designer
        </h1>
        <p className="text-[11px] text-muted-foreground mt-0.5">
          v0.4 · preview architecture v2 · Camera → Detector → Tracker → ANPR (Fusion) → Consumer.
          Cette UI remplacera à terme le Plugin Manager.
        </p>
      </div>

      {/* Pipeline visuel */}
      <div className="flex items-center gap-2 flex-wrap mb-4 p-4 border border-border bg-background/30" data-testid="pipeline-flow">
        <div className="flex flex-col items-center min-w-[100px] p-3 border border-[#00E676]/40 bg-[#00E676]/5">
          <div className="text-[10px] uppercase text-[#00E676]">Source</div>
          <div className="text-xs font-medium">Camera</div>
        </div>
        {STAGE_META.map((stage, i) => (
          <React.Fragment key={stage.id}>
            <ArrowRight size={16} className="text-muted-foreground" />
            <StageBlock stage={stage} count={selection[stage.id].length}
              onClick={() => setOpenStage(openStage === stage.id ? null : stage.id)} />
            {stage.id === "recognizers" && selection.recognizers.length > 1 && (
              <>
                <ArrowRight size={16} className="text-muted-foreground" />
                <div className="flex flex-col items-center min-w-[110px] p-3 border border-border bg-secondary/30">
                  <GitMerge size={18} className="text-[#FF9500]" />
                  <div className="text-xs font-medium mt-1">Fusion</div>
                  <div className="text-[10px] mono text-muted-foreground mt-0.5">
                    {fusion.strategy}
                  </div>
                </div>
              </>
            )}
          </React.Fragment>
        ))}
      </div>

      {/* Panneau selection courante */}
      {openStage && (
        <div className="border border-[#00E5FF]/40 p-3 mb-4 bg-secondary/20" data-testid="stage-picker">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium">
              Sélectionner les providers pour l&apos;étape « {STAGE_META.find(s => s.id === openStage).label} »
            </span>
            <button onClick={() => setOpenStage(null)} className="text-[10px] text-muted-foreground hover:text-foreground">Fermer</button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-1 max-h-64 overflow-y-auto">
            {stagePluginList(STAGE_META.find(s => s.id === openStage)).map((p) => {
              const on = selection[openStage].includes(p.name);
              return (
                <label key={p.name}
                  className={`flex items-start gap-2 p-1.5 text-[11px] cursor-pointer border ${on ? "border-[#00E5FF]/60 bg-[#00E5FF]/5" : "border-transparent hover:bg-secondary/40"}`}
                  data-testid={`picker-${p.name}`}>
                  <input type="checkbox" checked={on} onChange={() => toggle(openStage, p.name)} className="mt-0.5" />
                  <div className="min-w-0">
                    <div className="font-medium truncate">{p.display_name}</div>
                    <div className="text-[10px] text-muted-foreground line-clamp-1">{p.description || p.name}</div>
                  </div>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {/* Panneau Fusion (visible si >= 2 recognizers) */}
      {selection.recognizers.length > 1 && (
        <div className="border border-border p-3 mb-4" data-testid="fusion-config">
          <div className="flex items-center gap-2 mb-2">
            <GitMerge size={14} className="text-[#FF9500]" />
            <span className="text-xs font-medium">Fusion Engine · {selection.recognizers.length} providers ANPR combinés</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5">
            {FUSION_STRATEGIES.map((s) => (
              <label key={s.id}
                className={`flex flex-col p-2 text-[11px] cursor-pointer border ${fusion.strategy === s.id ? "border-[#FF9500]/60 bg-[#FF9500]/5" : "border-border hover:bg-secondary/40"}`}
                data-testid={`fusion-${s.id}`}>
                <div className="flex items-center gap-1.5">
                  <input type="radio" checked={fusion.strategy === s.id}
                    onChange={() => setFusion({ ...fusion, strategy: s.id })} />
                  <span className="font-medium">{s.label}</span>
                </div>
                <span className="text-[10px] text-muted-foreground mt-0.5 pl-4">{s.desc}</span>
              </label>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground">Seuil de confiance :</span>
            <input type="number" step="0.05" min="0" max="1" value={fusion.min_confidence}
              onChange={(e) => setFusion({ ...fusion, min_confidence: parseFloat(e.target.value) })}
              className="w-20 px-2 py-1 text-xs bg-card border border-input mono"
              data-testid="fusion-min-conf" />
          </div>
        </div>
      )}

      {/* Résumé JSON */}
      <div className="border border-border p-3">
        <div className="text-[10px] uppercase text-muted-foreground mb-2">Configuration compilée</div>
        <pre className="text-[10px] mono whitespace-pre-wrap text-muted-foreground bg-background/50 p-2 max-h-40 overflow-y-auto" data-testid="pipeline-json">
{JSON.stringify({
  stages: STAGE_META.map(s => ({ [s.id]: selection[s.id] })).reduce((a, b) => ({ ...a, ...b }), {}),
  fusion: selection.recognizers.length > 1 ? fusion : null,
}, null, 2)}
        </pre>
        <div className="text-[10px] text-muted-foreground mt-2">
          Cette config sera bientôt appliquée par caméra via /api/cameras/{"{id}"}/pipeline.
        </div>
      </div>
    </div>
  );
}
