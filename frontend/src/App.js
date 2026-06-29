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
import Cameras from "@/pages/Cameras";
import Sites from "@/pages/Sites";
import MapView from "@/pages/MapView";
import Anpr from "@/pages/Anpr";
import VehicleSearch from "@/pages/VehicleSearch";
import Alerts from "@/pages/Alerts";
import Audit from "@/pages/Audit";
import UsersPage from "@/pages/Users";
import SettingsPage from "@/pages/Settings";
import Notifications from "@/pages/Notifications";

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
      <Route path="/cameras" element={<Protected><Cameras /></Protected>} />
      <Route path="/sites" element={<Protected><Sites /></Protected>} />
      <Route path="/map" element={<Protected><MapView /></Protected>} />
      <Route path="/anpr" element={<Protected><Anpr /></Protected>} />
      <Route path="/vehicles" element={<Protected><VehicleSearch /></Protected>} />
      <Route path="/alerts" element={<Protected><Alerts /></Protected>} />
      <Route path="/audit" element={<Protected><Audit /></Protected>} />
      <Route path="/users" element={<Protected><UsersPage /></Protected>} />
      <Route path="/notifications" element={<Protected><Notifications /></Protected>} />
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
