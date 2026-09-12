import React from "react";
import { Cookie } from "lucide-react";
import { hasCookieConsent } from "@/components/CookieConsentBanner";
import { useApp } from "@/context/AppContext";

const ITEMS = [
  { name: "access_token / refresh_token", kindKey: "cookie.kind_http_cookie", purposeKey: "cookie.purpose_auth_session" },
  { name: "mg_token / mg_refresh", kindKey: "cookie.kind_local_storage", purposeKey: "cookie.purpose_auth_session_client" },
  { name: "mg_theme / mg_lang", kindKey: "cookie.kind_local_storage", purposeKey: "cookie.purpose_display_prefs" },
  { name: "mg_welcome_dismissed", kindKey: "cookie.kind_local_storage", purposeKey: "cookie.purpose_hide_welcome" },
  { name: "mg_cookie_consent", kindKey: "cookie.kind_local_storage", purposeKey: "cookie.purpose_remember_ack" },
];

export default function CookieSection() {
  const { t } = useApp();
  return (
    <div className="border border-border p-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.15em] text-muted-foreground mb-2">
        <Cookie size={14} /> {t("cookie.section_title")}
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed mb-3">
        {t("cookie.section_intro")}
      </p>
      <div className="space-y-1.5 mb-3">
        {ITEMS.map((it) => (
          <div key={it.name} className="grid grid-cols-1 sm:grid-cols-[1fr_auto_1.2fr] gap-x-3 gap-y-0.5 text-[11px] border-b border-border/60 pb-1.5 last:border-0">
            <span className="mono text-foreground">{it.name}</span>
            <span className="text-muted-foreground uppercase tracking-wider text-[9px] sm:self-center">{t(it.kindKey)}</span>
            <span className="text-muted-foreground">{t(it.purposeKey)}</span>
          </div>
        ))}
      </div>
      <div className="text-[11px] text-muted-foreground">
        {hasCookieConsent() ? t("cookie.already_acked") : t("cookie.awaiting_ack")}
      </div>
    </div>
  );
}
