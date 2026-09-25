import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/literata/index.css";
import "@fontsource/cormorant-garamond/400.css";
import "@fontsource/cormorant-garamond/500.css";
import "@fontsource/eb-garamond/400.css";
import "@fontsource/eb-garamond/400-italic.css";
import { App } from "./App";
import "./styles.css";
import "./settings-redesign.css";
import "./worlds-redesign.css";
import "./chronicles.css";
import "./scrollbar-visibility.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
