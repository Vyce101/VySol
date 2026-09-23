import { useEffect, useState } from "react";
import { ProvidersView } from "./ProvidersView";
import {
  api,
  jsonRequest,
  type Settings,
  type Speed,
  type WorldLayout,
} from "./api";
import type { CollectionPreview } from "./collectionPreview";

export function SettingsView({
  visible,
  speed,
  layout,
  onSaved,
  collectionPreview,
  onCollectionPreview,
  manageKeys,
  onReturnToCreation,
}: {
  visible: boolean;
  speed: Speed;
  layout: WorldLayout;
  onSaved: (settings: Settings) => void;
  collectionPreview: CollectionPreview;
  onCollectionPreview: (preview: CollectionPreview) => void;
  manageKeys?: boolean;
  onReturnToCreation?: () => void;
}) {
  const [section, setSection] = useState("appearance");
  useEffect(() => {
    if (manageKeys) setSection("providers");
  }, [manageKeys]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function save(next: Settings) {
    setSaving(true);
    setError("");
    try {
      onSaved(await api<Settings>("/settings", jsonRequest("PUT", next)));
    } catch {
      setError("Your setting could not be saved. Please try again.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <section
      className={`view settings-view ${visible ? "is-visible" : ""}`}
      aria-hidden={!visible}
      inert={!visible}
    >
      <h1>Settings</h1>
      {manageKeys && (
        <button
          className="text-action return-to-creation"
          onClick={onReturnToCreation}
        >
          ← Return to creation
        </button>
      )}
      <div className="settings-layout">
        <nav aria-label="Settings categories">
          {(["appearance", "providers", "developer"] as const).map((item) => (
            <button
              key={item}
              aria-pressed={section === item}
              onClick={() => setSection(item)}
            >
              {item === "appearance"
                ? "Appearance"
                : item === "providers"
                  ? "Providers"
                  : "Developer"}
            </button>
          ))}
        </nav>
        <div className="settings-content">
          <h2>
            {section === "appearance"
              ? "Appearance"
              : section === "providers"
                ? "Providers"
                : "Developer"}
          </h2>
          {section === "providers" ? (
            visible && <ProvidersView />
          ) : section === "appearance" ? (
            <div className="setting-row">
              <label htmlFor="world-layout">
                World display<span>Choose how you browse your collection.</span>
              </label>
              <select
                id="world-layout"
                value={layout}
                disabled={saving}
                onChange={(event) =>
                  save({
                    background_speed: speed,
                    world_layout: event.target.value as WorldLayout,
                  })
                }
              >
                <option value="shelf">Horizontal shelf</option>
                <option value="grid">Grid</option>
              </select>
            </div>
          ) : (
            <>
              <div className="setting-row">
                <label htmlFor="transition-speed">
                  Background transition speed
                  <span>How gently one world gives way to another.</span>
                </label>
                <select
                  id="transition-speed"
                  value={speed}
                  disabled={saving}
                  onChange={(event) =>
                    save({
                      background_speed: event.target.value as Speed,
                      world_layout: layout,
                    })
                  }
                >
                  <option value="fast">Fast — 150 ms</option>
                  <option value="normal">Normal — 300 ms</option>
                  <option value="slow">Slow — 600 ms</option>
                </select>
              </div>
              <div className="setting-row">
                <label htmlFor="homepage-preview">
                  Homepage preview
                  <span>
                    Temporary samples. Your saved worlds stay untouched.
                  </span>
                </label>
                <select
                  id="homepage-preview"
                  value={collectionPreview}
                  onChange={(event) =>
                    onCollectionPreview(event.target.value as CollectionPreview)
                  }
                >
                  <option value="saved">Your saved worlds</option>
                  <option value="four">4 sample worlds</option>
                  <option value="sample">12 sample worlds</option>
                  <option value="empty">Empty homepage</option>
                </select>
              </div>
            </>
          )}
          {error && (
            <p className="error-message" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
