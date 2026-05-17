import { Image, Palette, Type, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CommittedWorldDetailResponse } from "./committed-world-api";
import type { DraftWorldDetailResponse } from "./draft-world-api";
import defaultBackgroundUrl from "../../app/assets/images/Main World Image.png";

type WorldMode = "draft" | "committed";

export type CustomizeWorldState =
  | { mode: WorldMode; status: "idle" | "loading" | "error" }
  | { mode: "draft"; status: "loaded"; detail: DraftWorldDetailResponse }
  | {
      mode: "committed";
      status: "loaded";
      detail: CommittedWorldDetailResponse;
    };

type CustomizeFormValues = {
  displayName: string;
  description: string;
  backgroundImageUrl: string;
  backgroundLabel: string;
  fontAssetId: string;
  fontFileUrl: string | null;
  fontLabel: string;
};

const DRAFT_DEFAULT_DISPLAY_NAME = "Untitled World";
const DRAFT_DEFAULT_DESCRIPTION = "";
const DEFAULT_BACKGROUND_LABEL = "Main World Image";
const DEFAULT_FONT_ASSET_ID = "builtin-font-inter";
const DEFAULT_FONT_LABEL = "Inter";
const DEFAULT_FONT_STACK =
  '"VySol Default Inter", Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

const BUILT_IN_ASSET_LABELS: Record<string, string> = {
  "builtin-font-almendra-bold": "Almendra Bold",
  "builtin-font-cinzel-bold": "Cinzel Bold",
  "builtin-font-im-fell-english-sc-regular": "IM Fell English SC Regular",
  "builtin-font-inter": "Inter",
  "builtin-font-orbitron-bold": "Orbitron Bold",
  "builtin-image-dark-academy": "Dark Academy",
  "builtin-image-desert-ruins": "Desert Ruins",
  "builtin-image-fantasy-valley": "Fantasy Valley",
  "builtin-image-main-world": "Main World Image",
  "builtin-image-moonlit-shrine": "Moonlit Shrine",
  "builtin-image-neon-city": "Neon City",
  "builtin-image-ruined-battlefield": "Ruined Battlefield",
  "builtin-image-sky-islands": "Sky Islands",
  "builtin-image-snowfield-aurora": "Snowfield Aurora",
};

export function WorldDetailCustomizeTab({ state }: { state: CustomizeWorldState }) {
  const sourceKey = getCustomizeSourceKey(state);
  const initialValues = useMemo(() => getInitialFormValues(state), [sourceKey]);
  const [formValues, setFormValues] = useState(initialValues);
  const titleFontFamily = useCustomizeTitleFont(formValues);

  useEffect(() => {
    setFormValues(initialValues);
  }, [initialValues]);

  if (state.status === "idle" && state.mode === "committed") {
    return (
      <section className="customize-layout" aria-label="Customize">
        <CustomizeStatusMessage title="Committed world values are not loaded" />
      </section>
    );
  }

  if (state.status === "loading") {
    return (
      <section className="customize-layout" aria-label="Customize">
        <CustomizeStatusMessage title="Loading customize fields" />
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="customize-layout" aria-label="Customize">
        <CustomizeStatusMessage title={`${getModeLabel(state.mode)} values could not be loaded`} />
      </section>
    );
  }

  return (
    <section className="customize-layout" aria-label="Customize">
      <header className="customize-hero">
        <h1 style={{ fontFamily: titleFontFamily }}>
          {formValues.displayName || DRAFT_DEFAULT_DISPLAY_NAME}
        </h1>
        {formValues.description ? <p>{formValues.description}</p> : null}
      </header>
      <div className="customize-form-grid">
        <section className="customize-panel" aria-labelledby="customize-identity-title">
          <div className="customize-panel-heading">
            <UserRound aria-hidden="true" />
            <h2 id="customize-identity-title">World Identity</h2>
          </div>
          <label className="customize-field">
            <span>World Name</span>
            <input
              type="text"
              value={formValues.displayName}
              onChange={(event) =>
                setFormValues((currentValues) => ({
                  ...currentValues,
                  displayName: event.target.value,
                }))
              }
            />
          </label>
          <label className="customize-field">
            <span>Description</span>
            <textarea
              value={formValues.description}
              onChange={(event) =>
                setFormValues((currentValues) => ({
                  ...currentValues,
                  description: event.target.value,
                }))
              }
              rows={7}
            />
          </label>
        </section>

        <section className="customize-panel" aria-labelledby="customize-style-title">
          <div className="customize-panel-heading">
            <Palette aria-hidden="true" />
            <h2 id="customize-style-title">Visual Style</h2>
          </div>
          <div className="customize-preview-group">
            <span className="customize-preview-label">Background</span>
            <div className="customize-background-preview">
              <img src={formValues.backgroundImageUrl} alt="" draggable={false} />
              <div className="customize-background-preview-copy">
                <Image aria-hidden="true" />
                <span>{formValues.backgroundLabel}</span>
              </div>
            </div>
          </div>
          <div className="customize-preview-group">
            <span className="customize-preview-label">World Font</span>
            <div className="customize-font-preview">
              <Type aria-hidden="true" />
              <div>
                <span>{formValues.fontLabel}</span>
                <strong style={{ fontFamily: titleFontFamily }}>
                  {formValues.displayName || DRAFT_DEFAULT_DISPLAY_NAME}
                </strong>
              </div>
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}

function CustomizeStatusMessage({ title }: { title: string }) {
  return (
    <div className="customize-status-message" role="status">
      {title}
    </div>
  );
}

function useCustomizeTitleFont(formValues: CustomizeFormValues): string {
  const fontFamily = useMemo(
    () => `"${getCustomizeFontFamilyName(formValues.fontAssetId)}", ${DEFAULT_FONT_STACK}`,
    [formValues.fontAssetId],
  );

  useEffect(() => {
    if (formValues.fontFileUrl === null) {
      return;
    }

    const styleElement = document.createElement("style");
    styleElement.dataset.worldDetailCustomizeFont = formValues.fontAssetId;
    styleElement.textContent = buildCustomizeFontFaceRule(formValues);
    document.head.appendChild(styleElement);

    return () => {
      styleElement.remove();
    };
  }, [formValues.fontAssetId, formValues.fontFileUrl]);

  return fontFamily;
}

function getInitialFormValues(state: CustomizeWorldState): CustomizeFormValues {
  if (state.status !== "loaded") {
    return getDraftDefaultFormValues();
  }

  if (state.mode === "draft") {
    return getDraftDefaultFormValues();
  }

  return {
    displayName: state.detail.display_name,
    description: state.detail.description ?? "",
    backgroundImageUrl: state.detail.background_image_url,
    backgroundLabel: getAssetLabel(state.detail.background_asset_id),
    fontAssetId: state.detail.font_asset_id,
    fontFileUrl: state.detail.font_file_url,
    fontLabel: getAssetLabel(state.detail.font_asset_id),
  };
}

function getDraftDefaultFormValues(): CustomizeFormValues {
  return {
    displayName: DRAFT_DEFAULT_DISPLAY_NAME,
    description: DRAFT_DEFAULT_DESCRIPTION,
    backgroundImageUrl: defaultBackgroundUrl,
    backgroundLabel: DEFAULT_BACKGROUND_LABEL,
    fontAssetId: DEFAULT_FONT_ASSET_ID,
    fontFileUrl: null,
    fontLabel: DEFAULT_FONT_LABEL,
  };
}

function getCustomizeSourceKey(state: CustomizeWorldState): string {
  if (state.status !== "loaded") {
    return `${state.mode}-${state.status}`;
  }

  if (state.mode === "draft") {
    return `${state.mode}-${state.detail.draft_id}`;
  }

  return [
    state.mode,
    state.detail.world_id,
    state.detail.display_name,
    state.detail.description ?? "",
    state.detail.background_asset_id,
    state.detail.font_asset_id,
  ].join(":");
}

function getAssetLabel(assetId: string): string {
  return BUILT_IN_ASSET_LABELS[assetId] ?? assetId;
}

function getCustomizeFontFamilyName(fontAssetId: string): string {
  return `VySol Customize ${fontAssetId.replaceAll(/[^A-Za-z0-9_-]/g, "-")}`;
}

function buildCustomizeFontFaceRule(formValues: CustomizeFormValues): string {
  return `
@font-face {
  font-family: "${getCustomizeFontFamilyName(formValues.fontAssetId)}";
  src: url("${formValues.fontFileUrl}") format("truetype");
  font-display: swap;
}`;
}

function getModeLabel(mode: WorldMode): string {
  return mode === "draft" ? "Draft world" : "Committed world";
}
