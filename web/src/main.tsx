import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "leaflet/dist/leaflet.css";
import "./styles.css";
import { Dashboard } from "./pages/Dashboard";
import { PickSlip } from "./pages/PickSlip";
import { IssuedSummary } from "./pages/IssuedSummary";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/pickslip" element={<PickSlip />} />
        <Route path="/issued" element={<IssuedSummary />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
