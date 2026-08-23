import React from "react";
import { Cookie } from "lucide-react";
import { hasCookieConsent } from "@/components/CookieConsentBanner";

const ITEMS = [
  { name: "access_token / refresh_token", kind: "Cookie (HttpOnly)", purpose: "Session d'authentification" },
  { name: "mg_token / mg_refresh", kind: "Stockage local", purpose: "Session d'authentification (client)" },
  { name: "mg_theme / mg_lang", kind: "Stockage local", purpose: "Préférences d'affichage (thème, langue)" },
  { name: "mg_welcome_dismissed", kind: "Stockage local", purpose: "Masquer le popup de bienvenue" },
  { name: "mg_cookie_consent", kind: "Stockage local", purpose: "Mémorise que ce message a été lu" },
];

export default function CookieSection() {
  return (
    <div className="border border-border p-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-2">
        <Cookie size={14} /> Cookies &amp; stockage local
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed mb-3">
        Tous strictement nécessaires au fonctionnement de MG-VMS — aucun traceur publicitaire ni analytique tiers,
        donc rien à personnaliser ou désactiver.
      </p>
      <div className="space-y-1.5 mb-3">
        {ITEMS.map((it) => (
          <div key={it.name} className="grid grid-cols-1 sm:grid-cols-[1fr_auto_1.2fr] gap-x-3 gap-y-0.5 text-[11px] border-b border-border/60 pb-1.5 last:border-0">
            <span className="mono text-foreground">{it.name}</span>
            <span className="text-muted-foreground uppercase tracking-wider text-[9px] sm:self-center">{it.kind}</span>
            <span className="text-muted-foreground">{it.purpose}</span>
          </div>
        ))}
      </div>
      <div className="text-[11px] text-muted-foreground">
        {hasCookieConsent() ? "Message d'information déjà acquitté." : "En attente d'acquittement — voir le bandeau en bas de page."}
      </div>
    </div>
  );
}
