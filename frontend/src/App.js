import "@/App.css";
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppProvider, useApp } from "@/context/AppContext";
import { Toaster } from "@/components/ui/sonner";
import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import ResetPassword from "@/pages/ResetPassword";
import Dashboard from "@/pages/Dashboard";
import LiveView from "@/pages/LiveView";
import Recordings from "@/pages/Recordings";
import Network from "@/pages/Network";
import Reports from "@/pages/Reports";
import Hardware from "@/pages/Hardware";
import Cameras from "@/pages/Cameras";
import Sites from "@/pages/Sites";
import MapView from "@/pages/MapView";
import Anpr from "@/pages/Anpr";
import Events from "@/pages/Events";
import VehicleSearch from "@/pages/VehicleSearch";
import Alerts from "@/pages/Alerts";
import Audit from "@/pages/Audit";
import Diagnostics from "@/pages/Diagnostics";
import HealthDashboard from "@/pages/HealthDashboard";
import GPUStatus from "@/pages/GPUStatus";
import AnprBenchmark from "@/pages/AnprBenchmark";
import PipelineVideo from "@/pages/PipelineVideo";
import AIPipelineMonitor from "@/pages/AIPipelineMonitor";
import UsersPage from "@/pages/Users";
import SettingsPage from "@/pages/Settings";
import Notifications from "@/pages/Notifications";
import Plugins from "@/pages/Plugins";
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
      <Route path="/" element={<Protected><Dashboard /></Protected>} />
      <Route path="/live" element={<Protected><LiveView /></Protected>} />
      <Route path="/recordings" element={<Protected><Recordings /></Protected>} />
      <Route path="/network" element={<Protected><Network /></Protected>} />
      <Route path="/reports" element={<Protected><Reports /></Protected>} />
      <Route path="/hardware" element={<Protected><Hardware /></Protected>} />
      <Route path="/cameras" element={<Protected><Cameras /></Protected>} />
      <Route path="/sites" element={<Protected><Sites /></Protected>} />
      <Route path="/map" element={<Protected><MapView /></Protected>} />
      <Route path="/anpr" element={<Protected><Anpr /></Protected>} />
      <Route path="/smart-zones" element={<Protected><SmartZones /></Protected>} />
      <Route path="/workflows" element={<Protected><Workflows /></Protected>} />
      <Route path="/timeline" element={<Protected><Timeline /></Protected>} />
      <Route path="/events" element={<Protected><Events /></Protected>} />
      <Route path="/vehicles" element={<Protected><VehicleSearch /></Protected>} />
      <Route path="/alerts" element={<Protected><Alerts /></Protected>} />
      <Route path="/audit" element={<Protected><Audit /></Protected>} />
      <Route path="/diagnostics" element={<Protected><Diagnostics /></Protected>} />
      <Route path="/diagnostics/dashboard" element={<Protected><HealthDashboard /></Protected>} />
      <Route path="/gpu" element={<Protected><GPUStatus /></Protected>} />
      <Route path="/anpr-benchmark" element={<Protected><AnprBenchmark /></Protected>} />
      <Route path="/pipeline" element={<Protected><PipelineVideo /></Protected>} />
      <Route path="/pipeline-monitor" element={<Protected><AIPipelineMonitor /></Protected>} />
      <Route path="/users" element={<Protected><UsersPage /></Protected>} />
      <Route path="/notifications" element={<Protected><Notifications /></Protected>} />
      <Route path="/plugins" element={<Protected><Plugins /></Protected>} />
      <Route path="/plugins/:pluginId" element={<Protected><PluginPage /></Protected>} />
      <Route path="/settings" element={<Protected><SettingsPage /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <AppRoutes />
        <Toaster position="top-right" />
      </BrowserRouter>
    </AppProvider>
  );
}

export default App;
