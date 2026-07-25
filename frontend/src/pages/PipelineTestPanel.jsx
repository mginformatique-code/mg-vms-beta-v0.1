/**
 * PipelineTestPanel — Test du pipeline complet Detector → Tracker → Segmenter → Business.
 *
 * Permet à l'utilisateur d'injecter des détections seed, lancer le pipeline,
 * et visualiser les bboxes/tracks/masques sur un canvas 640x480. Les événements
 * métier sont listés à droite avec leur sévérité.
 */
import React, { useEffect, useRef, useState } from "react";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { PlayCircle, AlertTriangle, CheckCircle2, Zap } from "lucide-react";
import { toast } from "sonner";

const PRESETS = {
  "Personne+Voiture (counting)": [
    { label: "person", confidence: 0.95, bbox: [200, 150, 260, 400] },
    { label: "person", confidence: 0.91, bbox: [350, 180, 410, 420] },
    { label: "car", confidence: 0.88, bbox: [100, 250, 300, 350] },
  ],
  "Feu + Arme (alerte critique)": [
    { label: "fire", confidence: 0.87, bbox: [300, 100, 500, 300] },
    { label: "knife", confidence: 0.92, bbox: [50, 200, 120, 280] },
  ],
  "Chute (personne allongée)": [
    { label: "person", confidence: 0.85, bbox: [100, 300, 400, 380] },
  ],
  "Foule (over-capacity)": Array.from({ length: 12 }, (_, i) => ({
    label: "person",
    confidence: 0.9,
    bbox: [100 + (i % 4) * 100, 100 + Math.floor(i / 4) * 100, 160 + (i % 4) * 100, 250 + Math.floor(i / 4) * 100],
  })),
};

const SEVERITY_COLOR = {
  critical: "#FF3333",
  warning: "#FFB800",
  info: "#0044FF",
};

const LABEL_COLORS = {
  person: "#00E676",
  car: "#0044FF",
  truck: "#0891B2",
  fire: "#FF3333",
  smoke: "#666",
  knife: "#DC2626",
  gun: "#DC2626",
};

export default function PipelineTestPanel() {
  const [preset, setPreset] = useState("Personne+Voiture (counting)");
  const [seedJson, setSeedJson] = useState(JSON.stringify(PRESETS[preset], null, 2));
  const [runSegmentation, setRunSegmentation] = useState(false);
  const [emitEvents, setEmitEvents] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const canvasRef = useRef(null);

  const applyPreset = (name) => {
    setPreset(name);
    setSeedJson(JSON.stringify(PRESETS[name], null, 2));
  };

  const run = async () => {
    let seed;
    try {
      seed = JSON.parse(seedJson);
    } catch (e) {
      toast.error("JSON invalide dans les détections seed");
      return;
    }
    setRunning(true);
    try {
      const { data } = await api.post("/plugins/pipeline/test", {
        detections_seed: seed,
        run_segmentation: runSegmentation,
        run_business: true,
        emit_events: emitEvents,
      });
      setResult(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setRunning(false);
    }
  };

  // Draw bboxes + tracks + masks
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#0a0a0a";
    ctx.fillRect(0, 0, 640, 480);

    // Grid
    ctx.strokeStyle = "#1a1a1a";
    ctx.lineWidth = 1;
    for (let x = 0; x < 640; x += 64) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 480); ctx.stroke();
    }
    for (let y = 0; y < 480; y += 48) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(640, y); ctx.stroke();
    }

    if (!result) return;

    // Detections (bboxes sans track)
    (result.detections || []).forEach((d) => {
      const color = LABEL_COLORS[d.label] || "#0044FF";
      const [x1, y1, x2, y2] = d.bbox;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "11px monospace";
      ctx.fillText(`${d.label} ${(d.confidence * 100).toFixed(0)}%`, x1, y1 - 4);
    });

    // Tracks (bboxes plein avec ID)
    (result.tracks || []).forEach((t) => {
      const color = LABEL_COLORS[t.label] || "#00E676";
      const [x1, y1, x2, y2] = t.bbox;
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      // ID badge
      ctx.fillStyle = color;
      ctx.fillRect(x1, y1, 60, 16);
      ctx.fillStyle = "#000";
      ctx.font = "bold 10px monospace";
      ctx.fillText(`#${t.track_id} ${t.label}`, x1 + 3, y1 + 12);
    });

    // Masks (silhouettes)
    (result.masks || []).forEach((m) => {
      const [x1, y1, x2, y2] = m.bbox;
      ctx.fillStyle = "rgba(234, 88, 12, 0.25)";
      ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
      ctx.strokeStyle = "#EA580C";
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    });
  }, [result]);

  return (
    <div className="space-y-3 mt-6" data-testid="pipeline-test-panel">
      <div className="border border-border p-4 bg-card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-head font-semibold text-base flex items-center gap-2">
            <Zap size={16} className="text-[#00E676]" /> Pipeline Test — Detector → Tracker → Business
          </h3>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 text-[11px]">
              <Switch checked={runSegmentation} onCheckedChange={setRunSegmentation} data-testid="pipeline-toggle-seg" />
              <span>Segmentation</span>
            </label>
            <label className="flex items-center gap-1 text-[11px]">
              <Switch checked={emitEvents} onCheckedChange={setEmitEvents} data-testid="pipeline-toggle-emit" />
              <span>Émettre events</span>
            </label>
            <Button onClick={run} disabled={running} size="sm" data-testid="pipeline-run">
              <PlayCircle size={13} className="mr-1" /> {running ? "Exécution…" : "Lancer"}
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[280px_640px_1fr] gap-3">
          {/* Presets + JSON */}
          <div className="space-y-2">
            <Label className="text-[11px]">Scénarios prédéfinis</Label>
            <div className="space-y-1">
              {Object.keys(PRESETS).map((name) => (
                <button
                  key={name}
                  onClick={() => applyPreset(name)}
                  data-testid={`pipeline-preset-${name}`}
                  className={`w-full text-left text-[11px] px-2 py-1.5 border transition-colors ${
                    preset === name
                      ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF]"
                      : "border-border hover:border-[#0044FF]/60"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>
            <Label className="text-[11px] mt-3 block">Détections JSON (bbox = [x1,y1,x2,y2])</Label>
            <textarea
              value={seedJson}
              onChange={(e) => setSeedJson(e.target.value)}
              rows={12}
              className="w-full bg-background border border-border text-[10px] mono p-2 resize-y"
              data-testid="pipeline-seed-json"
            />
          </div>

          {/* Canvas visualization */}
          <div>
            <Label className="text-[11px]">Visualisation (640×480 · fond noir)</Label>
            <canvas
              ref={canvasRef}
              width={640}
              height={480}
              className="border border-border bg-black mt-1"
              data-testid="pipeline-canvas"
            />
            {result && (
              <div className="mt-2 text-[10px] mono text-muted-foreground grid grid-cols-3 gap-2">
                <div>
                  <b className="text-foreground">{result.detections.length}</b> détections
                </div>
                <div>
                  <b className="text-[#00E676]">{result.tracks.length}</b> tracks
                </div>
                <div>
                  <b className="text-[#EA580C]">{result.masks.length}</b> masques
                </div>
                <div>Detect: {result.timing_ms.detection_ms || 0}ms</div>
                <div>Track: {result.timing_ms.tracking_ms || 0}ms</div>
                <div>Biz: {result.timing_ms.business_ms || 0}ms</div>
              </div>
            )}
          </div>

          {/* Events */}
          <div>
            <Label className="text-[11px]">Événements métier générés</Label>
            {!result ? (
              <div className="text-[11px] text-muted-foreground italic mt-2 py-4 text-center">
                Cliquez sur « Lancer » pour exécuter le pipeline.
              </div>
            ) : result.business_events.length === 0 ? (
              <div className="text-[11px] text-muted-foreground italic mt-2 py-4 text-center">
                Aucun événement métier généré pour ce scénario.
              </div>
            ) : (
              <div className="space-y-1.5 mt-1 max-h-[440px] overflow-y-auto" data-testid="pipeline-events">
                {result.business_events.map((ev, i) => {
                  const c = SEVERITY_COLOR[ev.severity] || "#666";
                  const Icon = ev.severity === "critical" ? AlertTriangle : CheckCircle2;
                  return (
                    <div
                      key={i}
                      className="p-2 border text-[11px]"
                      style={{ borderLeftColor: c, borderLeftWidth: 3 }}
                      data-testid={`pipeline-event-${i}`}
                    >
                      <div className="flex items-center gap-1.5">
                        <Icon size={11} style={{ color: c }} />
                        <span
                          className="mono uppercase font-bold text-[9px] tracking-wider"
                          style={{ color: c }}
                        >
                          {ev.severity}
                        </span>
                        <span className="mono text-[10px] text-muted-foreground">{ev.source}</span>
                      </div>
                      <div className="mt-0.5">{ev.message}</div>
                      {ev.data && (
                        <details className="mt-1">
                          <summary className="text-[9px] cursor-pointer text-muted-foreground">data</summary>
                          <pre className="text-[9px] mono bg-black/40 p-1 mt-0.5">{JSON.stringify(ev.data, null, 2)}</pre>
                        </details>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {result?.plugins_used && (
              <div className="text-[9px] mono text-muted-foreground mt-2 border-t border-border pt-2">
                <div>Detectors: {(result.plugins_used.detectors || []).join(", ") || "—"}</div>
                <div>Trackers: {(result.plugins_used.trackers || []).join(", ") || "—"}</div>
                <div>Business: {(result.plugins_used.business || []).join(", ") || "—"}</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
