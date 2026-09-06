import React from "react";
import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Bell, Sparkles } from "lucide-react";
import { useApp } from "@/context/AppContext";
import Alerts from "@/pages/Alerts";
import AnomalyCenter from "@/pages/AnomalyCenter";

/**
 * v3.27 · Fusion des menus "Alertes" et "Anomalies IA" en un seul —
 * demande explicite ("un seul menu pour les alertes IA"). Les deux
 * systèmes restent complètement séparés côté backend (Alertes = ancien
 * moteur événements caméra `db.alerts`/routers.py ; Anomalies IA =
 * moteur dédié `db.vehicle_anomaly_reports`, voir vehicle_anomaly_ai.py)
 * — fusion volontairement UI seule (deux onglets), pas de refonte du
 * modèle de données legacy (déjà identifié séparément comme à auditer).
 */
export default function AiAlertsCenter() {
  const { t } = useApp();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "anomalies" ? "anomalies" : "alerts";
  const setTab = (v) => setParams(v === "alerts" ? {} : { tab: v }, { replace: true });

  return (
    <Tabs value={tab} onValueChange={setTab}>
      <div className="px-4 pt-4">
        <TabsList data-testid="ai-alerts-tabs">
          <TabsTrigger value="alerts" data-testid="ai-alerts-tab-alerts" className="gap-1.5">
            <Bell size={14} /> {t("nav.alerts")}
          </TabsTrigger>
          <TabsTrigger value="anomalies" data-testid="ai-alerts-tab-anomalies" className="gap-1.5">
            <Sparkles size={14} /> {t("nav.anomalies")}
          </TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="alerts"><Alerts /></TabsContent>
      <TabsContent value="anomalies"><AnomalyCenter /></TabsContent>
    </Tabs>
  );
}
