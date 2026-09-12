import React, { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/api";
import { ChevronLeft, ChevronRight, Loader2, Cctv, Film, Monitor, PlaySquare, Check } from "lucide-react";
import { useApp } from "@/context/AppContext";

/**
 * v3.74 · Assistant d'export vidéo multi-étapes (gros chantier "Export
 * vidéo professionnel & écosystème MG-VMS Player").
 *
 * Remplace l'ancien export mono-caméra immédiat de Recordings.jsx par un
 * assistant à 4 étapes : caméras+période → format/codec → système cible
 * → inclusion du lecteur autonome MG-VMS Player. La logique de sélection
 * de plage horaire (timeline) reste dans Recordings.jsx, inchangée —
 * seul ce qui suit "cliquer Exporter" est ici.
 */

const OS_OPTIONS = [
  { id: "any", labelKey: "expwiz.os_any" },
  { id: "windows", label: "Windows" },
  { id: "macos", label: "macOS" },
  { id: "linux", label: "Linux" },
];

export default function ExportWizard({ open, onClose, cams, primaryCameraId, start, end, durationLabel, onExported }) {
  const { t } = useApp();
  const STEPS = [t("expwiz.step_cameras_period"), t("expwiz.step_format"), t("expwiz.step_target_os"), t("expwiz.step_player")];
  const [step, setStep] = useState(0);
  const [selectedCams, setSelectedCams] = useState(() => new Set(primaryCameraId ? [primaryCameraId] : []));
  const [format, setFormat] = useState("zip");
  const [codec, setCodec] = useState("h264");
  const [targetOs, setTargetOs] = useState("any");
  const [includePlayer, setIncludePlayer] = useState(true);
  const [creating, setCreating] = useState(false);

  if (!open) return null;

  const multi = selectedCams.size > 1;
  const toggleCam = (id) => setSelectedCams((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const canNext = () => {
    if (step === 0) return selectedCams.size > 0;
    return true;
  };

  const reset = () => { setStep(0); setCreating(false); };
  const close = () => { reset(); onClose(); };

  const submit = async () => {
    setCreating(true);
    try {
      const { data } = await api.post("/recordings/export", {
        camera_ids: Array.from(selectedCams), start, end,
        format: multi ? "zip" : format, codec, target_os: targetOs,
        include_player: format === "zip" ? includePlayer : false,
      });
      toast.success(data.message || t("expwiz.export_created"));
      onExported?.(data);
      close();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || t("expwiz.export_failed"));
    } finally { setCreating(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="rounded-none border-border max-w-lg" data-testid="export-wizard">
        <DialogHeader>
          <DialogTitle className="font-head flex items-center gap-2"><Film size={16} /> {t("expwiz.dialog_title")} — {t("expwiz.step_label")} {step + 1}/4</DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-1 mb-3">
          {STEPS.map((s, i) => (
            <div key={s} className={`flex-1 h-1 ${i <= step ? "bg-[#0044FF]" : "bg-border"}`} />
          ))}
        </div>
        <div className="text-xs text-muted-foreground mb-3">{durationLabel}</div>

        {step === 0 && (
          <div className="space-y-1.5 max-h-72 overflow-y-auto" data-testid="export-wizard-cameras">
            {cams.map((c) => (
              <label key={c.id} className={`flex items-center gap-2 p-2 border cursor-pointer ${selectedCams.has(c.id) ? "border-[#0044FF] bg-[#0044FF]/5" : "border-border"}`}>
                <input type="checkbox" checked={selectedCams.has(c.id)} onChange={() => toggleCam(c.id)} />
                <Cctv size={14} className="text-muted-foreground" />
                <span className="text-sm flex-1 truncate">{c.name}</span>
                <span className="text-[10px] text-muted-foreground">{c.site_name}</span>
              </label>
            ))}
            {selectedCams.size > 1 && (
              <p className="text-[11px] text-[#FFB800] pt-1">{t("expwiz.multi_cam_notice")}</p>
            )}
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3">
            {!multi && (
              <div>
                <label className="text-xs uppercase tracking-wider text-muted-foreground">{t("expwiz.format_label")}</label>
                <div className="flex gap-2 mt-1">
                  {[["zip", t("expwiz.format_zip")], ["mp4", t("expwiz.format_mp4")]].map(([v, l]) => (
                    <button key={v} onClick={() => setFormat(v)}
                      className={`flex-1 px-3 py-2 text-xs border ${format === v ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF]" : "border-border"}`}>
                      {l}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div>
              <label className="text-xs uppercase tracking-wider text-muted-foreground">{t("expwiz.codec_label")}</label>
              <div className="flex gap-2 mt-1">
                {[["h264", t("expwiz.codec_h264")], ["h265", t("expwiz.codec_h265")]].map(([v, l]) => (
                  <button key={v} onClick={() => setCodec(v)}
                    className={`flex-1 px-3 py-2 text-xs border ${codec === v ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF]" : "border-border"}`}>
                    {l}
                  </button>
                ))}
              </div>
              {codec === "h265" && <p className="text-[11px] text-muted-foreground mt-1">{t("expwiz.h265_notice")}</p>}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-2" data-testid="export-wizard-os">
            <label className="text-xs uppercase tracking-wider text-muted-foreground">{t("expwiz.target_os_label")}</label>
            <div className="grid grid-cols-2 gap-2 mt-1">
              {OS_OPTIONS.map((o) => (
                <button key={o.id} onClick={() => setTargetOs(o.id)}
                  className={`flex items-center gap-2 px-3 py-2 text-xs border ${targetOs === o.id ? "border-[#0044FF] bg-[#0044FF]/10 text-[#0044FF]" : "border-border"}`}>
                  <Monitor size={13} /> {o.labelKey ? t(o.labelKey) : o.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3" data-testid="export-wizard-player">
            {(multi ? true : format === "zip") ? (
              <>
                <label className="flex items-center gap-2 p-3 border border-border cursor-pointer">
                  <input type="checkbox" checked={includePlayer} onChange={(e) => setIncludePlayer(e.target.checked)} />
                  <PlaySquare size={16} className="text-muted-foreground" />
                  <div>
                    <div className="text-sm font-medium">{t("expwiz.include_player")}</div>
                    <div className="text-[11px] text-muted-foreground">{t("expwiz.include_player_desc")}</div>
                  </div>
                </label>
              </>
            ) : (
              <p className="text-xs text-muted-foreground">{t("expwiz.player_zip_only")}</p>
            )}
            <div className="border border-border p-3 text-xs space-y-1">
              <div className="flex items-center gap-2"><Check size={13} className="text-[#00E676]" /> {selectedCams.size} {t("expwiz.summary_cameras")}</div>
              <div className="flex items-center gap-2"><Check size={13} className="text-[#00E676]" /> {multi ? "ZIP" : format.toUpperCase()} · {codec.toUpperCase()}</div>
              <div className="flex items-center gap-2"><Check size={13} className="text-[#00E676]" /> {OS_OPTIONS.find((o) => o.id === targetOs)?.labelKey ? t(OS_OPTIONS.find((o) => o.id === targetOs).labelKey) : OS_OPTIONS.find((o) => o.id === targetOs)?.label}</div>
            </div>
          </div>
        )}

        <div className="flex justify-between pt-3">
          <button onClick={() => step === 0 ? close() : setStep((s) => s - 1)}
            className="flex items-center gap-1 px-3 py-1.5 text-xs border border-border hover:bg-secondary">
            <ChevronLeft size={13} /> {step === 0 ? t("expwiz.cancel") : t("expwiz.previous")}
          </button>
          {step < 3 ? (
            <button onClick={() => canNext() && setStep((s) => s + 1)} disabled={!canNext()}
              className="flex items-center gap-1 px-3 py-1.5 text-xs bg-[#0044FF] text-white disabled:opacity-40">
              {t("expwiz.next")} <ChevronRight size={13} />
            </button>
          ) : (
            <button onClick={submit} disabled={creating} data-testid="export-wizard-create"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-[#0044FF] text-white disabled:opacity-50">
              {creating && <Loader2 size={13} className="animate-spin" />} {t("expwiz.create_export")}
            </button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
