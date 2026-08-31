/**
 * OpenSourceLicenses — Composants tiers utilisés par MG-VMS.
 *
 * Les licences listées ici ont été relevées sur les paquets RÉELLEMENT
 * installés dans l'image de production (métadonnées `importlib.metadata`
 * côté Python, `--version` côté conteneurs), et non recopiées de mémoire.
 * Les versions correspondent à celles épinglées dans `backend/requirements*.txt`
 * et aux images déclarées dans `deploy-app/docker-compose.yml`.
 *
 * ⚠ À tenir à jour lors d'une montée de version d'un de ces composants —
 * une licence peut changer d'une version à l'autre (cas déjà vu : Ultralytics
 * passé en AGPL-3.0, MongoDB passé en SSPL).
 */
import React, { useState } from "react";
import { Boxes, ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

const GROUPS = [
  {
    key: "infra",
    label: { fr: "Infrastructure vidéo", en: "Video infrastructure" },
    items: [
      { name: "go2rtc", version: "1.9.9", license: "MIT", url: "https://github.com/AlexxIT/go2rtc" },
      { name: "FFmpeg", version: "4.4.2", license: "LGPL-2.1+ / GPL-2+", url: "https://ffmpeg.org" },
      { name: "MongoDB", version: "7.0", license: "SSPL-1.0", url: "https://www.mongodb.com" },
      { name: "aiortc", version: "1.9.0", license: "BSD-3-Clause", url: "https://github.com/aiortc/aiortc" },
      { name: "PyAV", version: "12.3.0", license: "BSD", url: "https://github.com/PyAV-Org/PyAV" },
    ],
  },
  {
    key: "backend",
    label: { fr: "Serveur applicatif", en: "Application server" },
    items: [
      { name: "FastAPI", version: "0.110.0", license: "MIT", url: "https://fastapi.tiangolo.com" },
      { name: "Starlette", version: "0.36.3", license: "BSD", url: "https://www.starlette.io" },
      { name: "Uvicorn", version: "0.25.0", license: "BSD", url: "https://www.uvicorn.org" },
      { name: "Pydantic", version: "2.9.2", license: "MIT", url: "https://docs.pydantic.dev" },
      { name: "Motor / PyMongo", version: "3.5.1 / 4.8.0", license: "Apache-2.0", url: "https://www.mongodb.com/docs/drivers/motor/" },
      { name: "httpx", version: "0.27.2", license: "BSD", url: "https://www.python-httpx.org" },
      { name: "aiohttp", version: "3.10.5", license: "Apache-2.0", url: "https://docs.aiohttp.org" },
      { name: "cryptography", version: "43.0.1", license: "Apache-2.0 / BSD-3-Clause", url: "https://cryptography.io" },
      { name: "passlib", version: "1.7.4", license: "BSD", url: "https://passlib.readthedocs.io" },
      { name: "python-jose", version: "3.3.0", license: "MIT", url: "https://github.com/mpdavis/python-jose" },
    ],
  },
  {
    key: "cameras",
    label: { fr: "Pilotes caméras", en: "Camera drivers" },
    items: [
      { name: "reolink-aio", version: "0.21.10", license: "MIT", url: "https://github.com/starkillerOG/reolink_aio" },
      { name: "onvif-zeep", version: "0.2.12", license: "MIT", url: "https://github.com/FalkTannhaeuser/python-onvif-zeep" },
    ],
  },
  {
    key: "ai",
    label: { fr: "Intelligence artificielle", en: "Artificial intelligence" },
    items: [
      { name: "Ultralytics (YOLO)", version: "8.3.0", license: "AGPL-3.0", url: "https://github.com/ultralytics/ultralytics", strong: true },
      { name: "PyTorch", version: "2.4.1", license: "BSD-3-Clause", url: "https://pytorch.org" },
      { name: "torchvision", version: "0.19.1", license: "BSD", url: "https://pytorch.org/vision" },
      { name: "ONNX Runtime (GPU)", version: "1.19.2", license: "MIT", url: "https://onnxruntime.ai" },
      { name: "OpenCV", version: "4.10.0", license: "Apache-2.0", url: "https://opencv.org" },
      { name: "NumPy", version: "1.26.4", license: "BSD", url: "https://numpy.org" },
      { name: "Pillow", version: "10.4.0", license: "HPND", url: "https://python-pillow.org" },
      { name: "supervision", version: "0.23.0", license: "MIT", url: "https://github.com/roboflow/supervision" },
      { name: "fast-alpr", version: "0.1.1", license: "MIT", url: "https://github.com/ankandrew/fast-alpr" },
      { name: "EasyOCR", version: "1.7.2", license: "Apache-2.0", url: "https://github.com/JaidedAI/EasyOCR" },
      { name: "PaddleOCR", version: "3.7.0", license: "Apache-2.0", url: "https://github.com/PaddlePaddle/PaddleOCR" },
      { name: "InsightFace", version: "1.0.1", license: "— non déclarée par le paquet", url: "https://github.com/deepinsight/insightface" },
      // v3.20 · Modèle auto-hébergé (Admin → LLM), pas un paquet pip local —
      // pas de métadonnées importlib.metadata à relever ici comme pour le
      // reste de cette liste. Version réellement configurée sur ce serveur
      // (routes/llm_settings.py) : qwen3:1.7b. Licence Apache-2.0, publiée
      // par Alibaba/Qwen Team pour toute la série Qwen3.
      { name: "Qwen3 (LLM)", version: "1.7b", license: "Apache-2.0", url: "https://github.com/QwenLM/Qwen3" },
    ],
  },
  {
    key: "system",
    label: { fr: "Système hôte", en: "Host system" },
    items: [
      // v3.20 · Serveur NTP embarqué (Date et heure → Serveur de temps) —
      // paquet Debian réellement installé sur l'hôte (dpkg -l), pas une image
      // conteneur.
      { name: "chrony", version: "4.6.1", license: "GPL-2.0", url: "https://chrony-project.org" },
    ],
  },
  {
    key: "frontend",
    label: { fr: "Interface web", en: "Web interface" },
    items: [
      { name: "React", version: "19", license: "MIT", url: "https://react.dev" },
      { name: "Tailwind CSS", version: "3.4", license: "MIT", url: "https://tailwindcss.com" },
      { name: "Radix UI", version: "1.x", license: "MIT", url: "https://www.radix-ui.com" },
      { name: "lucide-react", version: "0.x", license: "ISC", url: "https://lucide.dev" },
      { name: "Recharts", version: "3.x", license: "MIT", url: "https://recharts.org" },
      { name: "axios", version: "1.x", license: "MIT", url: "https://axios-http.com" },
    ],
  },
];

export default function OpenSourceLicenses({ t, lang = "fr" }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const L = (o) => (lang === "en" ? o.en : o.fr);

  return (
    <div className="border border-border p-3" data-testid="oss-licenses-section">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground hover:text-foreground"
        data-testid="oss-licenses-toggle"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Boxes size={14} /> {t("oss.title")}
      </button>

      {open && (
        <div className="mt-3 space-y-2">
          <p className="text-[11px] text-muted-foreground leading-relaxed">
            {t("oss.intro")}
          </p>

          {GROUPS.map((g) => (
            <div key={g.key} className="border border-border">
              <button
                type="button"
                onClick={() => setExpanded((e) => (e === g.key ? null : g.key))}
                className="w-full flex items-center justify-between px-2.5 py-1.5 text-xs hover:bg-secondary/50"
                data-testid={`oss-group-${g.key}`}
              >
                <span className="flex items-center gap-1.5">
                  {expanded === g.key ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  {L(g.label)}
                </span>
                <span className="text-[10px] text-muted-foreground mono">{g.items.length}</span>
              </button>
              {expanded === g.key && (
                <div className="divide-y divide-border border-t border-border">
                  {g.items.map((it) => (
                    <div key={it.name} className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-[11px]">
                      <a
                        href={it.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-[#0044FF] hover:underline truncate"
                      >
                        {it.name} <ExternalLink size={10} className="shrink-0" />
                      </a>
                      <span className="flex items-center gap-2 shrink-0">
                        <span className="mono text-muted-foreground">{it.version}</span>
                        <span
                          className={`mono px-1.5 py-0.5 border ${
                            it.strong
                              ? "border-[#FFAA00] text-[#FFAA00]"
                              : "border-border text-muted-foreground"
                          }`}
                        >
                          {it.license}
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}

          {/* Signalé explicitement : Ultralytics (YOLO) est sous AGPL-3.0, une
              licence copyleft forte dont les obligations diffèrent nettement
              des MIT/BSD/Apache du reste de la liste. Mieux vaut que ce soit
              visible ici que découvert tardivement. */}
          <p className="text-[11px] leading-relaxed border-l-2 border-[#FFAA00] pl-2 text-muted-foreground">
            {t("oss.agpl_notice")}
          </p>
        </div>
      )}
    </div>
  );
}
