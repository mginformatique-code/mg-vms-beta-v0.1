/**
 * SecurityCenter.jsx — v0.5.4-B
 *
 * Nouveau menu Administration → Centre de sécurité. Un seul appel à
 * `/api/security/score` renvoie un score global 0-100 + un détail par
 * critère (ok/ko, texte explicatif, conseil actionnable).
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  ShieldCheck, ShieldAlert, ShieldOff, RefreshCw, Info, CheckCircle2, XCircle,
  Lock, Users, Server, HardDrive, Camera, Zap, Database, Key, Cloud, LogOut,
} from "lucide-react";

const CRITERION_ICON = {
  https:            Lock,
  jwt_env:          Key,
  strong_passwords: Lock,
  mfa:              ShieldCheck,
  backups:          Cloud,
  plugin_sandbox:   Zap,
  camera_firmware:  Camera,
  mongo_auth:       Database,
  disk:             HardDrive,
  certs:            Server,
};

function ScoreRing({ score, grade }) {
  const color = score >= 90 ? "#00E676" : score >= 75 ? "#88CC00"
               : score >= 60 ? "#FFB800" : score >= 40 ? "#FF7043" : "#FF3333";
  const r = 74, c = 2 * Math.PI * r;
  const dash = c * (score / 100);
  return (
    <div className="relative w-48 h-48 flex items-center justify-center" data-testid="secc-score-ring">
      <svg width="192" height="192" className="rotate-[-90deg]">
        <circle cx="96" cy="96" r={r} stroke="currentColor" className="text-border" strokeWidth="12" fill="none" />
        <circle cx="96" cy="96" r={r} stroke={color} strokeWidth="12" fill="none"
          strokeDasharray={`${dash} ${c - dash}`} strokeLinecap="round"
          style={{ transition: "stroke-dasharray 800ms ease" }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-5xl font-head font-black tracking-tight mono" style={{ color }}>{score}</div>
        <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mt-1">
          Score / 100
        </div>
        <div className="mt-1 text-xl mono font-black" style={{ color }}>{grade}</div>
      </div>
    </div>
  );
}

function CheckRow({ id, item }) {
  const Icon = CRITERION_ICON[id] || Info;
  const ok = item.ok;
  return (
    <div className="border border-border p-3" data-testid={`secc-check-${id}`}>
      <div className="flex items-start gap-2">
        <Icon size={16} className={ok ? "text-[#00E676]" : "text-[#FF3333]"} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium flex items-center gap-2">
            {item.label}
            <span className="text-[10px] mono text-muted-foreground">
              +{item.weight}
            </span>
            {ok
              ? <CheckCircle2 size={13} className="text-[#00E676] ml-auto" />
              : <XCircle size={13} className="text-[#FF3333] ml-auto" />}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">{item.detail}</div>
          {!ok && item.advice && (
            <div className="text-xs text-[#FFB800] mt-1.5 flex items-start gap-1">
              <Info size={11} className="mt-0.5 shrink-0" />
              <span>{item.advice}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function SecurityCenter() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/security/score");
      setData(r.data);
    } catch (e) { toast.error("Impossible de charger le score sécurité"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  if (loading || !data) {
    return <div className="p-8 text-muted-foreground" data-testid="secc-loading">Analyse sécurité en cours…</div>;
  }
  const okCount = Object.values(data.checks).filter((v) => v.ok).length;
  const koCount = Object.keys(data.checks).length - okCount;

  return (
    <div className="p-4 space-y-4" data-testid="security-center">
      <div className="flex items-end justify-between border-b border-border pb-3">
        <div>
          <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-1">
            MG-VMS · Administration
          </div>
          <h1 className="font-head font-black text-3xl tracking-tight">Centre de sécurité</h1>
        </div>
        <button onClick={load} className="flex items-center gap-2 border border-border px-3 py-2 text-xs hover:bg-secondary/50" data-testid="secc-refresh">
          <RefreshCw size={13} /> Réévaluer
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-2">
        <div className="bg-card border border-border p-4 flex flex-col items-center justify-center">
          <ScoreRing score={data.score} grade={data.grade} />
          <div className="mt-3 flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1"><CheckCircle2 size={12} className="text-[#00E676]" /> {okCount} conformes</span>
            <span className="flex items-center gap-1"><XCircle size={12} className="text-[#FF3333]" /> {koCount} à corriger</span>
          </div>
        </div>
        <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
          {Object.entries(data.checks).map(([k, v]) => (
            <CheckRow key={k} id={k} item={v} />
          ))}
        </div>
      </div>

      <div className="bg-card border border-border p-4">
        <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-3 flex items-center gap-1">
          <ShieldAlert size={12} /> Actions rapides
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Link to="/settings" className="border border-border p-3 hover:border-[#0044FF] hover:bg-secondary/40 transition" data-testid="secc-action-sessions">
            <LogOut size={14} className="text-muted-foreground mb-1" />
            <div className="text-xs font-medium">Sessions actives</div>
            <div className="text-[10px] text-muted-foreground">Gérer & révoquer</div>
          </Link>
          <Link to="/users" className="border border-border p-3 hover:border-[#0044FF] hover:bg-secondary/40 transition" data-testid="secc-action-users">
            <Users size={14} className="text-muted-foreground mb-1" />
            <div className="text-xs font-medium">Utilisateurs</div>
            <div className="text-[10px] text-muted-foreground">Rôles & 2FA</div>
          </Link>
          <Link to="/audit" className="border border-border p-3 hover:border-[#0044FF] hover:bg-secondary/40 transition" data-testid="secc-action-audit">
            <Info size={14} className="text-muted-foreground mb-1" />
            <div className="text-xs font-medium">Journal d&apos;audit</div>
            <div className="text-[10px] text-muted-foreground">Événements tracés</div>
          </Link>
          <Link to="/cameras" className="border border-border p-3 hover:border-[#0044FF] hover:bg-secondary/40 transition" data-testid="secc-action-cams">
            <Camera size={14} className="text-muted-foreground mb-1" />
            <div className="text-xs font-medium">Caméras</div>
            <div className="text-[10px] text-muted-foreground">Firmware & mots de passe</div>
          </Link>
        </div>
      </div>
    </div>
  );
}
