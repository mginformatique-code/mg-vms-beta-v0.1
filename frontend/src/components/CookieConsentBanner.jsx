import React, { useEffect, useState } from "react";
import { Cookie } from "lucide-react";
import { useApp } from "@/context/AppContext";

const CONSENT_KEY = "mg_cookie_consent";

export function hasCookieConsent() {
  return localStorage.getItem(CONSENT_KEY) === "1";
}

export default function CookieConsentBanner({ onOpenPreferences }) {
  const { t } = useApp();
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
        {t("cookie.banner_pre")} <b className="text-foreground">{t("cookie.banner_bold")}</b> {t("cookie.banner_post")}
      </p>
      <div className="flex items-center gap-2 shrink-0">
        <button onClick={() => { onOpenPreferences?.(); }} className="px-3 py-2 border border-border text-xs hover:bg-secondary transition-colors" data-testid="cookie-consent-preferences">
          {t("cookie.learn_more")}
        </button>
        <button onClick={accept} className="px-4 py-2 bg-[#0044FF] text-white text-xs" data-testid="cookie-consent-accept">
          {t("cookie.understood")}
        </button>
      </div>
    </div>
  );
}
