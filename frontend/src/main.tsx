import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { WorldDetailPage } from "./world-detail-page";
import { WorldHubPage } from "./world-hub-page";
import "./styles.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("VySol frontend root was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

function App() {
  const routeSearch = useRouteSearch();

  if (isWorldDetailRoute(routeSearch)) {
    return <WorldDetailPage />;
  }

  return <WorldHubPage />;
}

function useRouteSearch(): string {
  const [routeSearch, setRouteSearch] = useState(window.location.search);

  useEffect(() => {
    const updateRouteSearch = () => {
      setRouteSearch(window.location.search);
    };

    window.addEventListener("popstate", updateRouteSearch);
    return () => window.removeEventListener("popstate", updateRouteSearch);
  }, []);

  return routeSearch;
}

function isWorldDetailRoute(routeSearch: string): boolean {
  const query = new URLSearchParams(routeSearch);
  return query.has("mode") || query.has("draftId");
}
