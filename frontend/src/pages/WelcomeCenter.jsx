/**
 * WelcomeCenter.jsx — v0.5.1.a
 *
 * L'écran d'accueil officiel de MG-VMS. Chargé sur la route "/", il est la
 * porte d'entrée vers les 8 Centers (Camera, Pipeline, Plugin, Operations,
 * Event, Recording, Settings, Dashboard).
 *
 * Contenu :
 *   - Health score global (0-100) + statut par composant
 *   - Version installée + build + changelog "nouveautés depuis la dernière
 *     version consultée"
 *   - Alertes système auto-déduites (disque, mongo, GPU, go2rtc, plugins)
 *   - Actualités administrateur (collection welcome_news)
 *   - Stats express (caméras, événements, plaques, plugins)
 *   - Conseils contextuels
 *   - Documentation & liens externes
 *   - Préférences utilisateur (masquer pour cette version, importantes only)
 *
 * Un seul appel `/api/welcome/summary` charge tout, < 200 ms côté serveur.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApp } from "@/context/AppContext";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  Activity, AlertTriangle, ArrowRight, Bell, BookOpen, Bug, Camera as CamIcon,
  CheckCircle2, ChevronDown, ChevronUp, Cpu, Database, Github, HardDrive,
  Layers, Lightbulb, LifeBuoy, MemoryStick, Monitor, Newspaper, Package,
  PenSquare, Pin, PinOff, Puzzle, ScanLine, Server, Settings, Sparkles,
  Sparkle, Trash2, Wifi, Zap, PlayCircle, Link2, StickyNote, PlusCircle,
} from "lucide-react";

// ─────────────────────────────────────────────────────────────────────
// Constantes UI
// ─────────────────────────────────────────────────────────────────────
const STATUS_COLOR = {
  ok: "#00E676",
  warn: "#FFB800",
  crit: "#FF3333",
};
const SEVERITY_COLOR = {
  info: "#0044FF",
  warning: "#FFB800",
  critical: "#FF3333",
};

const COMPONENT_META = {
  gpu:      { icon: Zap,          label: "GPU / CUDA" },
  mongo:    { icon: Database,     label: "MongoDB" },
  pipeline: { icon: Layers,       label: "Pipeline IA" },
  go2rtc:   { icon: Monitor,      label: "go2rtc" },
  disk:     { icon: HardDrive,    label: "Stockage" },
  cpu:      { icon: Cpu,          label: "CPU" },
  ram:      { icon: MemoryStick,  label: "RAM" },
  cameras:  { icon: CamIcon,      label: "Caméras" },
  plugins:  { icon: Puzzle,       label: "Plugins" },
};

const CENTERS = [
  { to: "/live",             label: "Live",             icon: Monitor, desc: "Mosaïque temps réel des caméras" },
  { to: "/cameras",          label: "Camera Center",    icon: CamIcon, desc: "Découverte, config et probe capacités" },
  { to: "/pipeline-center",  label: "Pipeline Center",  icon: Layers,  desc: "Graphe IA, FPS et diagnostic par caméra" },
  { to: "/plugins",          label: "Plugin Center",    icon: Puzzle,  desc: "Marketplace, runtime & logs des plugins" },
  { to: "/events",           label: "Event Center",     icon: Bell,    desc: "Événements ANPR / IA / alarmes" },
  { to: "/recordings",       label: "Recording Center", icon: Activity,desc: "Enregistrements et timeline vidéo" },
  { to: "/dashboard",        label: "Dashboard",        icon: Server,  desc: "KPIs et graphes agrégés" },
  { to: "/settings",         label: "Settings Center",  icon: Settings,desc: "Utilisateurs, réseau, backups et 2FA" },
];

// v3.1.2 · Les 4 liens pointaient vers des URLs factices (mg-vms.local
// n'existe pas, github.com/mg-vms n'est pas le vrai dépôt) — jamais
// vérifiées après leur ajout initial. Support renvoie vers le site public
// (/contact sert de page support réelle).
// v3.7.3 · "Documentation" pointe désormais vers le wiki dédié
// (docs.mg-vms.com, 32 pages FR+EN en lecture publique) et non plus vers
// la page d'accueil commerciale du site, qui ne documente rien.
const DOC_LINKS = [
  { label: "Documentation",  href: "https://docs.mg-vms.com",                                      icon: BookOpen },
  { label: "GitHub",         href: "https://github.com/mginformatique-code/mg-vms-beta-v0.1",       icon: Github },
  { label: "Changelog",      href: "#changelog",                                                    icon: Newspaper, internal: true },
  { label: "Support",        href: "https://mg-vms.com/fr/contact",                                 icon: LifeBuoy },
];

// ─────────────────────────────────────────────────────────────────────
// Composants basiques
// ─────────────────────────────────────────────────────────────────────

function StatusDot({ status }) {
  const color = STATUS_COLOR[status] || STATUS_COLOR.ok;
  return (
    <span
      className="inline-block w-2 h-2 rounded-full shrink-0"
      style={{ background: color, boxShadow: `0 0 8px ${color}` }}
    />
  );
}

function ScoreRing({ score }) {
  const color = score >= 85 ? STATUS_COLOR.ok : score >= 60 ? STATUS_COLOR.warn : STATUS_COLOR.crit;
  const r = 62;
  const c = 2 * Math.PI * r;
  const dash = c * (score / 100);
  return (
    <div className="relative w-40 h-40 flex items-center justify-center" data-testid="welcome-health-ring">
      <svg width="160" height="160" className="rotate-[-90deg]">
        <circle cx="80" cy="80" r={r} stroke="currentColor" className="text-border" strokeWidth="10" fill="none" />
        <circle
          cx="80" cy="80" r={r}
          stroke={color}
          strokeWidth="10"
          fill="none"
          strokeDasharray={`${dash} ${c - dash}`}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 800ms ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-4xl font-head font-black tracking-tight mono" style={{ color }}>
          {score}
        </div>
        <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mt-1">
          / 100
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, accent, testId }) {
  return (
    <div className="bg-card border border-border p-3" data-testid={testId}>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1.5">{label}</div>
          <div className="font-head font-black text-2xl tracking-tight mono" style={{ color: accent }}>
            {value ?? "—"}
          </div>
        </div>
        <Icon size={18} strokeWidth={1.5} style={{ color: accent }} className="opacity-70" />
      </div>
    </div>
  );
}

function SectionHeader({ icon: Icon, title, right }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <Icon size={16} strokeWidth={1.5} className="text-muted-foreground" />
        <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground">{title}</div>
      </div>
      {right}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Sections
// ─────────────────────────────────────────────────────────────────────

function HealthSection({ health, version }) {
  const components = health?.components || {};
  const rows = Object.entries(components).map(([k, v]) => ({
    key: k,
    meta: COMPONENT_META[k] || { icon: Activity, label: k },
    status: v.status,
    score: v.score,
  }));

  return (
    <div className="bg-card border border-border p-4 lg:col-span-2" data-testid="welcome-health">
      <SectionHeader
        icon={Activity}
        title="Santé système"
        right={
          <div className="text-[10px] mono text-muted-foreground">
            MG-VMS <span className="text-foreground">{version?.installed || "—"}</span>
          </div>
        }
      />
      <div className="flex flex-col md:flex-row items-center gap-6">
        <ScoreRing score={health?.score ?? 0} />
        <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 w-full">
          {rows.map((r) => {
            const Icon = r.meta.icon;
            return (
              <div key={r.key} className="flex items-center gap-2 py-1" data-testid={`welcome-health-${r.key}`}>
                <StatusDot status={r.status} />
                <Icon size={14} strokeWidth={1.5} className="text-muted-foreground" />
                <span className="text-xs flex-1">{r.meta.label}</span>
                <span className="text-xs mono text-muted-foreground">{r.score}%</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function VersionSection({ version, hasNewVersion, onOpenChangelog }) {
  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-version">
      <SectionHeader icon={Package} title="Version" />
      <div className="text-3xl font-head font-black tracking-tight mono mb-1">
        {version?.installed || "—"}
      </div>
      <div className="text-xs text-muted-foreground mb-4">
        {version?.build_date ? `Build ${version.build_date}` : "Build inconnu"}
      </div>
      {hasNewVersion ? (
        <div className="flex items-center gap-2 border border-[#0044FF]/40 bg-[#0044FF]/10 p-2 mb-2">
          <Sparkles size={14} className="text-[#0044FF]" />
          <span className="text-xs flex-1">Nouveautés disponibles depuis votre dernière visite.</span>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
          <CheckCircle2 size={14} className="text-[#00E676]" />
          À jour · dernière version connue
        </div>
      )}
      <button
        onClick={onOpenChangelog}
        className="w-full text-xs uppercase tracking-[0.15em] text-[#0044FF] hover:bg-secondary/50 border border-border py-2 transition flex items-center justify-center gap-2"
        data-testid="welcome-version-changelog-btn"
      >
        Voir le changelog <ArrowRight size={12} />
      </button>
    </div>
  );
}

function AlertsSection({ alerts }) {
  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-alerts">
      <SectionHeader
        icon={AlertTriangle}
        title="Alertes système"
        right={<span className="text-xs mono text-muted-foreground">{alerts.length}</span>}
      />
      {alerts.length === 0 ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-3">
          <CheckCircle2 size={14} className="text-[#00E676]" />
          Aucune alerte système en cours.
        </div>
      ) : (
        <div className="divide-y divide-border">
          {alerts.map((a) => (
            <div key={a.id} className="py-2.5 flex items-start gap-2" data-testid={`welcome-alert-${a.id}`}>
              <span
                className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0"
                style={{ background: SEVERITY_COLOR[a.severity] || "#71717a" }}
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{a.title}</div>
                <div className="text-xs text-muted-foreground">{a.message}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatsSection({ stats }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2" data-testid="welcome-stats">
      <StatCard testId="welcome-stat-cameras" icon={CamIcon} label="Caméras en ligne" accent="#00E676" value={`${stats?.cameras_online ?? 0}/${stats?.cameras_total ?? 0}`} />
      <StatCard testId="welcome-stat-events" icon={Zap} label="Événements 24h" accent="#0044FF" value={stats?.events_today ?? 0} />
      <StatCard testId="welcome-stat-plates" icon={ScanLine} label="Plaques 24h" value={stats?.plates_today ?? 0} />
      <StatCard testId="welcome-stat-alerts" icon={Bell} label="Alertes actives" accent="#FFB800" value={stats?.alerts_active ?? 0} />
    </div>
  );
}

function TipsSection({ tips, t }) {
  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-tips">
      <SectionHeader icon={Lightbulb} title={t("welcome.tips")} />
      <ul className="space-y-2">
        {tips.map((tip, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground" data-testid={`welcome-tip-${i}`}>
            <Sparkle size={12} className="text-[#0044FF] mt-0.5 shrink-0" />
            <span>{tip}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// v0.5.3 · Tutoriels vidéo YouTube (admin CRUD)
// ─────────────────────────────────────────────────────────────────────
function TutorialsSection({ tutorials, isAdmin, onCreate, onDelete, t }) {
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: "", url: "", description: "" });
  const submit = async () => {
    if (!form.title.trim() || !form.url.trim()) { toast.error("Titre + URL requis"); return; }
    await onCreate(form);
    setForm({ title: "", url: "", description: "" });
    setCreating(false);
  };
  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-tutorials">
      <SectionHeader
        icon={PlayCircle}
        title={t("welcome.tutorials")}
        right={isAdmin && (
          <button
            onClick={() => setCreating((v) => !v)}
            className="text-xs text-[#0044FF] hover:underline flex items-center gap-1"
            data-testid="welcome-tut-create-btn"
          >
            <PlusCircle size={12} /> {creating ? t("common.cancel") : t("welcome.add_tutorial")}
          </button>
        )}
      />
      {creating && (
        <div className="mb-3 border border-border p-2 space-y-2" data-testid="welcome-tut-form">
          <input className="w-full bg-background border border-border px-2 py-1.5 text-sm"
            placeholder={t("welcome.tut_title")}
            value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
            data-testid="welcome-tut-title" />
          <input className="w-full bg-background border border-border px-2 py-1.5 text-sm mono"
            placeholder="https://youtu.be/..."
            value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })}
            data-testid="welcome-tut-url" />
          <textarea className="w-full bg-background border border-border px-2 py-1.5 text-sm min-h-[50px]"
            placeholder={t("welcome.tut_desc")}
            value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
            data-testid="welcome-tut-desc" />
          <button onClick={submit}
            className="w-full bg-[#0044FF] text-white px-3 py-1 text-xs uppercase tracking-wider"
            data-testid="welcome-tut-submit">
            {t("welcome.publish")}
          </button>
        </div>
      )}
      {tutorials.length === 0 ? (
        <div className="text-xs text-muted-foreground py-2">{t("welcome.no_tutorial")}</div>
      ) : (
        <div className="space-y-2 max-h-72 overflow-y-auto">
          {tutorials.map((tt) => (
            <div key={tt.id} className="flex gap-2 group" data-testid={`welcome-tut-${tt.id}`}>
              <a href={tt.url} target="_blank" rel="noopener noreferrer"
                className="relative w-24 aspect-video shrink-0 bg-black overflow-hidden border border-border">
                {tt.thumbnail ? (
                  <img src={tt.thumbnail} alt={tt.title} className="w-full h-full object-cover opacity-90 group-hover:opacity-100" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center"><PlayCircle size={20} /></div>
                )}
                <PlayCircle size={16} className="absolute inset-0 m-auto text-white opacity-80" />
              </a>
              <div className="flex-1 min-w-0">
                <a href={tt.url} target="_blank" rel="noopener noreferrer"
                  className="text-xs font-medium hover:text-[#0044FF] truncate block">{tt.title}</a>
                <div className="text-[10px] text-muted-foreground line-clamp-2">{tt.description}</div>
              </div>
              {isAdmin && (
                <button onClick={() => onDelete(tt.id)}
                  className="opacity-0 group-hover:opacity-100 text-[#FF3333]" title="Supprimer">
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// v0.5.3 · Widgets custom (notes libres + liens rapides) — style pfSense
// ─────────────────────────────────────────────────────────────────────
function WidgetsSection({ widgets, isAdmin, onCreate, onDelete, t }) {
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ type: "note", title: "", body: "", items: "" });
  const submit = async () => {
    if (!form.title.trim()) { toast.error(t("welcome.widget_title_required")); return; }
    let items = null;
    if (form.type === "links") {
      items = form.items.split("\n").map((l) => {
        const [label, url] = l.split("|").map((s) => (s || "").trim());
        return label && url ? { label, url } : null;
      }).filter(Boolean);
    }
    await onCreate({
      type: form.type, title: form.title.trim(),
      body: form.type === "note" ? form.body : "",
      items,
      order: 0,
    });
    setForm({ type: "note", title: "", body: "", items: "" });
    setCreating(false);
  };
  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-widgets">
      <SectionHeader
        icon={Layers}
        title={t("welcome.widgets")}
        right={isAdmin && (
          <button
            onClick={() => setCreating((v) => !v)}
            className="text-xs text-[#0044FF] hover:underline flex items-center gap-1"
            data-testid="welcome-widget-create-btn"
          >
            <PlusCircle size={12} /> {creating ? t("common.cancel") : t("welcome.add_widget")}
          </button>
        )}
      />
      {creating && (
        <div className="mb-3 border border-border p-2 space-y-2" data-testid="welcome-widget-form">
          <div className="flex gap-2">
            <label className="text-xs flex items-center gap-1 cursor-pointer">
              <input type="radio" name="wtype" value="note"
                checked={form.type === "note"} onChange={() => setForm({ ...form, type: "note" })} />
              {t("welcome.widget_note")}
            </label>
            <label className="text-xs flex items-center gap-1 cursor-pointer">
              <input type="radio" name="wtype" value="links"
                checked={form.type === "links"} onChange={() => setForm({ ...form, type: "links" })} />
              {t("welcome.widget_links")}
            </label>
          </div>
          <input className="w-full bg-background border border-border px-2 py-1.5 text-sm"
            placeholder={t("welcome.widget_title")} value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} />
          {form.type === "note" ? (
            <textarea className="w-full bg-background border border-border px-2 py-1.5 text-sm min-h-[60px]"
              placeholder={t("welcome.widget_body")} value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })} />
          ) : (
            <textarea className="w-full bg-background border border-border px-2 py-1.5 text-xs mono min-h-[60px]"
              placeholder="Label | https://…\nAutre lien | https://…"
              value={form.items}
              onChange={(e) => setForm({ ...form, items: e.target.value })} />
          )}
          <button onClick={submit}
            className="w-full bg-[#0044FF] text-white px-3 py-1 text-xs uppercase tracking-wider">
            {t("welcome.publish")}
          </button>
        </div>
      )}
      {widgets.length === 0 && !creating ? (
        <div className="text-xs text-muted-foreground py-2">{t("welcome.no_widget")}</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {widgets.map((w) => (
            <div key={w.id} className="border border-border p-3 group relative" data-testid={`welcome-widget-${w.id}`}>
              <div className="flex items-center gap-1.5 mb-1.5">
                {w.type === "links" ? <Link2 size={12} className="text-[#0044FF]" />
                                      : <StickyNote size={12} className="text-[#FFB800]" />}
                <span className="text-xs font-medium flex-1 truncate">{w.title}</span>
                {isAdmin && (
                  <button onClick={() => onDelete(w.id)}
                    className="opacity-0 group-hover:opacity-100 text-[#FF3333]" title="Supprimer">
                    <Trash2 size={11} />
                  </button>
                )}
              </div>
              {w.type === "note" ? (
                <p className="text-xs text-muted-foreground whitespace-pre-wrap">{w.body}</p>
              ) : (
                <ul className="space-y-1">
                  {(w.items || []).map((it, i) => (
                    <li key={i}>
                      <a href={it.url} target="_blank" rel="noopener noreferrer"
                        className="text-xs text-[#0044FF] hover:underline flex items-center gap-1">
                        <ArrowRight size={10} /> {it.label}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ChangelogSection({ changelog, expanded, onToggle }) {
  // v1.0-rc4.5 · Priorité aux nouveautés depuis last_seen_version, sinon
  // fallback sur les 5 dernières entrées (historique récent) pour ne
  // jamais afficher une section vide alors que CHANGELOG.md est peuplé.
  const newEntries = changelog?.new_since_last_seen || [];
  const recentEntries = changelog?.recent || [];
  const entries = newEntries.length > 0 ? newEntries : recentEntries;
  const sectionTitle = newEntries.length > 0 ? "Nouveautés" : "Historique récent";
  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-changelog" id="changelog">
      <SectionHeader
        icon={Sparkles}
        title={sectionTitle}
        right={
          <button
            onClick={onToggle}
            className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            data-testid="welcome-changelog-toggle"
          >
            {expanded ? "Réduire" : "Voir tout"} {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        }
      />
      {entries.length === 0 ? (
        <div className="text-xs text-muted-foreground py-2">Aucune entrée dans le changelog.</div>
      ) : (
        <div className="space-y-3">
          {(expanded ? entries : entries.slice(0, 3)).map((e) => (
            <div key={e.version} className="border-l-2 border-[#0044FF] pl-3" data-testid={`welcome-changelog-${e.version}`}>
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-head font-bold tracking-tight mono">{e.version}</span>
                {e.date && <span className="text-[10px] mono text-muted-foreground">{e.date}</span>}
              </div>
              {e.title && <div className="text-xs text-muted-foreground mt-0.5">{e.title}</div>}
              {expanded && e.body && (
                <pre className="text-[11px] mono text-muted-foreground whitespace-pre-wrap mt-2 max-h-40 overflow-y-auto">
                  {e.body}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NewsSection({ news, isAdmin, onCreate, onDelete }) {
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: "", body: "", severity: "info", pinned: false });

  const submit = async () => {
    if (!form.title.trim() || !form.body.trim()) {
      toast.error("Titre et contenu obligatoires");
      return;
    }
    await onCreate(form);
    setForm({ title: "", body: "", severity: "info", pinned: false });
    setCreating(false);
  };

  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-news">
      <SectionHeader
        icon={Newspaper}
        title="Actualités"
        right={
          isAdmin && (
            <button
              onClick={() => setCreating((v) => !v)}
              className="text-xs text-[#0044FF] hover:underline flex items-center gap-1"
              data-testid="welcome-news-create-btn"
            >
              <PenSquare size={12} /> {creating ? "Annuler" : "Publier"}
            </button>
          )
        }
      />
      {creating && (
        <div className="mb-3 border border-border p-2 space-y-2" data-testid="welcome-news-form">
          <input
            className="w-full bg-background border border-border px-2 py-1.5 text-sm"
            placeholder="Titre"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            data-testid="welcome-news-title"
          />
          <textarea
            className="w-full bg-background border border-border px-2 py-1.5 text-sm min-h-[80px]"
            placeholder="Contenu"
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
            data-testid="welcome-news-body"
          />
          <div className="flex items-center gap-2">
            <select
              className="bg-background border border-border px-2 py-1 text-xs"
              value={form.severity}
              onChange={(e) => setForm({ ...form, severity: e.target.value })}
              data-testid="welcome-news-severity"
            >
              <option value="info">Info</option>
              <option value="warning">Attention</option>
              <option value="critical">Critique</option>
            </select>
            <label className="text-xs flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                checked={form.pinned}
                onChange={(e) => setForm({ ...form, pinned: e.target.checked })}
                data-testid="welcome-news-pinned"
              />
              Épingler
            </label>
            <button
              onClick={submit}
              className="ml-auto bg-[#0044FF] text-white px-3 py-1 text-xs uppercase tracking-wider"
              data-testid="welcome-news-submit"
            >
              Publier
            </button>
          </div>
        </div>
      )}
      {news.length === 0 ? (
        <div className="text-xs text-muted-foreground py-2">Aucune actualité pour le moment.</div>
      ) : (
        <div className="divide-y divide-border">
          {news.map((n) => (
            <div key={n.id} className="py-2.5" data-testid={`welcome-news-item-${n.id}`}>
              <div className="flex items-start gap-2">
                <span
                  className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: SEVERITY_COLOR[n.severity] || "#71717a" }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{n.title}</span>
                    {n.pinned && <Pin size={11} className="text-[#FFB800]" />}
                  </div>
                  <div className="text-xs text-muted-foreground whitespace-pre-wrap mt-0.5">{n.body}</div>
                  <div className="text-[10px] mono text-muted-foreground mt-1">
                    {n.created_by} · {n.created_at?.slice(0, 16).replace("T", " ")}
                  </div>
                </div>
                {isAdmin && (
                  <button
                    onClick={() => onDelete(n.id)}
                    className="text-muted-foreground hover:text-[#FF3333]"
                    title="Supprimer"
                    data-testid={`welcome-news-delete-${n.id}`}
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CentersSection() {
  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-centers">
      <SectionHeader icon={Layers} title="Accès rapide aux Centers" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {CENTERS.map((c) => {
          const Icon = c.icon;
          return (
            <Link
              key={c.to}
              to={c.to}
              className="group border border-border p-3 hover:border-[#0044FF] hover:bg-secondary/40 transition flex flex-col gap-1"
              data-testid={`welcome-center-link-${c.to.replace(/\//g, "")}`}
            >
              <Icon size={16} strokeWidth={1.5} className="text-muted-foreground group-hover:text-[#0044FF]" />
              <div className="text-xs font-medium">{c.label}</div>
              <div className="text-[10px] text-muted-foreground line-clamp-2">{c.desc}</div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

function DocsSection({ onOpenChangelog }) {
  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-docs">
      <SectionHeader icon={BookOpen} title="Documentation" />
      <div className="grid grid-cols-2 gap-2">
        {DOC_LINKS.map((d) => {
          const Icon = d.icon;
          if (d.internal) {
            return (
              <button
                key={d.label}
                onClick={onOpenChangelog}
                className="flex items-center gap-2 border border-border px-3 py-2 hover:bg-secondary/40 text-xs"
                data-testid={`welcome-doc-${d.label}`}
              >
                <Icon size={13} /> {d.label}
              </button>
            );
          }
          return (
            <a
              key={d.label}
              href={d.href}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 border border-border px-3 py-2 hover:bg-secondary/40 text-xs"
              data-testid={`welcome-doc-${d.label}`}
            >
              <Icon size={13} /> {d.label}
            </a>
          );
        })}
      </div>
    </div>
  );
}

function PrefsSection({ prefs, currentVersion, onSave }) {
  const [local, setLocal] = useState({
    hide_until_next_version: !!prefs?.hide_until_next_version,
    always_show: !!prefs?.always_show,
    important_only: !!prefs?.important_only,
  });
  useEffect(() => {
    setLocal({
      hide_until_next_version: !!prefs?.hide_until_next_version,
      always_show: !!prefs?.always_show,
      important_only: !!prefs?.important_only,
    });
  }, [prefs]);

  const toggle = (k) => {
    const patch = { ...local, [k]: !local[k] };
    // Exclusivité always_show ↔ hide_until_next_version
    if (k === "always_show" && patch.always_show) patch.hide_until_next_version = false;
    if (k === "hide_until_next_version" && patch.hide_until_next_version) patch.always_show = false;
    setLocal(patch);
    onSave(patch);
  };

  const markSeen = () => {
    onSave({ last_seen_version: currentVersion });
    toast.success("Version marquée comme vue");
  };

  return (
    <div className="bg-card border border-border p-4" data-testid="welcome-prefs">
      <SectionHeader icon={Settings} title="Préférences d'accueil" />
      <div className="space-y-2">
        {[
          { key: "hide_until_next_version", label: `Ne plus afficher pour ${currentVersion}` },
          { key: "always_show", label: "Toujours afficher (par défaut)" },
          { key: "important_only", label: "Afficher uniquement les nouveautés importantes" },
        ].map((p) => (
          <label
            key={p.key}
            className="flex items-center gap-2 text-xs cursor-pointer hover:bg-secondary/30 px-2 py-1.5"
            data-testid={`welcome-pref-${p.key}`}
          >
            <input
              type="checkbox"
              checked={local[p.key]}
              onChange={() => toggle(p.key)}
              className="accent-[#0044FF]"
            />
            <span>{p.label}</span>
          </label>
        ))}
        <button
          onClick={markSeen}
          className="w-full mt-2 border border-border px-3 py-1.5 text-xs hover:bg-secondary/40 flex items-center justify-center gap-2"
          data-testid="welcome-pref-mark-seen"
        >
          <CheckCircle2 size={13} /> Marquer comme lu
        </button>
      </div>
      <div className="mt-3 text-[10px] text-muted-foreground">
        Version vue actuellement : <span className="mono text-foreground">{prefs?.last_seen_version || "—"}</span>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────

export default function WelcomeCenter() {
  const { user, t } = useApp();
  const [data, setData] = useState(null);
  const [tutorials, setTutorials] = useState([]);
  const [widgets, setWidgets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [changelogExpanded, setChangelogExpanded] = useState(false);
  const isAdmin = user?.role === "admin";

  const load = async () => {
    try {
      const [r, rt, rw] = await Promise.all([
        api.get("/welcome/summary"),
        api.get("/welcome/tutorials"),
        api.get("/welcome/widgets"),
      ]);
      setData(r.data);
      setTutorials(rt.data.items || []);
      setWidgets(rw.data.items || []);
    } catch (e) {
      toast.error(t("welcome.load_failed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const savePrefs = async (patch) => {
    try {
      const r = await api.put("/welcome/preferences", patch);
      setData((d) => (d ? { ...d, prefs: r.data } : d));
    } catch (e) {
      toast.error("Échec sauvegarde préférences");
    }
  };

  const createNews = async (payload) => {
    try {
      await api.post("/welcome/news", payload);
      toast.success(t("welcome.published"));
      await load();
    } catch (e) {
      toast.error(t("welcome.publish_denied"));
    }
  };
  const deleteNews = async (id) => {
    if (!window.confirm(t("welcome.delete_confirm"))) return;
    try {
      await api.delete(`/welcome/news/${id}`);
      await load();
    } catch (e) {
      toast.error(t("welcome.delete_denied"));
    }
  };
  const createTutorial = async (payload) => {
    try {
      await api.post("/welcome/tutorials", payload);
      toast.success(t("welcome.published"));
      await load();
    } catch (e) { toast.error(t("welcome.publish_denied")); }
  };
  const deleteTutorial = async (id) => {
    if (!window.confirm(t("welcome.delete_confirm"))) return;
    try { await api.delete(`/welcome/tutorials/${id}`); await load(); }
    catch (e) { toast.error(t("welcome.delete_denied")); }
  };
  const createWidget = async (payload) => {
    try { await api.post("/welcome/widgets", payload); toast.success(t("welcome.published")); await load(); }
    catch (e) { toast.error(t("welcome.publish_denied")); }
  };
  const deleteWidget = async (id) => {
    if (!window.confirm(t("welcome.delete_confirm"))) return;
    try { await api.delete(`/welcome/widgets/${id}`); await load(); }
    catch (e) { toast.error(t("welcome.delete_denied")); }
  };

  const openChangelog = () => {
    setChangelogExpanded(true);
    setTimeout(() => {
      const el = document.getElementById("changelog");
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 50);
  };

  const greeting = useMemo(() => {
    const h = new Date().getHours();
    if (h < 6) return "Bonne nuit";
    if (h < 12) return "Bonjour";
    if (h < 18) return "Bon après-midi";
    return "Bonsoir";
  }, []);

  if (loading || !data) {
    return (
      <div className="p-8 text-muted-foreground" data-testid="welcome-loading">
        Chargement du Welcome Center...
      </div>
    );
  }

  const { health, version, alerts, tips, news, prefs, changelog, stats } = data;

  return (
    <div className="p-4 space-y-4" data-testid="welcome-center">
      {/* Header */}
      <div className="flex items-end justify-between border-b border-border pb-3">
        <div>
          <div className="text-xs uppercase tracking-[0.15em] text-muted-foreground mb-1">
            MG-VMS · Welcome Center
          </div>
          <h1 className="font-head font-black text-3xl sm:text-4xl tracking-tight">
            {greeting}
            {user?.name ? <span className="text-muted-foreground font-normal">, {user.name}</span> : ""}
          </h1>
        </div>
        <div className="text-right hidden sm:block">
          <div className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">Score système</div>
          <div
            className="font-head font-black text-3xl mono"
            style={{
              color:
                health.score >= 85 ? STATUS_COLOR.ok :
                health.score >= 60 ? STATUS_COLOR.warn : STATUS_COLOR.crit,
            }}
          >
            {health.score}<span className="text-muted-foreground text-lg">/100</span>
          </div>
        </div>
      </div>

      {/* Ligne 1 : Health (2 cols) + Version */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-2">
        <HealthSection health={health} version={version} />
        <VersionSection
          version={version}
          hasNewVersion={changelog?.has_new_version}
          onOpenChangelog={openChangelog}
        />
      </div>

      {/* Ligne 2 : News + Tips + Tutoriels */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-2">
        <NewsSection
          news={news || []}
          isAdmin={isAdmin}
          onCreate={createNews}
          onDelete={deleteNews}
        />
        <TipsSection tips={tips || []} t={t} />
        <TutorialsSection tutorials={tutorials} isAdmin={isAdmin} t={t}
          onCreate={createTutorial} onDelete={deleteTutorial} />
      </div>

      {/* Ligne 3 : Widgets custom (admin) */}
      <WidgetsSection widgets={widgets} isAdmin={isAdmin} t={t}
        onCreate={createWidget} onDelete={deleteWidget} />

      {/* Ligne 4 : Centers */}
      <CentersSection />

      {/* Ligne 5 : Changelog + Docs + Prefs */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-2">
        <div className="lg:col-span-2">
          <ChangelogSection
            changelog={changelog}
            expanded={changelogExpanded}
            onToggle={() => setChangelogExpanded((v) => !v)}
          />
        </div>
        <div className="space-y-2">
          <DocsSection onOpenChangelog={openChangelog} />
          <PrefsSection
            prefs={prefs}
            currentVersion={version?.installed}
            onSave={savePrefs}
          />
        </div>
      </div>
    </div>
  );
}
