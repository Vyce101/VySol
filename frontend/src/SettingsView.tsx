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

type SettingsSection = "general" | "connections" | "developer";

export function SettingsView({
  visible,
  speed,
  layout,
  onSaved,
  collectionPreview,
  onCollectionPreview,
  manageKeys,
}: {
  visible: boolean;
  speed: Speed;
  layout: WorldLayout;
  onSaved: (settings: Settings) => void;
  collectionPreview: CollectionPreview;
  onCollectionPreview: (preview: CollectionPreview) => void;
  manageKeys?: boolean;
  onClose?: () => void;
}) {
  const [section, setSection] = useState<SettingsSection>("general");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (manageKeys) setSection("connections");
  }, [manageKeys]);

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
      className={`view settings-view settings-redesign ${visible ? "is-visible" : ""}`}
      aria-hidden={!visible}
      inert={!visible}
    >
      <header className="settings-page-header">
        <h1>Settings</h1>
      </header>

      <div className="settings-layout">
        <nav className="settings-navigation" aria-label="Settings sections">
          {(
            [
              ["general", "General"],
              ["connections", "AI Connections"],
              ["developer", "Developer"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-current={section === id ? "page" : undefined}
              onClick={() => setSection(id)}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="settings-content" key={section}>
          <h2>
            {section === "general"
              ? "General"
              : section === "connections"
                ? "AI Connections"
                : "Developer"}
          </h2>

          {section === "general" && (
            <div className="settings-options">
              <div className="settings-option">
                <label htmlFor="world-layout">
                  <span className="settings-option-title">World Display</span>
                  <span className="settings-option-description">
                    Choose how you browse your collection.
                  </span>
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
                  <option value="shelf">Shelf</option>
                  <option value="grid">Grid</option>
                </select>
              </div>

              <div className="settings-option">
                <label htmlFor="transition-speed">
                  <span className="settings-option-title">
                    Background Transition Speed
                  </span>
                  <span className="settings-option-description">
                    Set how quickly the artwork changes between worlds.
                  </span>
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
                  <option value="fast">Fast</option>
                  <option value="normal">Normal</option>
                  <option value="slow">Slow</option>
                </select>
              </div>
            </div>
          )}

          {section === "connections" && (
            visible && <ProvidersView />
          )}

          {section === "developer" && (
            <div className="settings-options">
              <div className="settings-option">
                <label htmlFor="homepage-preview">
                  <span className="settings-option-title">Homepage Preview</span>
                  <span className="settings-option-description">
                    Show temporary examples while you work on the app.
                  </span>
                </label>
                <select
                  id="homepage-preview"
                  value={collectionPreview}
                  onChange={(event) =>
                    onCollectionPreview(event.target.value as CollectionPreview)
                  }
                >
                  <option value="saved">Your Saved Worlds</option>
                  <option value="four">4 Sample Worlds</option>
                  <option value="sample">12 Sample Worlds</option>
                  <option value="empty">Empty Homepage</option>
                </select>
              </div>
            </div>
          )}

          {error && (
            <p className="settings-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
