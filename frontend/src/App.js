import "@/App.css";
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppProvider, useApp } from "@/context/AppContext";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import ResetPassword from "@/pages/ResetPassword";
import Dashboard from "@/pages/Dashboard";
import WelcomeCenter from "@/pages/WelcomeCenter";
import LiveView from "@/pages/LiveView";
import Recordings from "@/pages/Recordings";
import Network from "@/pages/Network";
import Reports from "@/pages/Reports";
import Hardware from "@/pages/Hardware";
import Cameras from "@/pages/Cameras";
import Sites from "@/pages/Sites";
import MapView from "@/pages/MapView";
import MapCenter from "@/pages/MapCenter";
import SessionExpiryWatcher from "@/components/SessionExpiryWatcher";
import InactivityWatcher from "@/components/InactivityWatcher";
import SecurityCenter from "@/pages/SecurityCenter";
import TlsSettings from "@/pages/TlsSettings";
import PipelineInspectorLive from "@/pages/PipelineInspectorLive";
import MfaCenter from "@/pages/MfaCenter";
import SessionsCenter from "@/pages/SessionsCenter";
import RbacCenter from "@/pages/RbacCenter";
import Anpr from "@/pages/Anpr";
import Events from "@/pages/Events";
import VehicleSearch from "@/pages/VehicleSearch";
import Vehicles from "@/pages/Vehicles";
import Alerts from "@/pages/Alerts";
import Audit from "@/pages/Audit";
import Diagnostics from "@/pages/Diagnostics";
import HealthDashboard from "@/pages/HealthDashboard";
import GPUStatus from "@/pages/GPUStatus";
import AnprBenchmark from "@/pages/AnprBenchmark";
import PipelineVideo from "@/pages/PipelineVideo";
import AIPipelineMonitor from "@/pages/AIPipelineMonitor";
import PipelineDesigner from "@/pages/PipelineDesigner";
import PipelineInspector from "@/pages/PipelineInspector";
import PipelineCenter from "@/pages/PipelineCenter";
import CameraCenter from "@/pages/CameraCenter";
import UsersPage from "@/pages/Users";
import SettingsPage from "@/pages/Settings";
import Notifications from "@/pages/Notifications";
import Plugins from "@/pages/PluginManagerNG";
import PluginPage from "@/pages/PluginPage";
import SmartZones from "@/pages/SmartZones";
import Timeline from "@/pages/Timeline";
import Workflows from "@/pages/Workflows";

function Protected({ children }) {
  const { user } = useApp();
  if (user === null) return <div className="h-screen flex items-center justify-center bg-background text-muted-foreground">Chargement...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/" element={<Protected><WelcomeCenter /></Protected>} />
      <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
      <Route path="/welcome" element={<Protected><WelcomeCenter /></Protected>} />
      <Route path="/live" element={<Protected><LiveView /></Protected>} />
      <Route path="/recordings" element={<Protected><Recordings /></Protected>} />
      <Route path="/network" element={<Protected><Network /></Protected>} />
      <Route path="/reports" element={<Protected><Reports /></Protected>} />
      <Route path="/hardware" element={<Protected><Hardware /></Protected>} />
      <Route path="/cameras" element={<Protected><Cameras /></Protected>} />
      <Route path="/sites" element={<Protected><Sites /></Protected>} />
      <Route path="/map" element={<Protected><MapCenter /></Protected>} />
      <Route path="/security-center" element={<Protected><SecurityCenter /></Protected>} />
      <Route path="/security-center/tls" element={<Protected><TlsSettings /></Protected>} />
      <Route path="/diagnostics/pipeline-inspector" element={<Protected><PipelineInspectorLive /></Protected>} />
      <Route path="/security-center/mfa" element={<Protected><MfaCenter /></Protected>} />
      <Route path="/security-center/sessions" element={<Protected><SessionsCenter /></Protected>} />
      <Route path="/security-center/rbac" element={<Protected><RbacCenter /></Protected>} />
      <Route path="/map-legacy" element={<Protected><MapView /></Protected>} />
      <Route path="/anpr" element={<Protected><Anpr /></Protected>} />
      <Route path="/smart-zones" element={<Protected><SmartZones /></Protected>} />
      <Route path="/workflows" element={<Protected><Workflows /></Protected>} />
      <Route path="/timeline" element={<Protected><Timeline /></Protected>} />
      <Route path="/events" element={<Protected><Events /></Protected>} />
      <Route path="/vehicles" element={<Protected><Vehicles /></Protected>} />
      <Route path="/vehicles/search" element={<Protected><VehicleSearch /></Protected>} />
      <Route path="/alerts" element={<Protected><Alerts /></Protected>} />
      <Route path="/audit" element={<Protected><Audit /></Protected>} />
      <Route path="/diagnostics" element={<Protected><Diagnostics /></Protected>} />
      <Route path="/diagnostics/dashboard" element={<Protected><HealthDashboard /></Protected>} />
      <Route path="/gpu" element={<Protected><GPUStatus /></Protected>} />
      <Route path="/anpr-benchmark" element={<Protected><AnprBenchmark /></Protected>} />
      <Route path="/pipeline" element={<Protected><PipelineVideo /></Protected>} />
      <Route path="/pipeline-monitor" element={<Protected><AIPipelineMonitor /></Protected>} />
      <Route path="/pipeline-designer" element={<Protected><PipelineDesigner /></Protected>} />
      <Route path="/pipeline-inspector" element={<Protected><PipelineInspector /></Protected>} />
      {/* v0.5.0.b · Alias sous /pipeline/ pour cohérence UX */}
      <Route path="/pipeline/designer" element={<Protected><PipelineDesigner /></Protected>} />
      <Route path="/pipeline/inspector" element={<Protected><PipelineInspector /></Protected>} />
      <Route path="/pipeline-center" element={<Protected><PipelineCenter /></Protected>} />
      <Route path="/camera-center/:cameraId" element={<Protected><CameraCenter /></Protected>} />
      <Route path="/users" element={<Protected><UsersPage /></Protected>} />
      <Route path="/notifications" element={<Protected><Notifications /></Protected>} />
      <Route path="/plugins" element={<Protected><Plugins /></Protected>} />
      <Route path="/plugins/:pluginId" element={<Protected><PluginPage /></Protected>} />
      <Route path="/settings" element={<Protected><SettingsPage /></Protected>} />
      <Route path="/storage" element={<Protected><SettingsPage /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <AppRoutes />
        <SessionExpiryWatcher />
        <InactivityWatcher />
        <Toaster position="top-right" />
      </BrowserRouter>
    </AppProvider>
  );
}

export default App;
