import React, { useEffect, useState } from "react";
import { Cookie } from "lucide-react";

const CONSENT_KEY = "mg_cookie_consent";

export function hasCookieConsent() {
  return localStorage.getItem(CONSENT_KEY) === "1";
}

export default function CookieConsentBanner({ onOpenPreferences }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!hasCookieConsent()) setVisible(true);
  }, []);

  if (!visible) return null;

  const accept = () => {
    localStorage.setItem(CONSENT_KEY, "1");
    setVisible(false);
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 z-[190] bg-card border-t border-border p-4 flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-4" data-testid="cookie-consent-banner">
      <Cookie size={20} className="text-[#0044FF] shrink-0" />
      <p className="text-xs text-muted-foreground leading-relaxed flex-1">
        MG-VMS utilise des cookies et stockage local <b className="text-foreground">strictement nécessaires</b> au
        fonctionnement (session, préférences d&apos;affichage) — aucun traceur publicitaire ni analytique tiers.
      </p>
      <div className="flex items-center gap-2 shrink-0">
        <button onClick={() => { onOpenPreferences?.(); }} className="px-3 py-2 border border-border text-xs hover:bg-secondary transition-colors" data-testid="cookie-consent-preferences">
          En savoir plus
        </button>
        <button onClick={accept} className="px-4 py-2 bg-[#0044FF] text-white text-xs" data-testid="cookie-consent-accept">
          J&apos;ai compris
        </button>
      </div>
    </div>
  );
}
