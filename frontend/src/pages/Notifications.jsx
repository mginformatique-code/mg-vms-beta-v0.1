import React, { useEffect, useState } from "react";
import { useApp } from "@/context/AppContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Mail, MessageSquare, Send, Save, Loader2, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

const empty = {
  smtp: { enabled: false, host: "", port: 587, username: "", password: "", from_email: "", to_email: "", tls: true, has_password: false },
  discord: { enabled: false, webhook_url: "", has_webhook_url: false },
  telegram: { enabled: false, bot_token: "", chat_id: "", has_bot_token: false },
};

const Inp = (p) => <input {...p} className="w-full px-3 py-2 bg-card border border-input outline-none text-sm focus:border-[#0044FF]" />;
const Lbl = ({ children }) => <label className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{children}</label>;

export default function Notifications() {
  const { t, can } = useApp();
  const [cfg, setCfg] = useState(empty);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState("");
  const isAdmin = can("admin");

  useEffect(() => { api.get("/notifications/settings").then((r) => setCfg({ ...empty, ...r.data })).catch(() => {}); }, []);

  const upd = (ch, k, v) => setCfg((c) => ({ ...c, [ch]: { ...c[ch], [k]: v } }));

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        smtp: { enabled: cfg.smtp.enabled, host: cfg.smtp.host, port: Number(cfg.smtp.port) || 587, username: cfg.smtp.username, password: cfg.smtp.password, from_email: cfg.smtp.from_email, to_email: cfg.smtp.to_email, tls: cfg.smtp.tls },
        discord: { enabled: cfg.discord.enabled, webhook_url: cfg.discord.webhook_url },
        telegram: { enabled: cfg.telegram.enabled, bot_token: cfg.telegram.bot_token, chat_id: cfg.telegram.chat_id },
      };
      const { data } = await api.put("/notifications/settings", payload);
      setCfg({ ...empty, ...data });
      toast.success(t("notif.saved"));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setSaving(false); }
  };

  const test = async (channel) => {
    setTesting(channel);
    try { await api.post(`/notifications/test?channel=${channel}`); toast.success(t("notif.test_ok")); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); } finally { setTesting(""); }
  };

  const ChannelHead = ({ ch, icon: Icon, name }) => (
    <div className="flex items-center justify-between mb-4 pb-3 border-b border-border">
      <div className="flex items-center gap-2"><Icon size={18} className="text-[#0044FF]" /><span className="font-head font-semibold">{name}</span>
        {cfg[ch].enabled && <span className="text-[9px] uppercase tracking-wider mg-online flex items-center gap-1"><CheckCircle2 size={12} /> {t("common.active")}</span>}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">{cfg[ch].enabled ? t("common.active") : t("notif.disabled")}</span>
        <Switch checked={cfg[ch].enabled} onCheckedChange={(v) => upd(ch, "enabled", v)} disabled={!isAdmin} data-testid={`notif-${ch}-toggle`} />
      </div>
    </div>
  );

  const placeholder = (has) => (has ? "•••••••• (déjà enregistré, laisser vide pour conserver)" : "");

  return (
    <div className="p-4 max-w-2xl">
      <h1 className="font-head font-bold text-2xl tracking-tight mb-1">{t("notif.title")}</h1>
      <p className="text-sm text-muted-foreground mb-4">{t("notif.subtitle")}</p>

      <Tabs defaultValue="smtp">
        <TabsList className="rounded-none bg-card border border-border">
          <TabsTrigger value="smtp" className="rounded-none" data-testid="tab-smtp"><Mail size={14} className="mr-1.5" /> Email</TabsTrigger>
          <TabsTrigger value="discord" className="rounded-none" data-testid="tab-discord"><MessageSquare size={14} className="mr-1.5" /> Discord</TabsTrigger>
          <TabsTrigger value="telegram" className="rounded-none" data-testid="tab-telegram"><Send size={14} className="mr-1.5" /> Telegram</TabsTrigger>
        </TabsList>

        <TabsContent value="smtp" className="mt-3">
          <div className="bg-card border border-border p-5">
            <ChannelHead ch="smtp" icon={Mail} name="SMTP / Email" />
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2"><Lbl>Serveur SMTP (host)</Lbl><Inp value={cfg.smtp.host} disabled={!isAdmin} onChange={(e) => upd("smtp", "host", e.target.value)} placeholder="smtp.gmail.com" data-testid="smtp-host" /></div>
              <div><Lbl>Port</Lbl><Inp type="number" value={cfg.smtp.port} disabled={!isAdmin} onChange={(e) => upd("smtp", "port", e.target.value)} data-testid="smtp-port" /></div>
              <label className="flex items-end gap-2 pb-2 text-sm"><Switch checked={cfg.smtp.tls} disabled={!isAdmin} onCheckedChange={(v) => upd("smtp", "tls", v)} /> TLS</label>
              <div><Lbl>{t("common.email")} (login)</Lbl><Inp value={cfg.smtp.username} disabled={!isAdmin} onChange={(e) => upd("smtp", "username", e.target.value)} data-testid="smtp-username" /></div>
              <div><Lbl>{t("common.password")}</Lbl><Inp type="password" value={cfg.smtp.password} disabled={!isAdmin} onChange={(e) => upd("smtp", "password", e.target.value)} placeholder={placeholder(cfg.smtp.has_password)} data-testid="smtp-password" /></div>
              <div><Lbl>Expéditeur (from)</Lbl><Inp value={cfg.smtp.from_email} disabled={!isAdmin} onChange={(e) => upd("smtp", "from_email", e.target.value)} data-testid="smtp-from" /></div>
              <div><Lbl>Destinataire (to)</Lbl><Inp value={cfg.smtp.to_email} disabled={!isAdmin} onChange={(e) => upd("smtp", "to_email", e.target.value)} data-testid="smtp-to" /></div>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="discord" className="mt-3">
          <div className="bg-card border border-border p-5">
            <ChannelHead ch="discord" icon={MessageSquare} name="Discord" />
            <Lbl>Webhook URL</Lbl>
            <Inp type="password" value={cfg.discord.webhook_url} disabled={!isAdmin} onChange={(e) => upd("discord", "webhook_url", e.target.value)} placeholder={cfg.discord.has_webhook_url ? "•••••••• (déjà enregistré)" : "https://discord.com/api/webhooks/..."} data-testid="discord-webhook" />
            <p className="text-[11px] text-muted-foreground mt-2">Discord → Paramètres du salon → Intégrations → Webhooks → Nouveau webhook → Copier l'URL.</p>
          </div>
        </TabsContent>

        <TabsContent value="telegram" className="mt-3">
          <div className="bg-card border border-border p-5">
            <ChannelHead ch="telegram" icon={Send} name="Telegram" />
            <div className="space-y-3">
              <div><Lbl>Bot Token</Lbl><Inp type="password" value={cfg.telegram.bot_token} disabled={!isAdmin} onChange={(e) => upd("telegram", "bot_token", e.target.value)} placeholder={cfg.telegram.has_bot_token ? "•••••••• (déjà enregistré)" : "123456:ABC-DEF..."} data-testid="telegram-token" /></div>
              <div><Lbl>Chat ID</Lbl><Inp value={cfg.telegram.chat_id} disabled={!isAdmin} onChange={(e) => upd("telegram", "chat_id", e.target.value)} placeholder="-1001234567890" data-testid="telegram-chatid" /></div>
            </div>
            <p className="text-[11px] text-muted-foreground mt-2">Créez un bot via @BotFather, puis récupérez le chat_id (le bot doit être membre du salon).</p>
          </div>
        </TabsContent>
      </Tabs>

      <div className="flex items-center gap-2 mt-4">
        {isAdmin && <button onClick={save} disabled={saving} data-testid="notif-save-btn" className="flex items-center gap-2 px-4 py-2 bg-[#0044FF] text-white text-sm hover:bg-[#0033cc]">{saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} {t("common.save")}</button>}
        <div className="flex gap-2 ml-auto">
          {["smtp", "discord", "telegram"].map((ch) => (
            <button key={ch} onClick={() => test(ch)} disabled={testing === ch} data-testid={`notif-test-${ch}`} className="flex items-center gap-1.5 px-3 py-2 border border-border text-sm hover:bg-secondary capitalize">
              {testing === ch ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} {t("notif.test")} {ch}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
