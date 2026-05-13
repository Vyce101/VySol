import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { WorldHubPage } from "./world-hub-page";
import "./styles.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("VySol frontend root was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <WorldHubPage />
  </StrictMode>,
);
